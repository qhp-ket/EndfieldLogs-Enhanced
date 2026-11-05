using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Observed packet shape is diagnostic evidence, not permission to allocate damage.</summary>
public static class PacketBuffClassification
{
    private static readonly HashSet<string> UtilityKeys = new(["atb", "atk_duration", "cd", "comboskill_cooldown",
        "common_character_perfect_dodge", "count", "damage_interval", "duration", "dodgeSkillId", "heal_value", "healvalue",
        "hp_up", "lv", "max_stack", "poise", "posie", "probability", "ratio", "shelter", "skill_bg_type", "speed", "vfx_buff_name"], StringComparer.Ordinal);
    private static readonly HashSet<string> DamageKeys = new(["atk_up", "atk_up2", "crit_up", "crit_up2", "crit_dmg_up",
        "def_decrease", "def_decrease_tick", "def_decrease_tick_final", "dmg_up", "fire_dmg_up", "ignore_fire_resist",
        "max_def_decrease", "max_def_decrease_final", "normal_atk_up_valid", "pd_up", "phy_dmg_up", "phy_dmg_up2",
        "spell_damage_taken_up", "spell_dmg_up", "spell_taken_up", "spell_up", "start_def_decrease"], StringComparer.Ordinal);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    public static bool HasDamageShape(string key)
    {
        var lower = key.ToLowerInvariant();
        return DamageKeys.Contains(lower) || new[] { "def_decrease", "resist", "taken_up", "vulnerable", "fragile", "dmg_up", "damage_up", "spell_up", "atk_up", "crit" }
            .Any(token => lower.Contains(token, StringComparison.Ordinal))
            || lower.StartsWith("ignore_", StringComparison.Ordinal) && (lower.Contains("res", StringComparison.Ordinal) || lower.Contains("def", StringComparison.Ordinal));
    }
    public static EvidenceObject Classify(EvidenceObject record)
    {
        static EvidenceObject Result(string status, string category, string label, string reason) => BuffEvidence.Object(
            ("status", new EvidenceText(status)), ("class", new EvidenceText(category)), ("label", new EvidenceText(label)), ("reason", new EvidenceText(reason)));
        if (record.Get("packet_mapping") is EvidenceObject mapping)
            return Result("mapped", Text(CatalogValues.Or(mapping.Get("role"), new EvidenceText("mapped"))), "已接受映射", Text(mapping.Get("reason")));
        var raw = CatalogValues.Text(CatalogValues.Or(record.Get("raw_event_key"), record.Get("event_key"), new EvidenceText("unknown_buff")));
        if (!SkillIdentityCatalog.IsDigitText(raw)) return Result("static_id", "static", "静态 ID", "buff id is already a static string id");
        var owner = Text(CatalogValues.Or(record.Get("owner_raw"), record.Get("target_character_key"), record.Get("target_enemy_key")));
        var source = Text(CatalogValues.Or(record.Get("raw_source"), record.Get("source_character_key")));
        if (!new[] { owner, source }.Any(value => value.StartsWith("chr_", StringComparison.Ordinal) || value.StartsWith("eny_", StringComparison.Ordinal)))
            return Result("unmapped", "orphan_actor", "孤立 actor", "numeric buff has no character/enemy owner or source context");
        var keys = CatalogValues.Iterable(CatalogValues.Or(record.Get("bb_keys"), new EvidenceArray([]))).Select(CatalogValues.Text).ToHashSet(StringComparer.Ordinal);
        if (CatalogValues.Truth(record.Get("bb_values")))
            keys.UnionWith((record.Get("bb_values") as EvidenceObject ?? throw new InvalidDataException("Blackboard must be an object")).Fields.Keys);
        if (BuffDisplayClassification.IsInternalTrigger(record))
            return Result("unmapped", "utility_or_marker", "内部触发窗", "numeric buff matches common cryst-triggered helper keys and should not be treated as an external damage buff");
        var damage = keys.Where(HasDamageShape).Order(PythonDisplay.CodePointComparer).ToArray();
        if (damage.Length > 0) return Result("unmapped", "rdps_effect", "疑似 rDPS 效果", "numeric buff has rDPS-shaped blackboard keys: " + string.Join(", ", damage));
        if (keys.Count == 0) return Result("unmapped", "no_blackboard", "无黑板", "numeric buff carried no blackboard values in this trace");
        return keys.All(key => UtilityKeys.Contains(key.ToLowerInvariant()))
            ? Result("unmapped", "utility_or_marker", "工具/标记", "only utility blackboard keys were observed")
            : Result("unmapped", "unknown_blackboard", "未知黑板", "blackboard keys exist but do not match accepted rDPS patterns");
    }
}
