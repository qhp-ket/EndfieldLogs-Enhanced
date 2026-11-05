using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Realtime;

public sealed record LiveAllocationDiagnostics(int AllocatedHits, int ReusedHits, long TotalAllocatedHits, long TotalReusedHits,
    int FinalizedHits, BigInteger? PendingStartLine, long Replays, string LastReplayReason, long InkReplays, string LastInkReplayReason);

/// <summary>One live analysis owns its contiguous allocation frontier, dependency snapshots and continuing ink ledger.</summary>
public sealed partial class LiveAllocationCache
{
    private sealed record Entry(ReportHitInput Input, EvidenceObject Output)
    {
        internal readonly bool InputReflexive = SameMap(Input.Baseline, Input.Baseline)
            && SameMap(Input.BasicAttributes, Input.BasicAttributes) && SameMap(Input.Attributes, Input.Attributes);
        internal readonly bool IntegerTime = Time(Input) is EvidenceInteger;
        internal EvidenceObject? OwnedInput, OwnedOutput;
        internal ReportHitInput? OwnedReport;
    }
    private DependencySnapshot[]? dependencies;
    private readonly FrozenEvidence.Context snapshots = new();
    private List<Entry> previous = [], current = [];
    private int finalized, reuseLimit, allocated, reused;
    private long totalAllocated, totalReused, replays, inkReplays;
    private string lastReplayReason = "", lastInkReplayReason = "";
    private BigInteger? pendingLine;
    private InkProvenanceStream? ink;
    private InkTraceLine[] inkLines = [];
    private InkObservationInput? inkInput;
    private Dictionary<BigInteger, EvidenceObject> normalShares = [], inkOutputs = [];
    private Dictionary<EffectSignature, EvidenceObject> inkBindings = [];
    private List<EvidenceObject> contributionRows = [];
    private readonly record struct ContributionUndo(string Key, bool Existed, double Total, double Maximum);
    private readonly List<ContributionUndo> contributionUndo = [];
    private readonly List<int> contributionEnds = [];
    private readonly List<string> contributionKeys = [];
    private readonly Dictionary<string, double> contributionTotals = new(StringComparer.Ordinal), contributionMaxima = new(StringComparer.Ordinal);
    public EffectRecordCache RecordAnalyses { get; } = new();
    public EffectRecordCache PreflightAnalyses { get; } = new();
    internal LiveHitPreparationCache HitPreparation { get; } = new();
    internal LiveSourcePreparationCache SourcePreparation { get; } = new();
    internal LiveHitAccountingCache HitAccounting { get; } = new();
    internal LiveParticipantCache ParticipantCounters { get; } = new();
    private bool ownedContributions;
    private bool previousOnlyIntegerTimes, currentOnlyIntegerTimes;
    internal long ComparedHitInputs { get; private set; }
    private static readonly EvidenceValue NegativeInfinity = new EvidenceReal(double.NegativeInfinity);
    private static readonly EvidenceValue PositiveInfinity = new EvidenceReal(double.PositiveInfinity);
    private static readonly EvidenceValue Zero = new EvidenceInteger(0);

    public LiveAllocationDiagnostics Diagnostics => new(allocated, reused, totalAllocated, totalReused, finalized,
        pendingLine, replays, lastReplayReason, inkReplays, lastInkReplayReason);
    public IReadOnlyDictionary<string, double> Maxima => ContributionSnapshot(contributionMaxima);
    private Dictionary<string, double> ContributionSnapshot(Dictionary<string, double> values)
        => contributionKeys.ToDictionary(key => key, key => values[key], StringComparer.Ordinal);

