using System.Globalization;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Observed scalar fields, distinct from the packet identity proof.</summary>
public static class DynamicWire
{
    public static EvidenceObject Data(EvidenceObject source, EvidenceValue action, double value, string owner, string skill, EvidenceObject observation)
    {
        var fields = BuffPacketWire.Data(observation).Fields.ToDictionary();
        foreach (var (input, output) in new[] { ("seq_id","operation_seq"), ("client_tick_tms","client_tick_ms"),
            ("inst_id","buff_inst_id"), ("owner_id","owner_id"), ("session_id","packet_session_id") })
            if (source.Fields.TryGetValue(input, out var item)) fields[output] = item;
        fields["action_id"] = action; fields["value"] = new EvidenceReal(value);
        fields["owner"] = owner == "?" ? EvidenceNull.Value : new EvidenceText(owner);
        fields["skill"] = skill == "unknown_skill" ? EvidenceNull.Value : new EvidenceText(skill);
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
        ["value"] = PythonDisplay.Float(SkillWire.Number(data.Get("value")) ?? throw new InvalidDataException("Expected runtime value")),
    };
}
