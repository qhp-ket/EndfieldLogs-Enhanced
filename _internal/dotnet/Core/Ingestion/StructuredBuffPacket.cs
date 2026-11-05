using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredBuffPacket
{
    public static Dictionary<string, string> UnresolvedFields(EvidenceObject data) => new()
    {
        ["uid"] = SkillWire.IdentityToken(data.Get("buff_inst_id")),
        ["seq"] = data.Fields.ContainsKey("operation_seq") ? PythonDisplay.String(data.Get("operation_seq")) : "unknown",
        ["triggerType"] = data.Get("trigger_type") is EvidenceInteger phase ? PythonDisplay.String(phase) : "unknown",
        ["actionId"] = PythonDisplay.String(data.Get("action_id")), ["ownerId"] = PythonDisplay.String(data.Get("target_id")),
        ["srcId"] = PythonDisplay.String(data.Get("source_actor_id")),
    };
    public static void Accept(TraceEvent item, int evidenceIndex, BuffPacketObservations packets)
    {
        if (item.Type is not ("buff_creation" or "buff_origin" or "buff_enable" or "buff_keyword" or "buff_unresolved"))
            throw new InvalidDataException("Expected BUFF packet event");
        var observation = item.Type == "buff_unresolved" ? item.Data
            : item.Data.Get("observation") as EvidenceObject ?? throw new InvalidDataException("Expected BUFF packet observation");
        foreach (var key in new[] { "buff_inst_id", "source_actor_id", "target_id", "owner_id", "operation_owner_id", "environment_inst_id" })
            if (observation.Get(key) is not EvidenceNull && (observation.Get(key) is not EvidenceText id || id.Value.Length == 0 || id.Value.Any(unit => unit is < '0' or > '9')))
                throw new InvalidDataException("Instance identities must be decimal strings");
        var data = (EvidenceObject)TraceValueProjection.Restore(item.Data, item.Data.Get("legacy_layout") as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>()));
        if (item.Type == "buff_unresolved") packets.ObserveUnresolved(UnresolvedFields(data), evidenceIndex, item.CapturedAtMs);
        else packets.Observe(item.Type, BuffPacketWire.Observation(data), evidenceIndex, item.CapturedAtMs);
    }
}
