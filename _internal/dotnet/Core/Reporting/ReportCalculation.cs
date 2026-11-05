using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;

namespace EndfieldLogs.Core.Reporting;

public sealed record ReportCalculationResult(StaticBaselineResult Baseline, IReadOnlyList<ReportHitInput> Hits,
    IReadOnlyList<EvidenceObject> Records, IReadOnlyList<EvidenceObject> Windows, IReadOnlyDictionary<string, double> Totals,
    EvidenceObject DamageBasis, EvidenceObject Preflight, IReadOnlyList<EvidenceObject> DebugHits,
    IReadOnlyList<EvidenceObject>? BuffEvents = null);

public sealed record TimedReportCalculationResult(ReportLifecycleResult Lifecycle, ReportCalculationResult? Calculation);

/// <summary>The report calculation sequence. Lifecycle selection and presentation are separate owners.</summary>
public sealed class ReportCalculation(StaticBaselineBuilder baseline, EffectWindowBuilder windows,
    DamageShareLedger ledger, AllocationPreflight preflight, DebugHitDetails details, ReportCriticalEvidence? critical = null,
    ReportBuffEvents? buffEvents = null)
{
    public static ReportCalculation Load(ResourceFiles files) => new(StaticBaselineBuilder.Load(files), EffectWindowBuilder.Load(files),
        DamageShareLedger.Load(files), AllocationPreflight.Load(files), DebugHitDetails.Load(files), ReportCriticalEvidence.Load(files),
        ReportBuffEvents.Load(files));

    public TimedReportCalculationResult Calculate(ReportLifecycleResult selection, string? traceText = null,
        bool includeDebug = false, CancellationToken cancellationToken = default, LiveAllocationCache? cache = null, bool summary = false)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return new(selection, selection.Window is not { } window ? null
            : Calculate(selection.Input, window.StartMs, window.EndMs, traceText, includeDebug, cancellationToken, cache, summary));
    }

    internal TimedReportCalculationResult CalculateOwned(ReportLifecycleResult selection, string traceText,
        CancellationToken cancellationToken, LiveAllocationCache? cache, bool summary) => new(selection,
        selection.Window is not { } window ? null : CalculateCore(selection.Input, window.StartMs, window.EndMs,
            traceText, false, cancellationToken, cache, summary, ownsHits: true));

    public ReportCalculationResult Calculate(ReportCalculationInput input, BigInteger startMs, BigInteger endMs,
        string? traceText = null, bool includeDebug = false, CancellationToken cancellationToken = default, LiveAllocationCache? cache = null, bool summary = false)
        => CalculateCore(input, startMs, endMs, traceText, includeDebug, cancellationToken, cache, summary, ownsHits: false);

    private ReportCalculationResult CalculateCore(ReportCalculationInput input, BigInteger startMs, BigInteger endMs,
        string? traceText, bool includeDebug, CancellationToken cancellationToken, LiveAllocationCache? cache, bool summary, bool ownsHits)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var prepared = ownsHits ? baseline.PrepareOwned(input.Baseline, startMs, summary ? cache?.HitPreparation : null)
            : baseline.Prepare(input.Baseline, startMs);
        cancellationToken.ThrowIfCancellationRequested();
        var hitEvidence = prepared.Hits.Select(hit => hit.Evidence).ToArray();
        var assembled = ownsHits ? windows.BuildOwned(input.Records, hitEvidence, endMs,
            prepared.StaticArtsStrength, prepared.ActiveSuits, prepared.ActiveWeapons, cache?.RecordAnalyses, readOnlyRecords: summary,
            retainAnalyses: !summary && buffEvents is not null)
            : windows.Build(input.Records, hitEvidence, endMs,
                prepared.StaticArtsStrength, prepared.ActiveSuits, prepared.ActiveWeapons, cache?.RecordAnalyses);
        var hits = prepared.Hits.Select((hit, index) => ownsHits && summary && ReferenceEquals(hit.Evidence, assembled.Hits[index])
            ? hit : hit with { Evidence = assembled.Hits[index] }).ToArray();
        var described = summary ? null : ownsHits ? buffEvents?.BuildOwned(assembled.Records, assembled.Windows, startMs, endMs, assembled.Analyses)
            : buffEvents?.Build(assembled.Records, assembled.Windows, startMs, endMs);
        var records = described?.Records ?? assembled.Records;
        cancellationToken.ThrowIfCancellationRequested();
        var allocated = ownsHits ? ledger.ComputeOwned(hits, assembled.Windows, records, traceText, cache, input.Ink, summary)
            : ledger.Compute(hits, assembled.Windows, records, traceText, cache, input.Ink);
        cancellationToken.ThrowIfCancellationRequested();
        var explained = summary || critical is null ? new ReportCriticalResult(allocated.Hits, allocated.Windows)
            : ownsHits ? critical.AttachOwned(allocated.Hits, records, allocated.Windows) : critical.Attach(allocated.Hits, records, allocated.Windows);
        var readiness = ownsHits && summary ? preflight.BuildSummaryOwned(records, explained.Windows, startMs, endMs,
            input.UnresolvedHits, input.UnresolvedBuffActions, cache?.PreflightAnalyses,
            cache?.HitAccounting.BlockerCount ?? explained.Hits.Sum(hit => AllocationPreflight.HitBlockerCount(hit.Evidence)))
            : ownsHits ? preflight.BuildOwned(records, explained.Windows, startMs, endMs,
            explained.Hits.Select(hit => hit.Evidence).ToArray(), input.UnresolvedHits, input.UnresolvedBuffActions, cache?.PreflightAnalyses,
            readOnlyRecords: false)
            : preflight.Build(records, explained.Windows, startMs, endMs,
            explained.Hits.Select(hit => hit.Evidence).ToArray(), input.UnresolvedHits, input.UnresolvedBuffActions, cache?.PreflightAnalyses);
        EvidenceObject basis;
        if (ownsHits && summary && cache is not null) basis = cache.HitAccounting.BuildBasis(allocated.Totals);
        else
        {
            var total = PythonNumericSum.Sum(explained.Hits.Select(hit => hit.Evidence.Fields["hit_value"]));
            basis = DamageBasis.Build(explained.Hits.Select(hit => hit.Evidence).ToArray(),
                allocated.Totals.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value), StringComparer.Ordinal), EffectIdentity.Integer(total));
        }
        var fields = (Dictionary<string, EvidenceValue>)basis.Fields;
        if (allocated.InkSummary.Fields.Count > 0) fields["ink_provenance"] = allocated.InkSummary;
        var ready = CatalogValues.Truth(readiness.Summary.Get("ok"));
        fields["rdps_preflight_ok"] = new EvidenceBoolean(ready);
        fields["rdps_strict_ok"] = new EvidenceBoolean(ready && CatalogValues.Truth(basis.Get("rdps_conservation_ok")));
        fields["preflight_blocker_count"] = readiness.Summary.Get("blocker_count");
        fields["unresolved_damage_actor_count"] = new EvidenceInteger(input.UnresolvedHits.Count(row =>
        {
            var time = EffectIdentity.Integer(CatalogValues.Or(row.Get("ts_ms"), new EvidenceInteger(0)));
            return time >= startMs && time <= endMs;
        }));
        cancellationToken.ThrowIfCancellationRequested();
        var grouped = summary ? explained.Hits : ownsHits ? ReportTimeline.AssignGroupsOwned(explained.Hits) : ReportTimeline.AssignGroups(explained.Hits);
        var result = new ReportCalculationResult(prepared, grouped, readiness.Records, explained.Windows, allocated.Totals, basis,
            readiness.Summary, [], described?.Events ?? []);
        return includeDebug ? WithDebug(result) : result;
    }

    public ReportCalculationResult WithDebug(ReportCalculationResult report)
    {
        var debug = details.Build(report.Hits, report.Windows, report.Records);
        return report with { DebugHits = debug.Hits, Windows = debug.Windows };
    }
}
