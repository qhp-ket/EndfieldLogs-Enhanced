using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static partial class DamageLegacyExporter
{
    internal static readonly (string Input, string Token)[] CalculationFields = [
        ("client_calc_result_value", "clientCalc"), ("client_final_damage_scale", "clientFinalScale"), ("client_attack_value", "clientAttack"),
        ("client_crit_add_scale", "clientCritAdd"), ("client_def_attr_defender_def", "clientDef"), ("client_def_resistance", "clientDefResistance"),
        ("client_dmg_type_resistance", "clientDmgTypeResistance"), ("client_defender_poise_factor", "clientPoiseFactor"),
        ("client_ignite_damage_scalar", "clientIgniteScalar"), ("client_final_value", "clientFinalValue"), ("client_weak_damage_scalar", "clientWeakScalar"),
        ("client_shelter_damage_scalar", "clientShelterScalar"), ("client_physical_infliction_damage_scalar", "clientPhysicalInflictionScalar")];
    private static string[] ModifierUids(EvidenceObject mods, string key) => Rows(mods.Get(key)).Select(row => Text(row.Get("buff_inst_id"))).Where(value => value.Length > 0).ToArray();
    private static string[] AttrInfo(EvidenceObject report, string key) => Rows(report.Get(key)).Where(row => Int(row.Get("attr_type")) is not null)
        .Select(row => I(Int(row.Get("attr_type"))) + ":" + string.Join(',', Items(row.Get("attrs")).Select(value => Float(value) is { } number ? PythonDisplay.Float(number) : S(value)))).ToArray();
    internal static void WriteEvidence(EvidenceObject e, EvidenceObject detail, EvidenceObject presence, long ts, BigInteger hitSeq, Action<long, string> write)
    {
        var mods = Obj(detail.Get("modifier_args")); var atk = ModifierUids(mods, "attacker_modifiers"); var def = ModifierUids(mods, "defender_modifiers");
        if (atk.Length > 0 || def.Length > 0)
        {
            write(ts, $"PKT_MOD #{hitSeq} atk=[{string.Join(' ', atk)}] def=[{string.Join(' ', def)}]");
            write(ts, $"PKT_MOD_DETAIL #{hitSeq} " + Json(Make(("attacker", Truth(mods.Get("attacker_modifiers")) ? mods.Get("attacker_modifiers") : new EvidenceArray([])),
                ("defender", Truth(mods.Get("defender_modifiers")) ? mods.Get("defender_modifiers") : new EvidenceArray([])),
                ("packetSessionId", e.Get("session_id")), ("packetSeq", e.Get("seq_id")), ("damageUnitIndex", detail.Get("damage_unit_index")), ("partInstId", detail.Get("part_inst_id"))), finite: true));
        }
        var report = Obj(detail.Get("battle_report_info"));
        var reportPresent = presence.Get("has_battle_report_info") is EvidenceBoolean flag ? (bool?)flag.Value : detail.Get("battle_report_info") is EvidenceObject ? true : null;
        if (reportPresent is not null) write(ts, $"PKT_ATTR_INFO #{hitSeq} " + Json(Make(("reportPresent", reportPresent), ("packetSeq", e.Get("seq_id")), ("packetSessionId", e.Get("session_id")))));
        var atkAttrs = AttrInfo(report, "attacker_attr_modify_info"); var defAttrs = AttrInfo(report, "defender_attr_modify_info");
        if (atkAttrs.Length > 0 || defAttrs.Length > 0) write(ts, $"PKT_ATTR #{hitSeq} atk=[{string.Join(' ', atkAttrs)}] def=[{string.Join(' ', defAttrs)}]");
        var debug = new[] { ("has_calculation_check_args", "calcCheck", true), ("has_calculate_damage_check_args", "calcArgs", true),
            ("processor_debug_args_count", "procArgs", false), ("has_attacker_attr_modifier_debug_data", "attDbg", true), ("has_defender_attr_modifier_debug_data", "defDbg", true),
            ("attacker_modifier_debug_handle_count", "atkModDbgHandles", false), ("defender_modifier_debug_handle_count", "defModDbgHandles", false),
            ("attacker_modifier_debug_arg_entry_count", "atkModDbgArgs", false), ("defender_modifier_debug_arg_entry_count", "defModDbgArgs", false) }
            .Select(pair => (Key: pair.Item2, Number: pair.Item3 ? new BigInteger(Truth(presence.Get(pair.Item1)) ? 1 : 0) : Int(presence.Get(pair.Item1)) ?? 0)).ToArray();
        if (debug.Any(pair => !pair.Number.IsZero)) write(ts, $"PKT_DBG #{hitSeq} " + string.Join(' ', debug.Select(pair => pair.Key + "=" + I(pair.Number))));
    }
}
