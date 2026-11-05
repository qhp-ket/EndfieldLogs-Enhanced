using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Ordered input for the existing ledger, without rendering or reparsing a legacy line.</summary>
public sealed record InkObservation(BigInteger Number, string Kind, IReadOnlyDictionary<string, string> Fields,
    EvidenceValue? Release = null, EvidenceValue? Identity = null, bool IdentityPresent = false, bool InvalidIdentity = false)
{
    public static InkObservation FromEvent(BigInteger index, TraceEvent item)
    {
        if (item.Type is not ("ink_release" or "blackboard_dynamic" or "blackboard_calculation" or "actor_mapping" or "skill_cast"))
            return new(index, "other", new Dictionary<string, string>());
        var data = item.Type is "ink_release" or "blackboard_calculation" ? BlackboardWire.Observation(item)
            : (EvidenceObject)TraceValueProjection.Restore(item.Data, item.Data.Get("legacy_layout") as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>()));
        if (item.Type == "ink_release") return new(index, "release", new Dictionary<string, string>(), BlackboardWire.ReleaseObservation(data));
        if (item.Type == "blackboard_dynamic") return new(index, "operation", DynamicWire.Fields(data), Identity: BuffPacketWire.Observation(data, pairs: false), IdentityPresent: true);
        if (item.Type == "blackboard_calculation")
        {
            var fields = BlackboardWire.Fields(data);
            fields["key"] = PythonDisplay.String(data.Get("key"));
            fields["final"] = PythonDisplay.Float(SkillWire.Number(data.Get("final_value"))!.Value);
            foreach (var (source, target) in new[] { ("value_a", "valueA"), ("value_b", "valueB") })
                if (data.Fields.ContainsKey(source)) fields[target] = PythonDisplay.Float(SkillWire.Number(data.Get(source))!.Value);
            return new(index, "operation", fields);
        }
        if (item.Type == "actor_mapping") return new(index, "mapping", new Dictionary<string, string>
        { ["id"] = SkillWire.IdentityToken(data.Get("entity_id")), ["source"] = SkillWire.Label(data, "mapping_source"), ["template"] = SkillWire.Label(data, "template") });
        if (item.Type == "skill_cast" && data.Get("phase") is EvidenceText { Value: "start" }) return new(index, "cast", new Dictionary<string, string>
        {
            ["ownerId"] = SkillWire.IdentityToken(data.Get("owner_id")), ["skill"] = SkillWire.Label(data, "skill", "unknown_skill"),
            ["inst"] = SkillWire.IdentityToken(data.Get("skill_inst_id")),
            ["seq"] = (SkillWire.Integer(data.Get("operation_seq")) ?? 0).ToString(CultureInfo.InvariantCulture),
            ["startMs"] = (SkillWire.Integer(data.Get("client_tick_ms")) ?? 0).ToString(CultureInfo.InvariantCulture),
        });
        return new(index, "other", new Dictionary<string, string>());
    }
    public static InkObservation FromLegacy(InkTraceLine input)
    {
        var line = input.Text;
        if (line.Contains(" INK_RELEASE ", StringComparison.Ordinal))
        {
            try { return new(input.Number, "release", new Dictionary<string, string>(), EvidenceJson.Parse(line[(line.IndexOf(" INK_RELEASE ", StringComparison.Ordinal) + 13)..])); }
            catch (Exception error) when (error is FormatException or InvalidCastException or KeyNotFoundException or InvalidDataException)
            { return new(input.Number, "release", new Dictionary<string, string>()); }
        }
        var kind = line.Contains(" ACTOR_MAP ", StringComparison.Ordinal) ? "mapping"
            : line.Contains(" SKILL_CAST_START ", StringComparison.Ordinal) ? "cast"
            : line.Contains(" BB_MODIFY_DYNAMIC ", StringComparison.Ordinal) || line.Contains(" BB_SIMPLE_CALC ", StringComparison.Ordinal) ? "operation" : "other";
        if (kind == "other") return new(input.Number, kind, new Dictionary<string, string>());
        var fields = TraceFields.Extract(line.Split(" identity=", 2, StringSplitOptions.None)[0]);
        if (kind != "operation" || !line.Contains(" identity=", StringComparison.Ordinal)) return new(input.Number, kind, fields);
        try { return new(input.Number, kind, fields, Identity: EvidenceJson.Parse(line[(line.IndexOf(" identity=", StringComparison.Ordinal) + 10)..]), IdentityPresent: true); }
        catch (Exception error) when (error is FormatException or InvalidCastException or InvalidDataException)
        { return new(input.Number, kind, fields, IdentityPresent: true, InvalidIdentity: true); }
    }
}