    private void RewindContributions(int first)
    {
        var end = first == 0 ? 0 : contributionEnds[first - 1];
        for (var index = contributionUndo.Count - 1; index >= end; index--)
        {
            var undo = contributionUndo[index];
            if (undo.Existed)
            {
                contributionTotals[undo.Key] = undo.Total;
                contributionMaxima[undo.Key] = undo.Maximum;
            }
            else
            {
                contributionTotals.Remove(undo.Key); contributionMaxima.Remove(undo.Key);
                contributionKeys.RemoveAt(contributionKeys.Count - 1);
            }
        }
        contributionUndo.RemoveRange(end, contributionUndo.Count - end);
        contributionEnds.RemoveRange(first, contributionEnds.Count - first);
    }
    private static EvidenceObject Copy(EvidenceObject value) => (EvidenceObject)BuffEvidence.Clone(value);
    private EvidenceObject[] ChangedRecords(IReadOnlyList<EvidenceObject>? previous, IReadOnlyList<EvidenceObject> rows) =>
        rows.Select((row, index) => previous is not null && index < previous.Count
            && (ReferenceEquals(previous[index], row) || EvidenceJson.PythonEquals(previous[index], row))
            ? previous[index] : (EvidenceObject)snapshots.Capture(row)).ToArray();
    private static EvidenceValue At(EvidenceObject row, string key, string fallback) => row.Fields.TryGetValue(key, out var value) ? value : row.Get(fallback);
    private static EffectSignature Identity(EvidenceObject row) => new([row.Get("uid"), row.Get("event_key"),
        At(row, "ts_ms", "start_ts_ms"), At(row, "line_no", "start_line_no"), row.Get("target_actor_id")]);
    private static EvidenceValue Stamp(EvidenceObject row, EvidenceValue? fallback = null)
    {
        foreach (var key in new[] { "ts_ms", "start_ts_ms", "snapshot_ts_ms" })
            if (row.Get(key) is EvidenceInteger or EvidenceReal or EvidenceBoolean) return row.Get(key);
        return fallback ?? NegativeInfinity;
    }
    private static EvidenceValue Min(EvidenceValue a, EvidenceValue b) => EffectIdentity.CompareKeys(a, b) <= 0 ? a : b;
    private static EvidenceValue Time(ReportHitInput hit)
    {
        var time = hit.Evidence.Get("ts_ms");
        return CatalogValues.Truth(time) ? time : Zero;
    }

    private static EvidenceValue ChangeAt(EvidenceValue old, EvidenceValue next, EvidenceValue start)
    {
        if (EvidenceJson.PythonEquals(old, next)) return PositiveInfinity;
        if (old is EvidenceObject a && next is EvidenceObject b)
        {
            start = Stamp(b, Stamp(a, start));
            var earliest = PositiveInfinity;
            foreach (var key in a.Fields.Keys.Concat(b.Fields.Keys).Distinct(StringComparer.Ordinal))
            {
                var before = a.Get(key); var after = b.Get(key);
                if (EvidenceJson.PythonEquals(before, after)) continue;
                if (key is "_dynamic_pending_state" or "_dynamic_seen_contexts" or "_dynamic_unresolved_keys" or "packet_modifier_last_seen_ts_ms") continue;
                EvidenceValue changed;
                if (key is "end_ts_ms" or "snapshot_end_ts_ms")
                {
                    var values = new[] { before, after }.Where(value => value is EvidenceInteger or EvidenceReal or EvidenceBoolean).ToArray();
                    changed = values.Length == 0 ? start : values.Aggregate(Min);
                }
                else if (key is "duration_ms" or "end_line_no" or "snapshot_end_line_no" or "end_is_observation_boundary")
                {
                    var values = new[] { a.Get("end_ts_ms"), a.Get("snapshot_end_ts_ms"), b.Get("end_ts_ms"), b.Get("snapshot_end_ts_ms") }
                        .Where(value => value is EvidenceInteger or EvidenceReal or EvidenceBoolean).ToArray();
                    changed = values.Length == 0 ? start : values.Aggregate(Min);
                }
                else changed = ChangeAt(before, after, start);
                earliest = Min(earliest, changed);
            }
            return earliest;
        }
        if (old is EvidenceArray rows && next is EvidenceArray updates)
        {
            if (rows.Items.Count == updates.Items.Count)
                return rows.Items.Zip(updates.Items).Select(pair => ChangeAt(pair.First, pair.Second, start)).Aggregate(PositiveInfinity, Min);
            if (updates.Items.Count > rows.Items.Count && rows.Items.Zip(updates.Items).All(pair => EvidenceJson.PythonEquals(pair.First, pair.Second)))
            {
                var added = updates.Items.Skip(rows.Items.Count).ToArray();
                if (added.All(value => value is EvidenceObject row && !EvidenceJson.PythonEquals(Stamp(row), NegativeInfinity)))
                    return added.Cast<EvidenceObject>().Select(row => Stamp(row)).Aggregate(PositiveInfinity, Min);
            }
        }
        return start;
    }

