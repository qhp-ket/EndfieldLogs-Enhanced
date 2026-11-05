using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Canonical identities plus structured type/order evidence for independent legacy export.</summary>
public static class TraceValueProjection
{
    private static readonly HashSet<string> InstanceFields = new(["attacker_id", "target_id", "event_inst_id", "event_owner_id", "part_inst_id", "buff_inst_id", "entity_id", "object_id", "weapon_id", "gem_id", "gem_weapon_id", "owner_id", "skill_inst_id", "source_actor_id", "operation_owner_id", "environment_inst_id", "projectile_id", "game_inst_id", "game_unique_id", "interactive_obj_id", "npc_proxy_id", "npc_obj_id", "battle_inst_id"], StringComparer.Ordinal);
    private static EvidenceObject Object(Dictionary<string, EvidenceValue> fields) => new(fields);
    private static EvidenceObject Empty() => Object([]);
    private static EvidenceText Text(string value) => new(value);

    public static (EvidenceValue Value, EvidenceObject Layout) Capture(EvidenceValue value, bool identity = false, bool ordered = false)
    {
        if (identity)
        {
            var kind = value switch { EvidenceInteger => "integer", EvidenceReal => "real", EvidenceText => "text", EvidenceBoolean => "boolean", EvidenceNull => "null", _ => throw new InvalidDataException("Instance identity must be a scalar") };
            BigInteger? number = value switch
            {
                EvidenceInteger integer => integer.Value,
                EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
                EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
                EvidenceText text when BigInteger.TryParse(text.Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var integer) => integer,
                _ => null,
            };
            EvidenceValue normalized = number is { Sign: >= 0 } valid ? Text(valid.ToString(CultureInfo.InvariantCulture)) : EvidenceNull.Value;
            Dictionary<string, EvidenceValue> shape = new() { ["scalar"] = Text(kind) };
            if ((kind == "integer" && normalized is EvidenceNull) || (kind == "text" && !EvidenceJson.PythonEquals(value, normalized)) || kind is "real" or "boolean")
                shape["raw"] = Text(PythonDisplay.String(value));
            return (normalized, Object(shape));
        }
        if (value is EvidenceReal realValue && !double.IsFinite(realValue.Value))
        {
            var status = double.IsNaN(realValue.Value) ? "nan" : realValue.Value > 0 ? "positive_infinity" : "negative_infinity";
            return (Object(new() { ["number_status"] = Text(status) }), Object(new() { ["nonfinite"] = Text(status) }));
        }
        if (value is EvidenceObject obj)
        {
            Dictionary<string, EvidenceValue> result = [], children = [], shape = [];
            foreach (var (key, child) in obj.Fields)
            {
                var item = Capture(child, InstanceFields.Contains(key), ordered || key is "modifier_args" or "observation");
                result[key] = item.Value;
                if (item.Layout.Fields.Count > 0) children[key] = item.Layout;
            }
            if (ordered) shape["keys"] = new EvidenceArray(obj.Fields.Keys.Select(key => (EvidenceValue)Text(key)).ToArray());
            if (children.Count > 0) shape["children"] = Object(children);
            return (Object(result), Object(shape));
        }
        if (value is EvidenceArray array)
        {
            List<EvidenceValue> result = []; Dictionary<string, EvidenceValue> children = [];
            for (var i = 0; i < array.Items.Count; i++)
            {
                var item = Capture(array.Items[i], ordered: ordered); result.Add(item.Value);
                if (item.Layout.Fields.Count > 0) children[i.ToString(CultureInfo.InvariantCulture)] = item.Layout;
            }
            return (new EvidenceArray(result), children.Count > 0 ? Object(new() { ["items"] = Object(children) }) : Empty());
        }
        return (value, Empty());
    }

    public static EvidenceValue Restore(EvidenceValue value, EvidenceObject layout)
    {
        if (layout.Fields.Count == 0) return value;
        if (layout.Get("scalar") is EvidenceText kind)
        {
            var raw = layout.Fields.TryGetValue("raw", out var token) ? token : value;
            var text = raw is EvidenceText literal ? literal.Value : "";
            return kind.Value switch
            {
                "null" => EvidenceNull.Value,
                "integer" => new EvidenceInteger(BigInteger.Parse(text, CultureInfo.InvariantCulture)),
                "real" => new EvidenceReal(text switch { "nan" => double.NaN, "inf" => double.PositiveInfinity, "-inf" => double.NegativeInfinity, _ => double.Parse(text, CultureInfo.InvariantCulture) }),
                "boolean" => new EvidenceBoolean(text == "True"),
                "text" => raw,
                _ => throw new InvalidDataException("Unknown legacy scalar kind"),
            };
        }
        if (layout.Get("nonfinite") is EvidenceText status)
        {
            if (value is not EvidenceObject marker || marker.Fields.Count != 1 || !EvidenceJson.PythonEquals(marker.Get("number_status"), status))
                throw new InvalidDataException("Numeric evidence status differs from layout");
            return new EvidenceReal(status.Value switch { "nan" => double.NaN, "positive_infinity" => double.PositiveInfinity, "negative_infinity" => double.NegativeInfinity, _ => throw new InvalidDataException("Unknown numeric status") });
        }
        if (value is EvidenceObject obj)
        {
            var keys = layout.Get("keys") is EvidenceArray order ? order.Items.Select(item => item is EvidenceText key ? key.Value : throw new InvalidDataException("Expected legacy key")).ToArray() : obj.Fields.Keys.ToArray();
            if (keys.Length != obj.Fields.Count || !keys.ToHashSet(StringComparer.Ordinal).SetEquals(obj.Fields.Keys)) throw new InvalidDataException("Legacy key order does not match evidence");
            var children = layout.Get("children") as EvidenceObject;
            return Object(keys.ToDictionary(key => key, key => Restore(obj.Get(key), children?.Get(key) as EvidenceObject ?? Empty()), StringComparer.Ordinal));
        }
        if (value is EvidenceArray array)
        {
            var children = layout.Get("items") as EvidenceObject;
            return new EvidenceArray(array.Items.Select((child, i) => Restore(child, children?.Get(i.ToString(CultureInfo.InvariantCulture)) as EvidenceObject ?? Empty())).ToArray());
        }
        return value;
    }
}
