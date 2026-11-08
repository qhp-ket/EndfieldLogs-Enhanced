using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Direct scalar observations; calculation state is owned by the ordered ink ledger.</summary>
public static class BlackboardWire
{
    public static EvidenceObject Data(EvidenceObject source, BigInteger action, string owner, string skill, params (string Key, EvidenceValue Value)[] values)
    {
        Dictionary<string, EvidenceValue> fields = [];
        foreach (var (input, output) in new[] { ("seq_id", "operation_seq"), ("client_tick_tms", "client_tick_ms"),
            ("inst_id", "buff_inst_id"), ("owner_id", "owner_id"), ("session_id", "packet_session_id") })
            if (source.Fields.TryGetValue(input, out var value)) fields[output] = value;
        fields["action_id"] = new EvidenceInteger(action);
        fields["owner"] = owner == "?" ? EvidenceNull.Value : new EvidenceText(owner);
        fields["skill"] = skill == "unknown_skill" ? EvidenceNull.Value : new EvidenceText(skill);
        foreach (var (key, value) in values) fields[key] = value;
        return new(fields);
    }
    public static Dictionary<string, string> Fields(EvidenceObject data) => new()
    {
        ["seq"] = (SkillWire.Integer(data.Get("operation_seq")) ?? 0).ToString(CultureInfo.InvariantCulture),
        ["tick"] = (SkillWire.Integer(data.Get("client_tick_ms")) ?? 0).ToString(CultureInfo.InvariantCulture),
        ["inst"] = SkillWire.IdentityToken(data.Get("buff_inst_id")), ["ownerId"] = SkillWire.IdentityToken(data.Get("owner_id")),
        ["owner"] = SkillWire.Label(data, "owner", "?"), ["packetSessionId"] = SkillWire.Label(data, "packet_session_id"),
        ["skill"] = SkillWire.Label(data, "skill", "unknown_skill"),
        ["actionId"] = (SkillWire.Integer(data.Get("action_id")) ?? 0).ToString(CultureInfo.InvariantCulture),
    };
    public static EvidenceObject ReleaseData(EvidenceObject observation) => new(new Dictionary<string, EvidenceValue>
    { ["observation"] = new EvidenceObject(observation.Fields.ToDictionary(pair => pair.Key == "buff_uid" ? "buff_inst_id" : pair.Key, pair => pair.Value)) });
    public static EvidenceObject ReleaseObservation(EvidenceObject data) => new(((EvidenceObject)data.Get("observation")).Fields
        .ToDictionary(pair => pair.Key == "buff_inst_id" ? "buff_uid" : pair.Key, pair => pair.Value));
    public static EvidenceObject Observation(TraceEvent item)
    {
        if (item.Type is not ("blackboard_calculation" or "blackboard_modify" or "blackboard_preset" or "ink_release"))
            throw new InvalidDataException("Expected blackboard or ink event");
        var fields = item.Type == "ink_release" ? item.Data.Get("observation") as EvidenceObject
            ?? throw new InvalidDataException("Expected release observation") : item.Data;
        foreach (var key in new[] { "buff_inst_id", "owner_id", "source_actor_id", "projectile_id" })
            if (fields.Get(key) is not EvidenceNull && (fields.Get(key) is not EvidenceText id || id.Value.Length == 0 || id.Value.Any(unit => unit is < '0' or > '9')))
                throw new InvalidDataException("Instance identities must be decimal strings");
        if (item.Type == "blackboard_calculation" && (item.Data.Get("key") is not EvidenceText || !item.Data.Fields.ContainsKey("final_value")))
            throw new InvalidDataException("Expected calculation key and result");
        if (item.Type == "blackboard_preset" && item.Data.Get("modified_value") is not EvidenceText)
            throw new InvalidDataException("Expected preset value");
        return TraceModel.Data(item);
    }
}
