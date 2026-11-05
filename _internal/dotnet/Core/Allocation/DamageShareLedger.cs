using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Realtime;

namespace EndfieldLogs.Core.Allocation;

public sealed record DamageShareResult(IReadOnlyList<ReportHitInput> Hits, IReadOnlyList<EvidenceObject> Windows,
    IReadOnlyDictionary<string, double> Totals, EvidenceObject InkSummary);

/// <summary>Ordered report allocation. Incremental cache ownership is supplied by the live report layer separately.</summary>
public sealed class DamageShareLedger(HitAllocator allocator, IReadOnlyDictionary<string, EvidenceObject> roots)
{
    public static DamageShareLedger Load(ResourceFiles files) => new(HitAllocator.Load(files), new BuffRootCatalog(files).Roots);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    public DamageShareResult Compute(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> windows,
        IReadOnlyList<EvidenceObject>? records = null, string? traceText = null, LiveAllocationCache? cache = null,
        InkObservationInput? inkInput = null)
        => ComputeCore(source, windows, records, traceText, cache, inkInput, ownsHits: false);

    internal DamageShareResult ComputeOwned(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> windows,
        IReadOnlyList<EvidenceObject> records, string? traceText, LiveAllocationCache? cache, InkObservationInput? inkInput, bool summary = false)
        => ComputeCore(source, windows, records, traceText, cache, inkInput, ownsHits: true, retainImmutable: summary && cache is not null);

    private DamageShareResult ComputeCore(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> windows,
        IReadOnlyList<EvidenceObject>? records, string? traceText, LiveAllocationCache? cache, InkObservationInput? inkInput, bool ownsHits, bool retainImmutable = false)
    {
        if (retainImmutable) cache!.BeginOwned(source, windows, records ?? []);
        else cache?.Begin(source, windows, records ?? []);
        AllocationConditionIndex? conditions = null;
        AllocationWindowIndex? windowIndex = null;
        Dictionary<string, IReadOnlyList<EvidenceObject>>? byUid = null, byActor = null;
        void PrepareAllocation()
        {
            conditions ??= new AllocationConditionIndex(records);
            windowIndex ??= new AllocationWindowIndex(windows);
            byUid ??= (records ?? []).GroupBy(record => Text(record.Get("uid")), StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => (IReadOnlyList<EvidenceObject>)group.ToArray(), StringComparer.Ordinal);
            byActor ??= (records ?? []).GroupBy(record => Text(record.Get("target_actor_id")), StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => (IReadOnlyList<EvidenceObject>)group.ToArray(), StringComparer.Ordinal);
        }
        if (!retainImmutable) PrepareAllocation();
        IReadOnlyList<EvidenceObject> currentWindows = windows.Select(value => (EvidenceObject)(ownsHits
            ? FrozenEvidence.CopyOwned(value) : BuffEvidence.Clone(value))).ToArray();
        IReadOnlyList<int>? resetWindows = null;
        List<ReportHitInput> hits = [];
        foreach (var input in source)
        {
            if (retainImmutable)
            {
                if (cache!.ReuseReportOwned(input) is { } reusedReport)
                {
                    hits.Add(reusedReport);
                    continue;
                }
            }
            else if ((ownsHits ? cache?.ReuseOwned(input) : cache?.Reuse(input)) is { } reused)
            {
                hits.Add(input with { Evidence = reused });
                continue;
            }
            var stamp = EffectIdentity.Integer(CatalogValues.Or(input.Evidence.Get("ts_ms"), new EvidenceInteger(0)));
            EvidenceObject hit;
            EvidenceObject shares;
            if ((inkInput is not null || traceText is not null) && input.Evidence.Get("skill_key") is EvidenceText { Value: InkProvenanceStream.Explosion })
            {
                hit = ownsHits && cache is null ? input.Evidence : (EvidenceObject)BuffEvidence.Clone(input.Evidence);
                shares = BuffEvidence.Object((CatalogValues.Text(hit.Fields["character_key"]), new EvidenceReal(EffectIdentity.Float(hit.Fields["hit_value"]))));
            }
            else
            {
                // Entirely reused reports and recorded ink need none of these historical indexes.
                PrepareAllocation();
                var targets = new[] { Text(input.Evidence.Get("character_key")), Text(input.Evidence.Get("target_enemy_key")) }.Distinct(StringComparer.Ordinal);
                var byTarget = targets.ToDictionary(target => target, target => conditions!.At(target, stamp), StringComparer.Ordinal);
                var allocation = allocator.Allocate(new(input, currentWindows, records, byTarget, byUid, byActor, WindowIndices: windowIndex!.At(stamp))
                    { WindowResetIndices = resetWindows, OwnsWindowBuffer = true, ConsumesHit = ownsHits && cache is null });
                hit = allocation.Hit; currentWindows = allocation.Windows;
                // Cache hits and recorded ink bypass evaluation and leave the previous dirty set intact.
                resetWindows = allocation.EvaluatedWindowIndices ?? resetWindows;
                shares = (EvidenceObject)BuffEvidence.Clone(CatalogValues.Or(allocation.Allocation.Get("contributions_map"), BuffEvidence.Object()));
            }
            ((Dictionary<string, EvidenceValue>)hit.Fields)["rdps_contributions"] = shares;
            if (retainImmutable) hit = cache!.RememberOwned(input, hit);
            else cache?.Remember(input, hit);
            hits.Add(input with { Evidence = hit });
        }
        var inkSummary = BuffEvidence.Object();
        if (inkInput is not null || traceText is not null)
        {
            var ink = inkInput is not null
                ? cache is null ? InkProvenanceStream.Apply(inkInput, hits.Select(hit => hit.Evidence).ToArray(), records ?? [], roots)
                    : ownsHits ? cache.ApplyInkOwned(inkInput, hits, records ?? [], roots) : cache.ApplyInk(inkInput, hits, records ?? [], roots)
                : cache is null ? InkProvenanceStream.Apply(traceText!, hits.Select(hit => hit.Evidence).ToArray(), records ?? [], roots)
                    : ownsHits ? cache.ApplyInkOwned(traceText!, hits, records ?? [], roots) : cache.ApplyInk(traceText!, hits, records ?? [], roots);
            inkSummary = ink.Summary;
            for (var index = 0; index < hits.Count; index++)
                if (!retainImmutable || !ReferenceEquals(hits[index].Evidence, ink.Hits[index]))
                    hits[index] = hits[index] with { Evidence = ink.Hits[index] };
        }
        if (cache is not null)
        {
            if (retainImmutable)
            {
                // Ink can revise explosion roots; only the finalized output enters shared accounting.
                for (var index = 0; index < hits.Count; index++)
                    if (!FrozenEvidence.IsFrozenRoot(hits[index].Evidence))
                        hits[index] = hits[index] with { Evidence = (EvidenceObject)FrozenEvidence.Capture(hits[index].Evidence) };
                cache.FinishOwned(hits);
                return new(hits, currentWindows, cache.ContributionTotalsOwned(hits), inkSummary);
            }
            cache.Finish(hits);
            return new(hits, currentWindows, cache.ContributionTotals(hits), inkSummary);
        }
        Dictionary<string, double> totals = new(StringComparer.Ordinal);
        foreach (var input in hits)
            if (input.Evidence.Get("rdps_contributions") is EvidenceObject contributions)
                foreach (var (character, credit) in contributions.Fields) totals[character] = totals.GetValueOrDefault(character) + EffectIdentity.Float(credit);
        return new(hits, currentWindows, totals, inkSummary);
    }
}
