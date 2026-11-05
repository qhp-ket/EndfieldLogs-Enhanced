using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Independent legacy formatting; never used by typed live ingestion.</summary>
public static class TraceLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int offset) => item.Type switch
    {
        "damage" => DamageLegacyExporter.Lines(item, offset),
        "damage_raw" or "damage_baseline" or "legacy_attribute_modifier" or "legacy_damage_modifier" => HistoricalLegacyExporter.Lines(item, offset),
        "entity_stats" or "entity_attributes" or "entity_value" or "entity_die" or "ability_spawn" => EntityLegacyExporter.Lines(item, offset),
        "squad" or "actor_mapping" or "character_skills" or "identity_inference" => IdentityLegacyExporter.Lines(item, offset),
        "loadout_group" or "loadout_slot" or "loadout_stats" => LoadoutLegacyExporter.Lines(item, offset),
        "skill_cast" or "atb" or "poise" => SkillLegacyExporter.Lines(item, offset),
        "buff_start" or "buff_end" or "buff_blackboard" => BuffLegacyExporter.Lines(item, offset),
        "buff_creation" or "buff_origin" or "buff_enable" or "buff_keyword" or "buff_unresolved" => BuffPacketLegacyExporter.Lines(item, offset),
        "blackboard_dynamic" or "buff_attribute_refresh" or "blackboard_skill_setting" => DynamicLegacyExporter.Lines(item, offset),
        "blackboard_calculation" or "blackboard_modify" or "blackboard_preset" or "ink_release" => BlackboardLegacyExporter.Lines(item, offset),
        "clock_tick" or "clock_sync" or "time_freeze_request" or "time_freeze_state" => ClockLegacyExporter.Lines(item, offset),
        "battle_timer" or "official_timer" or "battle_phase" or "battle_timer_missing" => TimerLegacyExporter.Lines(item, offset),
        "game_instance" or "game_mechanics" or "scene_battle" or "battle_reset" or "session_warning" => ContextLegacyExporter.Lines(item, offset),
        "dungeon" or "contracts" or "battle_result" => StageLegacyExporter.Lines(item, offset),
        _ => throw new NotSupportedException("Independent export is not connected for " + item.Type),
    };

    public static void Write(TraceVolumeChain chain, TextWriter destination, CancellationToken cancellationToken = default)
    {
        foreach (var item in TraceVolumes.ReadEvents(chain, cancellationToken))
            foreach (var line in Lines(item, chain.Volumes[0].Header.TimeZoneOffsetMinutes)) destination.Write(line);
    }
}
