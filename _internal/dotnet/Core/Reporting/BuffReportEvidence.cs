using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Owned report boundary for typed ingestion records; preserves optional fields and packet hook semantics.</summary>
public static class BuffReportEvidence
{
    private static EvidenceValue Text(string? value)=>BuffEvidence.Text(value);
    private static EvidenceArray Strings(IEnumerable<string> items)=>new(items.Select(Text).ToArray());
    private static EvidenceArray Rows(IEnumerable<BuffObservation> items)=>new(items.Select(item=>BuffEvidence.Hook(item.Evidence)).ToArray());

    public static EvidenceObject Project(BuffRecord row)
    {
        Dictionary<string,EvidenceValue> fields=new(StringComparer.Ordinal)
        {
            ["uid"]=Text(row.Uid),["uid_observation_only"]=new EvidenceBoolean(row.ObservationOnly),
            ["line_no"]=new EvidenceInteger(row.LineNumber),["ts_ms"]=new EvidenceInteger(row.TimestampMs),
            ["source_character_key"]=Text(row.SourceCharacterKey),["source_character_name"]=Text(row.SourceCharacterName),
            ["source_weapon_template"]=Text(row.SourceWeaponTemplate),["source_skill_key"]=Text(row.SourceSkillKey),["source_skill_family_key"]=Text(row.SourceSkillFamilyKey),
            ["raw_source_character_key"]=Text(row.RawSourceCharacterKey),["raw_source_character_name"]=Text(row.RawSourceCharacterName),["raw_source"]=Text(row.RawSource),
            ["target_character_key"]=Text(row.TargetCharacterKey),["target_character_name"]=Text(row.TargetCharacterName),
            ["target_enemy_key"]=Text(row.TargetEnemyKey),["target_enemy_name"]=Text(row.TargetEnemyName),["owner_raw"]=Text(row.OwnerRaw),
            ["target_actor_id"]=Text(row.TargetActorId),["source_actor_id"]=Text(row.SourceActorId),["event_key"]=Text(row.EventKey),["raw_event_key"]=Text(row.RawEventKey),
            ["packet_mapping"]=row.PacketMapping is { } mapping ? BuffEvidence.Clone(mapping) : EvidenceNull.Value,
            ["packet_mapping_rejected"]=new EvidenceBoolean(row.PacketMappingRejected),["raw_duration_ms"]=BuffEvidence.Number(row.RawDurationMs),
            ["end_ts_ms"]=BuffEvidence.Number(row.EndTimestampMs),["bb_keys"]=Strings(row.BlackboardKeys),["bb_values"]=BuffEvidence.Blackboard(row.BlackboardValues),
            ["attr_types"]=Strings(row.AttributeTypes),["attr_mods"]=new EvidenceArray(row.AttributeModifiers.Select(item=>(EvidenceValue)BuffEvidence.Object(
                ("attr_type",Text(item.AttributeType)),("bb_key",Text(item.BlackboardKey)),("use_key",Text(item.UseKey)),
                ("value",item.Value is double number ? new EvidenceReal(number) : EvidenceNull.Value))).ToArray()),
            ["is_weapon_buff"]=new EvidenceBoolean(row.IsWeaponBuff),["instance_start_line_no"]=new EvidenceInteger(row.InstanceStartLineNumber),
            ["enable_observations"]=Rows(row.EnableObservations),["creation_observations"]=Rows(row.CreationObservations),["attribute_refresh_snapshots"]=Rows(row.AttributeRefreshSnapshots),
        };
        if(row.EndLineNumber is int endLine) fields["end_line_no"]=new EvidenceInteger(endLine);
        if(row.RawDurationSource is not null) fields["raw_duration_source"]=Text(row.RawDurationSource);
        if(row.LifetimeMode is not null) { fields["lifetime_mode"]=Text(row.LifetimeMode);fields["lifetime_source"]=Text("typed_current_BuffData"); }
        if(row.SnapshotUpdate) fields["snapshot_update"]=new EvidenceBoolean(true);
        if(row.SnapshotEndTimestampMs is long boundary) fields["snapshot_end_ts_ms"]=new EvidenceInteger(boundary);
        if(row.SnapshotEndLineNumber is int boundaryLine) fields["snapshot_end_line_no"]=new EvidenceInteger(boundaryLine);
        if(row.LiveIdentityConflict) fields["rdps_live_identity_conflict"]=new EvidenceBoolean(true);
        if(row.DynamicIdentityConflict) fields["rdps_dynamic_identity_conflict"]=new EvidenceBoolean(true);
        if(row.ConflictingEnableState) fields["rdps_conflicting_enable_state"]=new EvidenceBoolean(true);
        if(row.OriginObservations is not null) fields["origin_observations"]=Rows(row.OriginObservations);
        if(row.RepeatedCreationObservations is not null) fields["repeated_creation_observations"]=Rows(row.RepeatedCreationObservations);
        if(row.PacketCreationContexts is not null) fields["packet_creation_contexts"]=Rows(row.PacketCreationContexts);
        if(row.ResistanceParameterSnapshots is not null) fields["resistance_parameter_snapshots"]=Rows(row.ResistanceParameterSnapshots);
        if(row.KeywordRateSnapshots is not null) fields["keyword_rate_snapshots"]=Rows(row.KeywordRateSnapshots);
        return new(fields);
    }
}
