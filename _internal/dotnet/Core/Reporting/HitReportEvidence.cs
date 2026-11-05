using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Compatibility projection of typed hits and late packet evidence at a report boundary.</summary>
public static class HitReportEvidence
{
    private static EvidenceValue Text(string? value)=>BuffEvidence.Text(value);
    private static EvidenceValue Integer(BigInteger? value)=>BuffEvidence.Number(value);
    private static EvidenceValue Real(double? value)=>value is double number ? new EvidenceReal(number) : EvidenceNull.Value;
    private static EvidenceArray Strings(IEnumerable<string> values)=>new(values.Select(Text).ToArray());
    private static EvidenceArray Integers(IEnumerable<BigInteger> values)=>new(values.Select(value=>(EvidenceValue)new EvidenceInteger(value)).ToArray());
    private static EvidenceObject Map<TKey,TValue>(IReadOnlyDictionary<TKey,TValue> values,Func<TValue,EvidenceValue> project) where TKey:notnull
        =>new(values.ToDictionary(pair=>pair.Key is IFormattable key ? key.ToString(null,CultureInfo.InvariantCulture) : pair.Key.ToString()!,
            pair=>project(pair.Value),StringComparer.Ordinal));
    private static EvidenceObject Sides(PacketListEvidence? values)=>BuffEvidence.Object(
        ("attacker",Strings(values?.Attacker ?? [])),("defender",Strings(values?.Defender ?? [])));

    public static EvidenceObject Packet(HitPacketEvidence packet)
    {
        Dictionary<string,EvidenceValue> fields=new(StringComparer.Ordinal)
        {
            ["character_key"]=Text(packet.CharacterKey),["packet_seq_id"]=Integer(packet.PacketSequence),["packet_session_id"]=Text(packet.PacketSession),
        };
        if(packet.RawDamage is { } raw) fields["dpd_raw"]=BuffEvidence.Object(
            ("calc",Real(raw.Calculation)),("atk_scale",Real(raw.AttackScale)),("blocked",Integer(raw.Blocked)),
            ("damage_type_raw",Text(raw.DamageTypeRaw)),("decorate_mask_raw",Text(raw.DecorateMaskRaw)),("collider",Text(raw.Collider)),
            ("atk_zones",new EvidenceArray(raw.AttackerZones.Select(Real).ToArray())),("def_zones",new EvidenceArray(raw.DefenderZones.Select(Real).ToArray())));
        if(packet.Baseline is not null) fields["baseline"]=Map(packet.Baseline,value=>new EvidenceReal(value));
        if(packet.AttributeReportPresent is bool present) fields["packet_attribute_report_present"]=new EvidenceBoolean(present);
        if(packet.AttributeReportUnresolved) fields["packet_attribute_report_unresolved"]=new EvidenceBoolean(true);
        if(packet.ModifierHandles is not null) fields["packet_modifier_handles"]=BuffEvidence.Clone(packet.ModifierHandles);
        if(packet.ModifierHandlesUnresolved) fields["packet_modifier_handles_unresolved"]=new EvidenceBoolean(true);
        if(packet.Modifiers is not null) { fields["packet_modifier_seen"]=new EvidenceBoolean(true);fields["packet_modifier_uids"]=Sides(packet.Modifiers); }
        if(packet.Attributes is not null) { fields["packet_attr_seen"]=new EvidenceBoolean(true);fields["packet_attr_details"]=Sides(packet.Attributes); }
        if(packet.AttributeConflict) fields["packet_attr_conflict"]=new EvidenceBoolean(true);
        if(packet.UnresolvedEffectConditions) fields["rdps_unresolved_effect_conditions"]=new EvidenceBoolean(true);
        return new(fields);
    }

