using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;

namespace EndfieldLogs.Core.Reporting;

public sealed record BattleReportInput(ReportCalculationInput Calculation, ReportTimingInput Timing,
    ReportSourceInput Sources, ReportParticipantInput Participants, ReportMetadataInput? Metadata = null)
{
    public static BattleReportInput Capture(BattleIngestionStream stream, DateOnly? referenceDate = null) => new(ReportCalculationInput.Capture(stream),
        ReportTimingInput.Capture(stream), ReportSourceInput.Capture(stream), ReportParticipantInput.Capture(stream),
        ReportMetadataInput.Capture(stream, referenceDate ?? DateOnly.FromDateTime(DateTime.Now)));

    internal static BattleReportInput CaptureLive(BattleIngestionStream stream, LiveHitProjectionCache hits, LiveBuffProjectionCache buffs,
        DateOnly referenceDate, bool summary = false) =>
        new(ReportCalculationInput.CaptureLive(stream, hits, buffs, immutableHits: summary), ReportTimingInput.Capture(stream),
            summary ? ReportSourceInput.CaptureSummary(stream) : ReportSourceInput.Capture(stream),
            ReportParticipantInput.Capture(stream), ReportMetadataInput.Capture(stream, referenceDate));
}

public sealed record BattleReportAnalysisResult(ReportLifecycleResult Lifecycle, ReportSourceInput Sources,
    ReportCalculationResult? Calculation, ReportParticipantProjection Participants, ReportTimelineProjection? Timeline,
    ReportMetadataInput? Metadata = null);

