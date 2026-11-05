using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Allocation;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Capture on the ingestion owner; report workers prepare sources and scope their private copy.</summary>
public sealed record ReportCalculationInput(ReportBaselineInput Baseline, IReadOnlyList<EvidenceObject> Records,
    IReadOnlyList<EvidenceObject> UnresolvedHits, IReadOnlyList<EvidenceObject> UnresolvedBuffActions)
{
    public InkObservationInput? Ink { get; init; }

    public static ReportCalculationInput Capture(BattleIngestionStream stream) => Capture(stream, ReportBaselineInput.Capture(stream));

    internal static ReportCalculationInput CaptureLive(BattleIngestionStream stream, LiveHitProjectionCache hits, LiveBuffProjectionCache buffs,
        bool immutableHits = false) =>
        Capture(stream, ReportBaselineInput.Capture(stream, immutableHits ? hits.CaptureImmutable : hits.Capture), buffs.Capture(stream.Buffs));

    private static ReportCalculationInput Capture(BattleIngestionStream stream, ReportBaselineInput baseline,
        IReadOnlyList<EvidenceObject>? records = null) => new(baseline,
        records ?? stream.Buffs.Records.Select(BuffReportEvidence.Project).ToArray(), stream.Hits.Unresolved.Select(row => BuffEvidence.Object(
            ("line_no", new EvidenceInteger(row.LineNumber)), ("ts_ms", new EvidenceInteger(row.TimestampMs)),
            ("source_actor", BuffEvidence.Text(row.SourceActor)), ("attacker_actor", BuffEvidence.Text(row.AttackerActor)),
            ("target_actor", BuffEvidence.Text(row.TargetActor)), ("raw_skill_key", BuffEvidence.Text(row.RawSkill)),
            ("packet_hit_value", BuffEvidence.Text(row.PacketHit)), ("reason", new EvidenceText(row.Reason)))).ToArray(),
        stream.Buffs.UnresolvedActions.Select(row => (EvidenceObject)BuffEvidence.Clone(row.Evidence)).ToArray()) { Ink = stream.Ink.Capture() };
}
