using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Structural packet proof mapping, independent of old-log formatting.</summary>
public static class BuffPacketWire
{
    private static readonly IReadOnlyDictionary<string, string> Fields = new Dictionary<string, string>
    {
        ["schemaVersion"]="schema_version", ["buffUid"]="buff_inst_id", ["buffTemplate"]="template",
        ["sourceActorId"]="source_actor_id", ["targetActorId"]="target_id", ["sessionId"]="session_id",
        ["operationSeq"]="operation_seq", ["operationOwnerId"]="operation_owner_id", ["operationGeneration"]="operation_generation",
        ["generationScope"]="generation_scope", ["sourceEvent"]="source_event", ["buffNumId"]="buff_num_id",
        ["buffId"]="buff_id", ["buffTemplateId"]="buff_template_id", ["assignedItems"]="assigned_items",
        ["isNewInstance"]="is_new_instance", ["priorUidObserved"]="prior_uid_observed", ["observationKind"]="observation_kind",
        ["enhanceMultiplier"]="enhance_multiplier", ["actionId"]="action_id", ["triggerType"]="trigger_type",
        ["creationActionType"]="creation_action_type", ["creationActionRuntimeCase"]="creation_action_runtime_case",
        ["environmentType"]="environment_type", ["ownerType"]="owner_type", ["environmentInstId"]="environment_inst_id",
        ["templateStrId"]="template_str_id", ["templateIntId"]="template_int_id", ["enabled"]="enabled",
        ["ownerId"]="owner_id", ["clientTickMs"]="client_tick_ms", ["generation"]="generation",
        ["addedBuffNumId"]="added_buff_num_id", ["modify"]="modify", ["operationPayloadCase"]="operation_payload_case",
        ["validationErrors"]="validation_errors",
        ["templateType"]="template_type", ["templateIdCase"]="template_id_case", ["actionType"]="action_type",
        ["actionRuntimeCase"]="action_runtime_case", ["eventContext"]="event_context", ["runtime"]="runtime",
        ["actionSerialization"]="action_serialization",
    };
    private static readonly IReadOnlyDictionary<string, string> Inverse = Fields.ToDictionary(pair => pair.Value, pair => pair.Key);
    public static EvidenceObject Data(EvidenceObject observation)
    {
        var mapped = observation.Fields.ToDictionary(pair => Fields[pair.Key], pair => pair.Value);
        if (mapped.GetValueOrDefault("modify") is EvidenceArray rows)
            mapped["modify"] = new EvidenceArray(rows.Items.Select(value => value is EvidenceObject row ? (EvidenceValue)new EvidenceObject(row.Fields.ToDictionary(
                pair => pair.Key switch { "configIndex" => "config_index", "rateAfter" => "rate_after", _ => throw new InvalidDataException("Unknown keyword row field") }, pair => pair.Value)) : value).ToArray());
        Dictionary<string, EvidenceValue> data = new() { ["observation"] = new EvidenceObject(mapped) };
        if (mapped.GetValueOrDefault("template") is EvidenceText { Value: "unknown_buff" })
        { mapped["template"] = EvidenceNull.Value; data["template_status"] = new EvidenceText("unresolved"); }
        return new(data);
    }
    public static EvidenceObject Observation(EvidenceObject data, bool pairs = true)
    {
        if (data.Get("observation") is not EvidenceObject observation) throw new InvalidDataException("Expected BUFF packet observation");
        var mapped = observation.Fields.ToDictionary(pair => Inverse[pair.Key], pair => pair.Value);
        if (mapped.GetValueOrDefault("modify") is EvidenceArray rows)
            mapped["modify"] = new EvidenceArray(rows.Items.Select(value => value is EvidenceObject row ? (EvidenceValue)new EvidenceObject(row.Fields.ToDictionary(
                pair => pair.Key switch { "config_index" => "configIndex", "rate_after" => "rateAfter", _ => throw new InvalidDataException("Unknown keyword row field") }, pair => pair.Value)) : value).ToArray());
        if (data.Get("template_status") is EvidenceText { Value: "unresolved" } && mapped.GetValueOrDefault("buffTemplate") is EvidenceNull)
            mapped["buffTemplate"] = new EvidenceText("unknown_buff");
        var result = new EvidenceObject(mapped);
        return pairs ? WithPairs(result) : result;
    }
    public static EvidenceObject WithPairs(EvidenceObject observation) => (EvidenceObject)Pairs(observation);
    private static EvidenceValue Pairs(EvidenceValue value) => value switch
    {
        EvidenceObject obj => ObjectPairs(obj),
        EvidenceArray array => new EvidenceArray(array.Items.Select(Pairs).ToArray()),
        _ => value,
    };
    private static EvidenceObject ObjectPairs(EvidenceObject obj)
    {
        var fields = obj.Fields.ToDictionary(pair => pair.Key, pair => Pairs(pair.Value));
        return new(fields) { SourcePairs = fields.ToArray() };
    }
}
