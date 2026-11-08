using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class LoadoutLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("loadout_group" or "loadout_slot" or "loadout_stats")) throw new InvalidDataException("Expected loadout event");
        var data = ExportValues.Data(item);
        string N(string key) => LoadoutWire.Number(data, key).ToString(CultureInfo.InvariantCulture);
        string T(string key, string fallback = "") => LoadoutWire.Text(data, key, fallback);
        string body;
        if (item.Type == "loadout_group")
            body = $"LOADOUT reason={S(data.Get("reason"))} slotCount={S(data.Get("slot_count"))} memberCount={S(data.Get("member_count"))} roster=[{string.Join(' ', ((EvidenceArray)data.Get("roster")).Items.Cast<EvidenceObject>().Select(row => S(row.Get("entity_id"))))}]";
        else if (item.Type == "loadout_slot")
        {
            var complete = data.Get("equipment_snapshot_complete") is EvidenceBoolean flag ? "equipsComplete=" + (flag.Value ? 1 : 0) + " " : "";
            var unplaced = data.Get("unplaced_equipment") is EvidenceArray array ? "unplacedEquipInstIds=[" + string.Join(',', array.Items.Cast<EvidenceObject>().Select(row => S(row.Get("entity_id")))) + "] " : "";
            body = $"LOADOUT slot={N("slot")} char={S(data.Get("template"))} slotCharInstId={N("entity_id")} resolvedCharInstId={N("entity_id")} character=packet charInfo.instId={N("entity_id")} template={S(data.Get("template"))} charLv={N("char_level")} potential={N("potential")} weaponInstId={N("weapon_id")} weaponTemplate={T("weapon_template", "unknown_weapon")} weaponLv={N("weapon_lv")} refine={I(LoadoutWire.Integer(data.Get("refine")))} break={N("breakthrough")} attachedGem={N("gem_id")} equipInsts={T("equip_inst_ids", "{}")} equips={T("equips", "{}")} {complete}{unplaced}equipSuit={T("equip_suit", "{}")} skillIntIds=[{T("skill_int_ids")}]";
        }
        else body = $"LOADOUT_STATS slot={N("slot")} char={S(data.Get("template"))} weaponInstId={N("weapon_id")} weaponTemplate={T("weapon_template", "unknown_weapon")} weaponSync={T("weapon_sync_source", "missing")} weaponBaseAtk={Present(data.Get("weapon_base_atk"))} weaponBaseAtkLv1={Present(data.Get("weapon_base_atk_lv1"))} weaponBaseAtkMax={Present(data.Get("weapon_base_atk_max"))} weaponRefineStatsSource={T("weapon_refine_stats_source", "unknown")} weaponRefineStats={{{T("weapon_refine_stats")}}} weaponSourceSkills={{{T("weapon_source_skills")}}} gemInstId={N("gem_id")} gemWeaponId={N("gem_weapon_id")} gemTemplate={N("gem_template")} gemTerms={{{T("gem_terms")}}}";
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + body + "\n"];
    }
}
