using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Native values and shared operation context, independent of legacy formatting.</summary>
public static class TraceModel
{
    internal static readonly HashSet<string> Identities = new(["attacker_id", "target_id", "event_inst_id", "event_owner_id", "part_inst_id", "buff_inst_id", "entity_id", "object_id", "weapon_id", "gem_id", "gem_weapon_id", "owner_id", "skill_inst_id", "source_actor_id", "operation_owner_id", "environment_inst_id", "projectile_id", "game_inst_id", "game_unique_id", "interactive_obj_id", "npc_proxy_id", "npc_obj_id", "battle_inst_id"], StringComparer.Ordinal);
    internal static readonly HashSet<string> OpaqueFields = new(["bb", "debug", "debug_args", "processor_debug_args", "invalid_fields", "normalization_errors"], StringComparer.Ordinal);
    private static readonly HashSet<string> Integers = new(["operation_seq", "operation_generation", "generation", "client_tick_ms",
        "tick_ms", "client_ts", "server_ts", "logical_ts", "message_id", "hit_seq", "detail_index", "action_id", "skill_level",
        "template_int_id", "original_template_int_id", "damage_unit_index", "char_level", "weapon_lv", "slot", "potential", "refine", "breakthrough"], StringComparer.Ordinal);
    private static EvidenceObject TypedFields(EvidenceObject data)
    {
        var errors = data.Get("normalization_errors") is EvidenceArray previous ? previous.Items.ToList() : [];
        Dictionary<string, EvidenceValue> NormalizeFields(EvidenceObject row, string path)
        {
            var fields = row.Fields.ToDictionary();
            foreach (var key in fields.Keys.Where(Integers.Contains).Order(StringComparer.Ordinal).ToArray())
            {
                var value = fields[key];
                if (value is EvidenceNull or EvidenceInteger) continue;
                if (value is EvidenceText text && Regex.IsMatch(text.Value, @"\A[+-]?[0-9]+\z"))
                    fields[key] = new EvidenceInteger(BigInteger.Parse(text.Value, CultureInfo.InvariantCulture));
                else
                {
                    errors.Add(new EvidenceObject(new Dictionary<string, EvidenceValue> {
                        ["path"] = new EvidenceText(path + "/" + key), ["status"] = new EvidenceText("invalid_integer"), ["raw"] = value }));
                    fields[key] = EvidenceNull.Value;
                }
            }
            return fields;
        }
        var root = NormalizeFields(data, "");
        foreach (var key in new[] { "observation", "action" })
            if (data.Get(key) is EvidenceObject row) root[key] = new EvidenceObject(NormalizeFields(row, "/" + key));
        if (errors.Count > 0) root["normalization_errors"] = new EvidenceArray(errors);
        return new(root);
    }
    private static readonly Dictionary<string, string> Context = new()
    {
        ["session_id"] = "session_id", ["operation_seq"] = "operation_seq", ["operation_owner_id"] = "owner_id",
        ["operation_generation"] = "generation", ["client_tick_ms"] = "client_tick_ms", ["generation"] = "generation",
    };
    private static readonly Dictionary<string, string[]> ObservationContext = new()
    {
        ["buff_creation"] = ["session_id", "operation_seq", "operation_owner_id", "operation_generation"],
        ["buff_origin"] = ["operation_seq"],
        ["buff_enable"] = ["operation_seq", "client_tick_ms", "generation"],
        ["buff_keyword"] = ["session_id", "operation_seq", "client_tick_ms", "generation"],
        ["blackboard_dynamic"] = ["session_id", "operation_seq", "operation_owner_id", "generation", "client_tick_ms"],
        ["buff_attribute_refresh"] = ["session_id", "operation_seq", "operation_owner_id", "generation", "client_tick_ms"],
        ["blackboard_skill_setting"] = ["session_id", "operation_seq", "operation_owner_id", "generation", "client_tick_ms"],
        ["ink_release"] = ["session_id", "operation_seq", "client_tick_ms"],
    };
    private static readonly Dictionary<string, string> RootContext = new()
    { ["operation_seq"] = "operation_seq", ["client_tick_ms"] = "client_tick_ms", ["packet_session_id"] = "session_id" };
    public static EvidenceValue Normalize(EvidenceValue value, bool identity = false)
    {
        List<EvidenceValue> errors = [];
        var result = Normalize(value, identity, errors, "");
        if (errors.Count > 0 && result is EvidenceObject obj)
        {
            var fields = obj.Fields.ToDictionary(); fields["normalization_errors"] = new EvidenceArray(errors); return new EvidenceObject(fields);
        }
        return result;
    }
    private static EvidenceValue Normalize(EvidenceValue value, bool identity, List<EvidenceValue> errors, string path, bool opaque = false)
    {
        if (identity && value is not EvidenceNull && value is not EvidenceInteger { Value.Sign: >= 0 }
            && !(value is EvidenceText textValue && textValue.Value.Length > 0 && textValue.Value.All(unit => unit is >= '0' and <= '9')))
            errors.Add(new EvidenceObject(new Dictionary<string, EvidenceValue>
            { ["path"] = new EvidenceText(path), ["status"] = new EvidenceText("invalid_identity"), ["raw"] = Normalize(value, false, [], path, opaque: true) }));
        if (identity) return value switch
        {
            EvidenceInteger { Value.Sign: >= 0 } number => new EvidenceText(number.Value.ToString(CultureInfo.InvariantCulture)),
            EvidenceText text when text.Value.Length > 0 && text.Value.All(unit => unit is >= '0' and <= '9')
                => new EvidenceText(System.Numerics.BigInteger.Parse(text.Value, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture)),
            _ => EvidenceNull.Value,
        };
        return value switch
        {
            EvidenceReal number when !double.IsFinite(number.Value) => new EvidenceObject(new Dictionary<string, EvidenceValue>
                { ["number_status"] = new EvidenceText(double.IsNaN(number.Value) ? "nan" : number.Value > 0 ? "positive_infinity" : "negative_infinity") }),
            EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key,
                pair => Normalize(pair.Value, !opaque && Identities.Contains(pair.Key), errors, path + "/" + pair.Key,
                    opaque || OpaqueFields.Contains(pair.Key)), StringComparer.Ordinal)),
            EvidenceArray array => new EvidenceArray(array.Items.Select((child, index) => Normalize(child, false, errors, path + "/" + index, opaque)).ToArray()),
            _ => value,
        };
    }
    public static EvidenceObject Compact(EvidenceObject input, EvidenceObject source, long? tick, string? type = null)
    {
        var fields = TypedFields((EvidenceObject)Normalize(input)).Fields.ToDictionary();
        var context = source.Fields.ToDictionary();
        if (tick is long time) context["client_tick_ms"] = new EvidenceInteger(time);
        foreach (var row in new[] { fields, fields.GetValueOrDefault("observation") is EvidenceObject observation ? observation.Fields.ToDictionary() : null })
        {
            if (row is null) continue;
            foreach (var (key, common) in ReferenceEquals(row, fields) ? RootContext : (ObservationContext.GetValueOrDefault(type ?? "") ?? []).ToDictionary(key => key, key => Context[key]))
                if (row.TryGetValue(key, out var child) && context.TryGetValue(common, out var shared)
                    && child.GetType() == shared.GetType() && EvidenceJson.PythonEquals(child, shared)) row.Remove(key);
            if (!ReferenceEquals(row, fields)) fields["observation"] = new EvidenceObject(row);
        }
        if (fields.GetValueOrDefault("evidence") is EvidenceObject evidence && evidence.Get("packet_context") is EvidenceObject { Fields.Count: 2 } packet
            && EvidenceJson.PythonEquals(packet.Get("packetSeq"), source.Get("operation_seq"))
            && EvidenceJson.PythonEquals(packet.Get("packetSessionId"), source.Get("session_id")))
            fields["evidence"] = new EvidenceObject(evidence.Fields.Where(pair => pair.Key != "packet_context").ToDictionary());
        return new(fields);
    }
    public static EvidenceObject Data(TraceEvent item)
    {
        // Only the explicit v1 adapter reads old scalar layouts.
        if (item.Data.Fields.ContainsKey("legacy_layout")) return TraceV1.NativeData(item.Data);
        var data = item.Data;
        if (data.Get("observation") is not EvidenceObject && item.Type is not ("skill_cast" or "atb" or "poise" or "entity_value" or "ability_spawn"
            or "blackboard_calculation" or "blackboard_modify" or "blackboard_preset" or "clock_tick" or "battle_timer" or "battle_phase" or "buff_unresolved")) return data;
        var context = item.Source.Fields.ToDictionary();
        if (item.ClientTickMs is long tick) context["client_tick_ms"] = new EvidenceInteger(tick);
        var fields = data.Fields.ToDictionary();
        foreach (var (key, common) in new[] { ("operation_seq", "operation_seq"), ("client_tick_ms", "client_tick_ms"), ("packet_session_id", "session_id") })
            if (!fields.ContainsKey(key) && context.TryGetValue(common, out var value)) fields[key] = value;
        if (data.Get("observation") is EvidenceObject observation)
        {
            var target = observation.Fields.ToDictionary();
            foreach (var (key, common) in (ObservationContext.GetValueOrDefault(item.Type) ?? []).ToDictionary(key => key, key => Context[key]))
                if (!target.ContainsKey(key) && context.TryGetValue(common, out var value)) target[key] = value;
            fields["observation"] = new EvidenceObject(target);
        }
        return new(fields);
    }
}