    public static EvidenceObject Project(DamageHit hit)
    {
        var id=hit.Identity;
        var action=hit.Action;
        var value=hit.Amounts;
        var arts=hit.ArtsStrength;
        Dictionary<string,EvidenceValue> fields=new(StringComparer.Ordinal)
        {
            ["seq"]=Integer(id.Sequence),["line_no"]=Integer(id.LineNumber),["ts_ms"]=Integer(id.TimestampMs),
            ["character_key"]=Text(id.Character),["character_name"]=Text(id.CharacterName),
            ["target_enemy_key"]=Text(id.Target),["target_enemy_name"]=Text(id.TargetName),
            ["raw_skill_key"]=Text(id.RawSkill),["skill_key"]=Text(id.Skill),["skill_name"]=Text(id.SkillName),
            ["target_actor_id"]=Text(id.TargetActor),["source_actor_id"]=Text(id.SourceActor),
            ["skill_level"]=Integer(action.SkillLevel),["template_int_id"]=Integer(action.TemplateInteger),
            ["event_inst_id"]=Text(action.EventInstance),["event_owner_id"]=Text(action.EventOwner),
            ["packet_owner_id"]=Text(action.PacketOwner),["packet_generation"]=Integer(action.PacketGeneration),
            ["client_tick_ms"]=Integer(action.ClientTick),["action_id"]=Integer(action.Action),["damage_unit_index"]=Integer(action.UnitIndex),
            ["damage_unit_index_source"]=EvidenceNull.Value,["original_template_int_id"]=Integer(action.OriginalTemplate),
            ["dynamic_bb_signature"]=Text(hit.Blackboards.DynamicSignature),["dynamic_bb_values"]=Map(hit.Blackboards.Dynamic,item=>new EvidenceReal(item)),
            ["calc_bb_signature"]=Text(hit.Blackboards.CalculationSignature),["calc_bb_values"]=Map(hit.Blackboards.Calculation,item=>BuffEvidence.Clone(new EvidenceObject(item))),
            ["damage_element"]=Text(hit.Element),["damage_school"]=Text(hit.School),["damage_element_source"]=Text(hit.Element is null ? null : "official_action_unit"),
            ["damage_decorate_mask"]=EvidenceNull.Value,["damage_decorate_mask_source"]=EvidenceNull.Value,
            ["static_damage_decorate_mask"]=Integer(hit.StaticUnit?.StaticMask),["static_damage_decorate_mask_source"]=Text(hit.StaticUnit?.StaticMaskSource),
            ["damage_calculation"]=hit.StaticUnit?.Calculation is { } calculation ? BuffEvidence.Clone(calculation) : EvidenceNull.Value,
            ["skill_group_type"]=Integer(action.Group),["skill_family_key"]=Text(action.Family),
            ["hit_value"]=Integer(value.Value),["raw_hit_value"]=Integer(value.RawValue),
            ["packet_hit_value"]=Integer(value.PacketHit),["packet_raw_value"]=Real(value.PacketRaw),["packet_final_value"]=Real(value.PacketFinal),
            ["damage_value_source"]=Text(value.Source),["rdps_basis_value"]=Integer(value.Value),["rdps_basis_source"]=Text(value.Source),
            ["overkill_damage"]=Integer(value.Overkill),["enemy_hp_after"]=Integer(value.EnemyHpAfter),["enemy_hp_after_observed"]=new EvidenceBoolean(value.EnemyHpObserved),
            ["crit_flag"]=Integer(value.CriticalFlag),["critical_flag_observed"]=new EvidenceBoolean(value.CriticalFlagObserved),
            ["critical_observation"]=hit.Critical is { } critical ? BuffEvidence.Object(("template",Text(critical.Template)),
                ("values",Map(critical.Values,item=>new EvidenceReal(item))),("lines",Map(critical.Lines,item=>new EvidenceInteger(item))),
                ("times",Map(critical.Times,item=>Integer(item)))) : EvidenceNull.Value,
            ["part_inst_id"]=Integer(action.PartInstance),["hit_index"]=Integer(action.HitIndex),
            ["dpd_raw"]=EvidenceNull.Value,["baseline"]=EvidenceNull.Value,["packet_modifier_seen"]=new EvidenceBoolean(false),
            ["packet_modifier_uids"]=Sides(null),["packet_attr_details"]=Sides(null),
            ["arts_strength_damage_observed"]=new EvidenceBoolean(arts.Observed),["arts_strength_damage_kind"]=Text(arts.Kind),
            ["arts_strength_damage_source"]=Text(arts.Source),["arts_strength_damage_factor_count"]=Integer(arts.FactorCount),
        };
        foreach(var (key,item) in Packet(hit.Packet).Fields) fields[key]=item;
        if(hit.TargetStats.Unresolved) fields["rdps_unresolved_target_binding"]=new EvidenceBoolean(true);
        if(hit.AttackerStats.Unresolved) fields["rdps_unresolved_attacker_binding"]=new EvidenceBoolean(true);
        if(hit.TargetStats.Snapshot is { } target)
        {
            fields["target_stats_snapshot_ts_ms"]=Integer(target.TimestampMs);
            fields["target_stats_snapshot_line_no"]=Integer(target.LineNumber);
            fields["target_stats_invalid_attr_types"]=Integers(target.InvalidAttributeTypes);
            if(hit.TargetStats.Defense is double defense) { fields["target_defense"]=Real(defense);fields["target_defense_source"]=Text("ENTITY_STATS.attr3"); }
            if(hit.TargetStats.ResistanceScalars.Count>0)
            { fields["target_resistance_scalars"]=Map(hit.TargetStats.ResistanceScalars,item=>new EvidenceReal(item));fields["target_resistance_source"]=Text("ENTITY_STATS.attr4_7_48_60"); }
            if(hit.TargetStats.ResistancePoints.Count>0)
            { fields["target_resistance_points"]=Map(hit.TargetStats.ResistancePoints,item=>new EvidenceReal(item));fields["target_resistance_points_source"]=Text("ENTITY_STATS.attr94_99"); }
        }
        if(hit.AttackerStats.Snapshot is { } attacker)
        {
            fields["attacker_stats_attrs"]=Map(attacker.Attributes,item=>new EvidenceReal(item));
            fields["attacker_stats_basic_attrs"]=Map(attacker.BasicAttributes,item=>new EvidenceReal(item));
            fields["attacker_stats_level"]=Integer(attacker.Level);fields["attacker_stats_source"]=Text("ENTITY_STATS");
            fields["attacker_stats_snapshot_ts_ms"]=Integer(attacker.TimestampMs);fields["attacker_stats_snapshot_line_no"]=Integer(attacker.LineNumber);
            fields["attacker_stats_observed_attr_count"]=Integer(attacker.Attributes.Count);fields["attacker_stats_invalid_attr_types"]=Integers(attacker.InvalidAttributeTypes);
        }
        return new(fields);
    }
}