    private static bool SameMap(IReadOnlyDictionary<BigInteger, EvidenceValue> a, IReadOnlyDictionary<BigInteger, EvidenceValue> b)
    {
        if (a.Count != b.Count) return false;
        // Scalar NaN remains unequal even when both maps or values have the same identity.
        foreach (var (key, before) in a)
            if (!b.TryGetValue(key, out var after) || !EvidenceJson.PythonEquals(before, after)) return false;
        return true;
    }
    private static bool SameInput(ReportHitInput a, ReportHitInput b) => (ReferenceEquals(a.Evidence, b.Evidence) || EvidenceJson.PythonEquals(a.Evidence, b.Evidence))
        && a.BaselineProjectionIsNumeric == b.BaselineProjectionIsNumeric && SameMap(a.Baseline, b.Baseline)
        && SameMap(a.BasicAttributes, b.BasicAttributes) && SameMap(a.Attributes, b.Attributes);
    private ReportHitInput Capture(ReportHitInput hit) => FrozenEvidence.IsFrozenRoot(hit.Evidence)
        && FrozenEvidence.IsFrozenNumbers(hit.Baseline) && FrozenEvidence.IsFrozenNumbers(hit.BasicAttributes)
        && FrozenEvidence.IsFrozenNumbers(hit.Attributes) ? hit : hit with
    {
        Evidence = (EvidenceObject)snapshots.Capture(hit.Evidence), Baseline = FrozenEvidence.CaptureNumbers(hit.Baseline),
        BasicAttributes = FrozenEvidence.CaptureNumbers(hit.BasicAttributes), Attributes = FrozenEvidence.CaptureNumbers(hit.Attributes),
    };

    public void Begin(IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records)
        => BeginCore(hits, windows, records, retainUnchangedPrefix: false);

    internal void BeginOwned(IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records)
        => BeginCore(hits, windows, records, retainUnchangedPrefix: true);

    private void BeginCore(IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> windows,
        IReadOnlyList<EvidenceObject> records, bool retainUnchangedPrefix)
    {
        allocated = reused = 0;
        EvidenceObject[][] next = [ChangedRecords(dependencies?[0].Rows, records), ChangedRecords(dependencies?[1].Rows, windows)];
        DependencyChange[]? changes = null;
        var cutoff = PositiveInfinity;
        string? reason = null;
        if (dependencies is not null && previous.Count > 0)
        {
            if (finalized > 0 && hits.Skip(previous.Count).Any(hit => EffectIdentity.CompareKeys(Time(hit), Time(previous[finalized - 1].Input)) < 0))
                reason = "late damage arrived behind the finalized frontier";
            changes = dependencies.Select((old, group) => CompareDependencies(old, next[group])).ToArray();
            foreach (var change in changes) cutoff = Min(cutoff, change.Cutoff);
            if (reason is null && !(retainUnchangedPrefix && previousOnlyIntegerTimes && ReferenceEquals(cutoff, PositiveInfinity))
                && previous.Take(finalized).Any(row => EffectIdentity.CompareKeys(Time(row.Input), cutoff) >= 0))
                reason = "semantic evidence changed behind the finalized frontier";
        }
        reuseLimit = 0;
        // Captured inputs prove this once when a hit enters the cache. With no
        // dependency cutoff, their integer times cannot reach positive infinity.
        // Public/noninteger inputs retain the original per-hit comparisons.
        var unboundedIntegerPrefix = retainUnchangedPrefix && previousOnlyIntegerTimes && ReferenceEquals(cutoff, PositiveInfinity);
        // A dependency cutoff can cross the finalized frontier without invalidating earlier hits.
        // Revalidate that prefix before rewinding only the affected suffix. Out-of-order damage
        // keeps the conservative reset; public callers retain their existing replay contract.
        if (reason is null || retainUnchangedPrefix && reason == "semantic evidence changed behind the finalized frontier")
            foreach (var row in previous)
            {
                if (reuseLimit >= hits.Count || !unboundedIntegerPrefix && EffectIdentity.CompareKeys(Time(hits[reuseLimit]), cutoff) >= 0) break;
                ComparedHitInputs++;
                // Only our recursively protected input can keep its identity. Scalar NaN maps
                // remain nonreflexive and must retain the original invalidation contract.
                if (!(ReferenceEquals(row.Input, hits[reuseLimit]) && row.InputReflexive)
                    && !SameInput(row.Input, hits[reuseLimit])) break;
                reuseLimit++;
            }
        if (reason is null && reuseLimit < finalized) reason = "finalized hit identity or hit-time context changed";
        if (reason is not null)
        {
            replays++; lastReplayReason = reason;
            if (!retainUnchangedPrefix) { previous = []; reuseLimit = 0; }
            finalized = 0; ink = null; inkLines = []; inkInput = null;
            normalShares.Clear(); inkOutputs.Clear(); inkBindings.Clear();
        }
        dependencies = changes is null ? next.Select(rows => new DependencySnapshot(rows)).ToArray()
            : changes.Select(change => change.Commit()).ToArray();
        current = [];
        currentOnlyIntegerTimes = true;
    }