/// <summary>Owned snapshot entry for Runtime: prepare observations, select scope, calculate and project participants.</summary>
public sealed class BattleReportAnalysis(ReportLifecycle lifecycle, ReportCalculation calculation, ReportParticipants participants,
    ReportTimeline? timeline = null, BattleLoadoutResolver? loadouts = null, ReportExport? export = null)
{
    public static BattleReportAnalysis Load(ResourceFiles files, TimeZoneInfo? timeZone = null)
    {
        var identities = new SkillResourceCatalog(files).CreateIdentityCatalog();
        DisplayNameCatalog names = new(files, new(files), identities);
        var loadouts = BattleLoadoutResolver.Load(files);
        return new(ReportLifecycle.Load(files), ReportCalculation.Load(files), new(names.Character), ReportTimeline.Load(files), loadouts,
            new(loadouts, names.Enemy, new ContractTagCatalog(files).Payload, timeZone));
    }

    public BattleReportAnalysisResult Analyze(BattleReportInput input, string traceText, bool includeDebug = false,
        CancellationToken cancellationToken = default, LiveAllocationCache? cache = null, bool summary = false)
        => AnalyzeCore(input, traceText, includeDebug, cancellationToken, cache, summary, ownsInput: false);

    private BattleReportAnalysisResult AnalyzeCore(BattleReportInput input, string traceText, bool includeDebug,
        CancellationToken cancellationToken, LiveAllocationCache? cache, bool summary, bool ownsInput)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var source = input.Calculation;
        if (loadouts is not null)
        {
            var repaired = loadouts.Repair(source.Baseline.Loadouts.Groups, source.Baseline.Loadouts.Fallback);
            source = source with { Baseline = source.Baseline with { Loadouts = new(repaired.Groups, repaired.Fallback) } };
        }
        var sources = summary ? input.Sources with { PoiseEvents = [], RefreshEvents = [], AtbEvents = [] } : input.Sources;
        var prepared = ownsInput ? ReportSourcePreparation.PrepareOwned(source, sources, preserveHits: summary && cache is not null,
            summaryCache: summary ? cache?.SourcePreparation : null)
            : ReportSourcePreparation.Prepare(source, sources);
        var selected = lifecycle.Select(prepared.Calculation, input.Timing, traceText);
        var counters = ownsInput && summary && cache is not null
            ? participants.PrepareOwned(input.Participants, selected.Input.Baseline.Hits, selected.Input.Records, selected.RebuildTotals, cache.ParticipantCounters)
            : participants.Prepare(input.Participants, selected.Input.Baseline.Hits, selected.Input.Records, selected.RebuildTotals);
        var computed = (ownsInput ? calculation.CalculateOwned(selected, traceText, cancellationToken, cache, summary)
            : calculation.Calculate(selected, traceText, includeDebug: false, cancellationToken, cache, summary)).Calculation;
        var projected = computed is null ? new ReportParticipantProjection([], [])
            : participants.Project(counters, computed.Baseline.Loadouts, computed.Totals, selected.DurationMs);
        cancellationToken.ThrowIfCancellationRequested();
        var display = computed is null || summary ? null : ownsInput
            ? timeline?.BuildOwned(computed.Hits, prepared.Sources, selected, projected.Participants, counters.Roster, computed.Windows, computed.Records)
            : timeline?.Build(computed.Hits, prepared.Sources, selected, projected.Participants, counters.Roster, computed.Windows, computed.Records);
        if (computed is not null && display?.Windows is { } displayedWindows) computed = computed with { Windows = displayedWindows };
        if (computed is not null && includeDebug) computed = calculation.WithDebug(computed);
        return new(selected, prepared.Sources, computed, projected, display, input.Metadata);
    }

    public EndfieldLogs.Core.Compatibility.EvidenceObject? BuildReport(BattleReportInput input, string traceText, string? fileName = null,
        bool includeDebug = false, bool allowEmpty = false, CancellationToken cancellationToken = default)
    {
        if (export is null) throw new InvalidOperationException("The report exporter must be configured");
        var result = Analyze(input, traceText, includeDebug, cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        return export.Build(result, traceText, fileName, includeDebug, allowEmpty);
    }

    public EndfieldLogs.Core.Compatibility.EvidenceObject? BuildSnapshot(BattleReportInput input, string traceText,
        bool summary = false, CancellationToken cancellationToken = default, LiveAllocationCache? cache = null)
        => BuildSnapshotCore(input, traceText, summary, cancellationToken, cache, ownsInput: false);

    /// <summary>Capture private history input and detach once after report and display projection.</summary>
    public EndfieldLogs.Core.Compatibility.EvidenceObject? BuildHistorySnapshot(BattleIngestionStream stream,
        DateOnly referenceDate, string traceText, string? fileName = null, BigInteger? lastHitHintMs = null,
        CancellationToken cancellationToken = default)
    {
        if (export is null) throw new InvalidOperationException("The report exporter must be configured");
        cancellationToken.ThrowIfCancellationRequested();
        var input = BattleReportInput.Capture(stream, referenceDate);
        if (lastHitHintMs is not null) input = input with { Timing = ReportTimingInput.Capture(stream, lastHitHintMs: lastHitHintMs) };
        var result = AnalyzeCore(input, traceText, false, cancellationToken, cache: null, summary: false, ownsInput: true);
        var report = export.BuildOwned(result, traceText, fileName);
        cancellationToken.ThrowIfCancellationRequested();
        // Transfer private report containers, detach protected descendants and convert
        // wide/nonfinite numbers. Neither stream state nor resource objects escape.
        return report is null ? null : (EndfieldLogs.Core.Compatibility.EvidenceObject)SnapshotQuality.JsonEvidenceOwned(
            Realtime.LiveReportProjection.OverlayOwned(report));
    }

    // The live engine transfers its fresh capture and discards it after this call. Public entries retain isolation.
    internal EndfieldLogs.Core.Compatibility.EvidenceObject? BuildOwnedSnapshot(BattleReportInput input, string traceText,
        bool summary, CancellationToken cancellationToken, LiveAllocationCache cache)
        => BuildSnapshotCore(input, traceText, summary, cancellationToken, cache, ownsInput: true);

    private EndfieldLogs.Core.Compatibility.EvidenceObject? BuildSnapshotCore(BattleReportInput input, string traceText,
        bool summary, CancellationToken cancellationToken, LiveAllocationCache? cache, bool ownsInput)
    {
        if (export is null) throw new InvalidOperationException("The report exporter must be configured");
        var result = AnalyzeCore(input, traceText, false, cancellationToken, cache, summary, ownsInput);
        if (summary)
        {
            var compact = export.BuildSummary(result, cache?.Maxima ?? Realtime.LiveReportProjection.MaximaFromHits(result.Calculation?.Hits ?? []));
            cancellationToken.ThrowIfCancellationRequested();
            return compact;
        }
        var report = export.Build(result, traceText, "live-overlay.log", allowEmpty: true);
        cancellationToken.ThrowIfCancellationRequested();
        return report is null ? null : Realtime.LiveReportProjection.Overlay(report);
    }
}
