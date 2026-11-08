using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Decoded source fields and their established analysis projections, never full trace rows.</summary>
public static class LoadoutWire
{
    private static readonly string[] SlotFields = ["slot", "char_level", "potential", "weapon_template", "weapon_lv", "refine", "breakthrough",
        "equip_inst_ids", "equips", "equip_suit", "skill_int_ids", "equipment_snapshot_complete"];
    private static readonly string[] StatsFields = ["slot", "weapon_template", "weapon_sync_source", "weapon_base_atk", "weapon_base_atk_lv1",
        "weapon_base_atk_max", "weapon_refine_stats_source", "weapon_refine_stats", "weapon_source_skills", "gem_template", "gem_terms"];
    public static EvidenceObject Data(EvidenceObject row, bool stats = false)
    {
        Dictionary<string, EvidenceValue> result = [];
        foreach (var key in stats ? StatsFields : SlotFields)
            if (row.Fields.TryGetValue(key, out var value)) result[key] = value;
        result["template"] = new EvidenceText(Text(row, "char"));
        foreach (var (source, target) in new[] { ("weapon_inst_id", "weapon_id"), ("attached_gem", "gem_id"),
            stats ? ("gem_weapon_id", "gem_weapon_id") : ("char_inst_id", "entity_id") })
            if (row.Fields.TryGetValue(source, out var value)) result[target] = value;
        if (!stats && row.Get("unresolved_equip_inst_ids") is EvidenceArray unresolved)
            result["unplaced_equipment"] = new EvidenceArray(unresolved.Items.Select(value => (EvidenceValue)new EvidenceObject(
                new Dictionary<string, EvidenceValue> { ["entity_id"] = value })).ToArray());
        return new(result);
    }
    public static BigInteger? Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger number => number.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text when BigInteger.TryParse(text.Value.Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var number) => number,
        _ => null,
    };
    public static BigInteger Number(EvidenceObject data, string key) => Integer(data.Get(key)) ?? BigInteger.Zero;
    public static string Text(EvidenceObject data, string key, string fallback = "") => CatalogValues.Truth(data.Get(key)) ? PythonDisplay.String(data.Get(key)) : fallback;
    public static string? CompactBody(string value)
    {
        var start = value.IndexOf('{'); if (start < 0) return null;
        var depth = 0;
        for (var index = start; index < value.Length; index++)
        {
            if (value[index] == '{') depth++;
            else if (value[index] == '}' && --depth == 0) return value[(start+1)..index];
        }
        return null;
    }
    private static EvidenceArray NativeRows(EvidenceObject data, string key) => data.Get(key) switch
    {
        EvidenceArray rows => rows,
        EvidenceNull => new EvidenceArray([]),
        _ => throw new InvalidDataException("Expected native loadout array: " + key),
    };
    public static LoadoutSlotObservation Slot(EvidenceObject data)
    {
        var level = Number(data, "weapon_lv"); var refine = Integer(data.Get("refine"));
        return new(((EvidenceText)data.Get("template")).Value)
        {
            Slot = Number(data, "slot"), CharacterLevel = Number(data, "char_level") is { IsZero: false } characterLevel ? characterLevel : null,
            Potential = Number(data, "potential"), WeaponInstance = Number(data, "weapon_id").ToString(CultureInfo.InvariantCulture),
            Weapon = Text(data, "weapon_template", "unknown_weapon"), WeaponLevel = level > 0 ? level : null,
            Refine = refine is not null && refine >= 0 && refine <= 5 ? refine : null,
            Breakthrough = Number(data, "breakthrough"),
            Suits = NativeRows(data, "equip_suit"), Equipment = NativeRows(data, "equips"),
            SkillIds = NativeRows(data, "skill_int_ids").Items.Select(PythonDisplay.String).ToArray(),
            UnplacedIds = data.Get("unplaced_equipment") is EvidenceArray unplaced ? unplaced.Items.Cast<EvidenceObject>()
                .Where(row => row.Get("entity_id") is not EvidenceNull).Select(row => PythonDisplay.String(row.Get("entity_id"))).ToArray() : null,
            EquipmentComplete = data.Get("equipment_snapshot_complete") is EvidenceBoolean complete
                && !(data.Get("invalid_fields") is EvidenceObject invalid && invalid.Fields.ContainsKey("equips")) ? complete.Value : null,
        };
    }
    public static LoadoutStatsObservation Stats(EvidenceObject data)
    {
        BigInteger Attack(string key) => TraceFields.OptionalInteger(data.Get(key) is EvidenceNull ? "unknown" : PythonDisplay.String(data.Get(key))) ?? BigInteger.Zero;
        return new(((EvidenceText)data.Get("template")).Value)
        {
            Weapon = Text(data, "weapon_template", "unknown_weapon"), WeaponInstance = Number(data, "weapon_id").ToString(CultureInfo.InvariantCulture),
            RefineStats = NativeRows(data, "weapon_refine_stats"), SourceSkills = NativeRows(data, "weapon_source_skills"),
            BaseAttack = Attack("weapon_base_atk"), BaseAttackLv1 = Attack("weapon_base_atk_lv1"), BaseAttackMax = Attack("weapon_base_atk_max"),
            GemInstance = Number(data, "gem_id").ToString(CultureInfo.InvariantCulture), GemWeapon = Number(data, "gem_weapon_id").ToString(CultureInfo.InvariantCulture),
            GemTemplate = Number(data, "gem_template").ToString(CultureInfo.InvariantCulture),
            Terms = NativeRows(data, "gem_terms"),
        };
    }
}