    public EvidenceObject? Reuse(ReportHitInput hit)
        => ReuseCore(hit, ownsHit: false);

    internal EvidenceObject? ReuseOwned(ReportHitInput hit)
        => ReuseCore(hit, ownsHit: true);

    internal ReportHitInput? ReuseReportOwned(ReportHitInput hit)
    {
        if (ReuseOwned(hit) is not { } evidence) return null;
        var entry = current[^1];
        // Capture preserves identity only for complete recursively immutable inputs.
        // Equal replacement maps and public/mutable inputs keep their current per-call wrapper.
        if (!ReferenceEquals(entry.Input, hit)) return hit with { Evidence = evidence };
        var saved = entry.OwnedReport;
        if (saved is not null && ReferenceEquals(saved.Evidence, evidence))
            return saved;
        return entry.OwnedReport = hit with { Evidence = evidence };
    }

    private EvidenceObject? ReuseCore(ReportHitInput hit, bool ownsHit)
    {
        if (current.Count >= reuseLimit) return null;
        var entry = previous[current.Count];
        current.Add(entry);
        currentOnlyIntegerTimes &= entry.IntegerTime;
        if (ownsHit && FrozenEvidence.IsFrozenRoot(hit.Evidence))
        {
            if (!ReferenceEquals(entry.OwnedInput, hit.Evidence))
            {
                entry.OwnedInput = hit.Evidence;
                entry.OwnedOutput = FrozenEvidence.MergeRoot(hit.Evidence, entry.Output);
            }
            reused++; totalReused++;
            return entry.OwnedOutput!;
        }
        var result = ownsHit ? hit.Evidence : Copy(hit.Evidence);
        foreach (var (key, value) in entry.Output.Fields) ((Dictionary<string, EvidenceValue>)result.Fields)[key] = ownsHit ? value : BuffEvidence.Clone(value);
        reused++; totalReused++;
        return result;
    }

