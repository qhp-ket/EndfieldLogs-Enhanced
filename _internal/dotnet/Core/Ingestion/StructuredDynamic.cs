using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class StructuredDynamic
{
    public static void Accept(TraceEvent item, int evidenceIndex, BuffDynamicObservations dynamics)
    {
        if (item.Type is not ("blackboard_dynamic" or "buff_attribute_refresh" or "blackboard_skill_setting"))
            throw new InvalidDataException("Expected dynamic blackboard event");
        if (item.Data.Get("observation") is not EvidenceObject observation) throw new InvalidDataException("Expected runtime identity proof");
        foreach (var fields in new[] { item.Data, observation })
            foreach (var key in new[] { "buff_inst_id", "owner_id", "operation_owner_id", "environment_inst_id" })
                if (fields.Get(key) is not EvidenceNull && (fields.Get(key) is not EvidenceText id || id.Value.Length == 0 || id.Value.Any(unit => unit is < '0' or > '9')))
                    throw new InvalidDataException("Instance identities must be decimal strings");
        var data = TraceModel.Data(item);
        // Read-skill-setting has always been diagnostic; it is not a refresh.
        if (item.Type == "blackboard_skill_setting") return;
        var refresh = item.Type == "buff_attribute_refresh";
        dynamics.Observe(refresh, refresh ? new Dictionary<string, string>() : DynamicWire.Fields(data), BuffPacketWire.Observation(data, pairs: false), evidenceIndex, item.CapturedAtMs);
    }
}
