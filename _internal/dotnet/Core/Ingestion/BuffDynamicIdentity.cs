using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

internal sealed record BoundDynamicIdentity(EvidenceObject Payload, string Uid, string Template,
    BigInteger Sequence, BigInteger ActionId, BuffOperationContext Context, BuffRecord Record);

internal static class BuffDynamicIdentity
{
    public static BoundDynamicIdentity Bind(BuffInstanceState state, EvidenceObject identity, bool refresh,
        IReadOnlyDictionary<string, string> fields, string? skill, BigInteger? actionId, double? value)
    {
        var expected = refresh ? 31 : 7;
        var runtime = refresh ? "refresh_buff_attr_modifier_value_action" : "modify_dynamic_blackboard_action";
        var uid = BuffEvidence.String(identity.Get("environmentInstId"));
        var session = BuffEvidence.String(identity.Get("sessionId"));
        if (identity.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true }
            || identity.Get("actionType") is not EvidenceInteger type || type.Value != expected
            || BuffEvidence.String(identity.Get("actionRuntimeCase")) != runtime
            || identity.Get("operationPayloadCase") is not EvidenceText { Value: "trigger_action_op_data" }
            || identity.Get("ownerType") is not (EvidenceInteger { Value.IsOne: true } or EvidenceText { Value: "1" })
            || identity.Get("templateType") is not EvidenceText { Value: "Buff" }
            || identity.Get("triggerType") is not EvidenceInteger { Value.IsZero: true }
            || string.IsNullOrEmpty(session)
            || new[] { "operationSeq", "generation", "actionId" }.Any(key => identity.Get(key) is not EvidenceInteger number || number.Value < 0)
            || new[] { "environmentInstId", "ownerId", "operationOwnerId" }.Any(key => !BuffInstanceState.ValidPacketId(identity.Get(key)))
            || uid is "0" or "4294967295" || !EvidenceJson.PythonEquals(identity.Get("ownerId"), identity.Get("operationOwnerId"))
            || refresh && !EvidenceJson.PythonEquals(identity.Get("buffUid"), identity.Get("environmentInstId"))) throw new FormatException("invalid_dynamic_buff_identity");
        string? template;
        if (identity.Get("templateIdCase") is EvidenceText { Value: "int_id" } && identity.Get("templateIntId") is EvidenceInteger numberId
            && numberId.Value >= 0 && identity.Get("templateStrId") is EvidenceNull)
            template = state.Numbers.GetValueOrDefault(PythonDisplay.String(numberId));
        else if (identity.Get("templateIdCase") is EvidenceText { Value: "str_id" } && identity.Get("templateStrId") is EvidenceText { Value.Length: > 0 } textId
            && identity.Get("templateIntId") is EvidenceNull) template = textId.Value;
        else throw new FormatException("invalid_dynamic_template_oneof");
        if (!state.ActiveByUid.TryGetValue(uid!, out var record) || record.LiveIdentityConflict || record.DynamicIdentityConflict
            || template != record.EventKey || BuffEvidence.String(identity.Get("ownerId")) != record.TargetActorId) throw new FormatException("unbound_dynamic_buff_instance");
        var sequence = ((EvidenceInteger)identity.Get("operationSeq")).Value;
        if (record.CreationObservations.Count == 0 || record.CreationObservations.Any(row => BuffEvidence.String(row.Get("sessionId")) != session)
            || !record.CreationObservations.Any(row => BuffEvidence.Integer(row.Get("operationSeq")) <= sequence))
            throw new FormatException("missing_compatible_buff_creation_observation");
        var action = ((EvidenceInteger)identity.Get("actionId")).Value;
        if (!refresh && (fields.GetValueOrDefault("inst") != uid || fields.GetValueOrDefault("ownerId") != BuffEvidence.String(identity.Get("ownerId"))
            || actionId != action || skill != template || TraceFields.OptionalInteger(fields.GetValueOrDefault("seq")) != sequence || value is null))
            throw new FormatException("dynamic_text_identity_conflict");
        return new(identity, uid!, template!, sequence, action, new(session, BuffEvidence.String(identity.Get("operationOwnerId"))!, identity.Get("generation")), record);
    }

    public static EvidenceObject Parse(string text, out bool duplicateFields)
    {
        if (!text.StartsWith('{')) throw new FormatException("dynamic_identity_not_object");
        var value = EvidenceJson.ParseWithPairs(text);
        if (value is not EvidenceObject obj) throw new FormatException("dynamic_identity_not_object");
        duplicateFields = obj.SourcePairs?.Count != obj.Fields.Count;
        return new(obj.Fields);
    }
}
