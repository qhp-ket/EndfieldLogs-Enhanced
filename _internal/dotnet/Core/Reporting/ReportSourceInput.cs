using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Owned non-hit evidence captured with the calculation input on the ingestion owner.</summary>
public sealed record ReportSourceInput(IReadOnlyList<EvidenceObject> Casts, IReadOnlyList<EvidenceObject> DynamicEvents,
    IReadOnlyList<EvidenceObject> RefreshEvents, IReadOnlyList<EvidenceObject> PoiseEvents,
    IReadOnlyDictionary<string, long> ModifierLastSeen, IReadOnlyList<EvidenceObject> AtbEvents)
{
    public static ReportSourceInput Capture(BattleIngestionStream stream)
        => CaptureCore(stream, includeDisplay: true);

    // Live summaries never consume these display histories. Keep them in ingestion for an explicit full report.
    internal static ReportSourceInput CaptureSummary(BattleIngestionStream stream)
        => CaptureCore(stream, includeDisplay: false);

    private static ReportSourceInput CaptureCore(BattleIngestionStream stream, bool includeDisplay)
    {
        static EvidenceValue Number(double? value) => value is { } number ? new EvidenceReal(number) : EvidenceNull.Value;
        EvidenceObject Cast(SkillCastObservation cast)
        {
            var row = BuffEvidence.Object(
                ("ts_ms", new EvidenceInteger(cast.TimestampMs)), ("line_no", new EvidenceInteger(cast.LineNumber)),
                ("skill", new EvidenceText(cast.Skill)), ("owner", BuffEvidence.Text(cast.Owner)),
                ("owner_id", BuffEvidence.Text(cast.OwnerId)), ("skill_inst_id", BuffEvidence.Text(cast.SkillInstanceId)),
                ("skill_source", BuffEvidence.Text(cast.SkillSource)), ("source_character_key", BuffEvidence.Text(cast.CharacterKey)),
                ("end_ts_ms", BuffEvidence.Number(cast.EndTimestampMs)));
            if (cast.EndLineNumber is { } endLine) ((Dictionary<string, EvidenceValue>)row.Fields)["end_line_no"] = new EvidenceInteger(endLine);
            return row;
        }
        return new(stream.Skills.Casts.Select(Cast).ToArray(),
            stream.Buffs.DynamicEvents.Select(row => (EvidenceObject)BuffEvidence.Hook(row.Evidence)).ToArray(),
            includeDisplay ? stream.Buffs.AttributeRefreshEvents.Select(row => (EvidenceObject)BuffEvidence.Hook(row.Evidence)).ToArray() : [],
            includeDisplay ? stream.Packets.PoiseDamage.Select(row => BuffEvidence.Object(
                ("ts_ms", new EvidenceInteger(row.TimestampMs)), ("line_no", new EvidenceInteger(row.LineNumber)),
                ("type", new EvidenceText("PoiseDamage")), ("value", Number(row.Value)), ("current_value", Number(row.CurrentValue)),
                ("source", new EvidenceText(row.Source)), ("source_int", BuffEvidence.Number(row.SourceInteger)),
                ("orig_source", BuffEvidence.Text(row.OriginalSource)), ("orig_source_int", BuffEvidence.Number(row.OriginalSourceInteger)))).ToArray() : [],
            new Dictionary<string, long>(stream.Packets.ModifierLastSeenByUid, StringComparer.Ordinal),
            includeDisplay ? stream.Skills.AtbObservations.Select(row => BuffEvidence.Object(
                ("ts_ms", new EvidenceInteger(row.TimestampMs)), ("line_no", new EvidenceInteger(row.LineNumber)),
                ("character_key", BuffEvidence.Text(row.CharacterKey)), ("owner_actor_id", BuffEvidence.Text(row.OwnerActorId)),
                ("value", Number(row.Value)), ("delta", Number(row.Delta)), ("recovery_speed", Number(row.RecoverySpeed)),
                ("client_tick_ms", Number(row.ClientTickMs)), ("reason", BuffEvidence.Text(row.Reason)),
                ("source", BuffEvidence.Text(row.Source)), ("original_source", BuffEvidence.Text(row.OriginalSource)))).ToArray() : []);
    }
}