    public void Remember(ReportHitInput input, EvidenceObject output)
    {
        var entry = new Entry(Capture(input), (EvidenceObject)snapshots.Capture(new EvidenceObject(output.Fields.Where(pair => !input.Evidence.Fields.TryGetValue(pair.Key, out var original)
            || !EvidenceJson.PythonEquals(original, pair.Value)).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal))));
        current.Add(entry);
        currentOnlyIntegerTimes &= entry.IntegerTime;
        allocated++; totalAllocated++;
    }

    internal EvidenceObject RememberOwned(ReportHitInput input, EvidenceObject output)
    {
        Remember(input, output);
        // The first result preserves the allocator's exact scalar types. Subsequent reuse retains
        // the existing Python-equality patch contract and acquires a stable merged identity there.
        return (EvidenceObject)snapshots.Capture(output);
    }

    internal void FinishOwned(IReadOnlyList<ReportHitInput> hits)
    {
        HitAccounting.Update(hits);
        if (HitAccounting.FinalizedCount is not { } count) { FinishCore(hits); return; }
        finalized = count; previous = current; previousOnlyIntegerTimes = currentOnlyIntegerTimes;
        pendingLine = finalized < hits.Count ? EffectIdentity.Integer(hits[finalized].Evidence.Get("line_no")) : null;
    }

    public void Finish(IReadOnlyList<ReportHitInput> hits)
    {
        HitAccounting.Clear(); ownedContributions = false;
        FinishCore(hits);
    }

    private void FinishCore(IReadOnlyList<ReportHitInput> hits)
    {
        var latest = hits.Select(Time).Aggregate(NegativeInfinity, (a, b) => EffectIdentity.CompareKeys(a, b) > 0 ? a : b);
        finalized = 0;
        foreach (var hit in hits)
        {
            if (hit.Evidence.Fields.Any(pair => pair.Key.StartsWith("rdps_unresolved_", StringComparison.Ordinal)
                && pair.Key != "rdps_unresolved_static_multiplier_sources" && CatalogValues.Truth(pair.Value))
                || EffectIdentity.CompareKeys(Time(hit), latest) >= 0) break;
            finalized++;
        }
        previous = current;
        previousOnlyIntegerTimes = currentOnlyIntegerTimes;
        pendingLine = finalized < hits.Count ? EffectIdentity.Integer(hits[finalized].Evidence.Get("line_no")) : null;
    }

    public IReadOnlyDictionary<string, double> ContributionTotals(IReadOnlyList<ReportHitInput> hits)
        => ContributionTotalsCore(hits, ownsHits: false);

    internal IReadOnlyDictionary<string, double> ContributionTotalsOwned(IReadOnlyList<ReportHitInput> hits)
        => ContributionTotalsCore(hits, ownsHits: true);

    private IReadOnlyDictionary<string, double> ContributionTotalsCore(IReadOnlyList<ReportHitInput> hits, bool ownsHits)
    {
        var rows = ownsHits ? HitAccounting.Contributions.ToList()
            : hits.Select(hit => (EvidenceObject)FrozenEvidence.Capture(hit.Evidence.Get("rdps_contributions") as EvidenceObject ?? BuffEvidence.Object())).ToList();
        var first = ownsHits && ownedContributions ? Math.Min(HitAccounting.UnchangedPrefix, contributionRows.Count) : 0;
        while (first < Math.Min(rows.Count, contributionRows.Count) && EvidenceJson.PythonEquals(rows[first], contributionRows[first])) first++;
        // Save only the values changed by each hit. Rewinding restores their exact
        // prior bits, never subtracts floating-point credits, and keeps key order.
        RewindContributions(first);
        foreach (var row in rows.Skip(first))
        {
            foreach (var (key, value) in row.Fields)
            {
                var credit = EffectIdentity.Float(value);
                var existed = contributionTotals.TryGetValue(key, out var total);
                var maximum = contributionMaxima.GetValueOrDefault(key);
                contributionUndo.Add(new(key, existed, total, maximum));
                if (!existed) contributionKeys.Add(key);
                contributionTotals[key] = total + credit;
                var rounded = PythonDecimalRounding.Round(credit, 4);
                if (rounded > maximum) contributionMaxima[key] = rounded;
                else contributionMaxima.TryAdd(key, 0);
            }
            contributionEnds.Add(contributionUndo.Count);
        }
        contributionRows = rows;
        ownedContributions = ownsHits;
        return ContributionSnapshot(contributionTotals);
    }

    public InkProvenanceResult ApplyInk(string text, IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> records,
        IReadOnlyDictionary<string, EvidenceObject> roots)
        => ApplyInkText(text, hits, records, roots, ownsHits: false);

    internal InkProvenanceResult ApplyInkOwned(string text, IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> records,
        IReadOnlyDictionary<string, EvidenceObject> roots)
        => ApplyInkText(text, hits, records, roots, ownsHits: true);

    private InkProvenanceResult ApplyInkText(string text, IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> records,
        IReadOnlyDictionary<string, EvidenceObject> roots, bool ownsHits)
    {
        var relevant = PythonTextLines.Split(text).Select((line, index) => new InkTraceLine(index + 1, line))
            .Where(line => new[] { " HP_V2 ", " INK_RELEASE ", " BB_MODIFY_DYNAMIC ", " BB_SIMPLE_CALC ", " ACTOR_MAP ", " SKILL_CAST_START " }
                .Any(tag => line.Text.Contains(tag, StringComparison.Ordinal))).ToArray();
        var prefixChanged = inkInput is not null || relevant.Length < inkLines.Length || !relevant.Take(inkLines.Length).SequenceEqual(inkLines);
        var result = ApplyInkCore(hits, records, roots, prefixChanged, inkLines.Length,
            skip => relevant.Skip(skip).Select(InkObservation.FromLegacy), ownsHits);
        inkLines = relevant; inkInput = null;
        return result;
    }

    public InkProvenanceResult ApplyInk(InkObservationInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, IReadOnlyDictionary<string, EvidenceObject> roots)
        => ApplyInkInput(input, hits, records, roots, ownsHits: false);

    internal InkProvenanceResult ApplyInkOwned(InkObservationInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, IReadOnlyDictionary<string, EvidenceObject> roots)
        => ApplyInkInput(input, hits, records, roots, ownsHits: true);

    private InkProvenanceResult ApplyInkInput(InkObservationInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, IReadOnlyDictionary<string, EvidenceObject> roots, bool ownsHits)
    {
        var result = ApplyInkCore(hits, records, roots, inkInput is null || !input.Continues(inkInput),
            inkInput?.Count ?? 0, input.After, ownsHits);
        inkInput = input; inkLines = [];
        return result;
    }

    private InkProvenanceResult ApplyInkCore(IReadOnlyList<ReportHitInput> hits, IReadOnlyList<EvidenceObject> records,
        IReadOnlyDictionary<string, EvidenceObject> roots, bool prefixChanged, int previousCount,
        Func<int, IEnumerable<InkObservation>> observations, bool ownsHits)
    {
        // Until ink evidence appears, immutable summary hits need no separate source ledger.
        // The first relevant record/explosion still starts from observation zero below.
        if (ownsHits && ink is null
            && !records.Any(row => row.Get("event_key") is EvidenceText { Value: InkProvenanceStream.Buff })
            && hits.All(hit => FrozenEvidence.IsFrozenRoot(hit.Evidence)
                && hit.Evidence.Get("skill_key") is not EvidenceText { Value: InkProvenanceStream.Explosion }))
            return new(hits.Select(hit => hit.Evidence).ToArray(), BuffEvidence.Object());
        Dictionary<BigInteger, EvidenceObject> normal = [];
        foreach (var hit in hits.Where(hit => hit.Evidence.Get("skill_key") is not EvidenceText { Value: InkProvenanceStream.Explosion }))
            normal[EffectIdentity.Integer(hit.Evidence.Get("line_no"))] = (EvidenceObject)FrozenEvidence.Capture(hit.Evidence.Get("rdps_contributions") as EvidenceObject ?? BuffEvidence.Object());
        var bindingFields = new[] { "packet_creation_contexts", "source_actor_id", "source_character_key", "target_actor_id", "rdps_live_identity_conflict", "end_line_no" };
        Dictionary<EffectSignature, EvidenceObject> bindings = [];
        foreach (var row in records.Where(row => row.Get("event_key") is EvidenceText { Value: InkProvenanceStream.Buff }))
            bindings[Identity(row)] = new(bindingFields.ToDictionary(key => key, row.Get, StringComparer.Ordinal));
        var changed = normalShares.Any(pair => !normal.TryGetValue(pair.Key, out var value) || !EvidenceJson.PythonEquals(pair.Value, value));
        var rebound = inkBindings.Any(pair => !bindings.TryGetValue(pair.Key, out var value) || !EvidenceJson.PythonEquals(pair.Value, value));
        var reset = ink is null || changed || rebound || prefixChanged;
        if (reset)
        {
            if (ink is not null)
            {
                inkReplays++;
                lastInkReplayReason = changed ? "original contribution changed" : rebound ? "ink binding changed" : "ink input prefix changed";
            }
            ink = new(roots); inkOutputs = [];
        }
        var evidence = hits.Select(hit => hit.Evidence).ToArray();
        var advanced = ownsHits ? ink!.AdvanceOwnedObservations(observations(reset ? 0 : previousCount), evidence, records)
            : ink!.AdvanceObservations(observations(reset ? 0 : previousCount), evidence, records);
        normalShares = normal;
        inkBindings = bindings.ToDictionary(pair => pair.Key, pair => Copy(pair.Value));
        var owned = advanced.Hits.ToArray();
        for (var index = 0; index < owned.Length; index++)
        {
            var hit = owned[index];
            if (hit.Get("skill_key") is not EvidenceText { Value: InkProvenanceStream.Explosion }) continue;
            var line = EffectIdentity.Integer(hit.Get("line_no"));
            if (hit.Get("_ink_allocation") is not EvidenceNull)
                inkOutputs[line] = (EvidenceObject)FrozenEvidence.Capture(new EvidenceObject(new[] { "_ink_allocation", "ink_provenance", "rdps_contributions", "rdps_unresolved_effect_conditions" }
                    .Where(hit.Fields.ContainsKey).ToDictionary(key => key, hit.Get, StringComparer.Ordinal)));
            else if (inkOutputs.TryGetValue(line, out var saved))
                foreach (var (key, value) in saved.Fields) ((Dictionary<string, EvidenceValue>)hit.Fields)[key] = ownsHits ? value : BuffEvidence.Clone(value);
        }
        return new(owned, CatalogValues.Truth(advanced.Summary.Get("explosions")) ? advanced.Summary : BuffEvidence.Object());
    }
}
