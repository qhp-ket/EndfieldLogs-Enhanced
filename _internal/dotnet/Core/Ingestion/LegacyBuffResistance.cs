using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Older envelopes retain their narrower proof; modern malformed identity never falls back.</summary>
internal static class LegacyBuffResistance
{
    private static readonly string[] Keys = ["def_decrease", "additional_def_decrease"];

    public static void Observe(BuffInstanceState state, string? text, bool refresh, IReadOnlyDictionary<string, string> fields,
        string? skill, BigInteger? actionId, double? value, int lineNumber, long timestampMs)
        => Observe(state, () => text is null ? null : EvidenceJson.Parse(text) as EvidenceObject
            ?? throw new InvalidDataException("legacy_dynamic_observation_not_object"), refresh, fields, skill, actionId, value, lineNumber, timestampMs);

    public static void Observe(BuffInstanceState state, EvidenceObject observation, bool refresh, IReadOnlyDictionary<string, string> fields,
        string? skill, BigInteger? actionId, double? value, int lineNumber, long timestampMs)
        => Observe(state, () => observation, refresh, fields, skill, actionId, value, lineNumber, timestampMs);

    private static void Observe(BuffInstanceState state, Func<EvidenceObject?> read, bool refresh, IReadOnlyDictionary<string, string> fields,
        string? skill, BigInteger? actionId, double? value, int lineNumber, long timestampMs)
    {
        try
        {
            var observation = read();
            if (observation is null) return;
            if (observation.Get("eventContext") is not EvidenceObject context
                || new[] { "operationOwnerId", "ownerId", "environmentInstId", "generation", "templateType", "templateIdCase", "actionRuntimeCase", "operationPayloadCase" }
                    .Any(key => observation.Get(key) is not EvidenceNull)
                || PythonDisplay.String(context.Get("owner_type")) != "1" || context.Get("template_type") is not EvidenceText { Value: "Buff" }) return;
            var uid = PythonDisplay.String(context.Get("inst_id"));
            var owner = PythonDisplay.String(context.Get("owner_id"));
            var rawTemplate = context.Get("template_str_id");
            var template = context.Get("template_int_id") is EvidenceInteger number && !Truth(rawTemplate)
                ? state.Numbers.GetValueOrDefault(PythonDisplay.String(number)) : BuffEvidence.String(rawTemplate);
            if (template is null || !BuffCreationRuntimeProof.IsCorrosionPath(template) || observation.Get("schemaVersion") is not EvidenceInteger { Value.IsOne: true }
                || context.Get("seq_id") is not EvidenceInteger sequence || sequence.Value < 0 || observation.Get("actionId") is not EvidenceInteger action
                || !state.ActiveByUid.TryGetValue(uid, out var record) || record.EventKey != template || record.TargetActorId != owner
                || string.IsNullOrEmpty(record.SourceActorId) || string.IsNullOrEmpty(record.SourceCharacterKey) || record.LiveIdentityConflict
                || new[] { uid, owner, record.SourceActorId }.Any(id => !BuffInstanceState.ValidPacketId(new EvidenceText(id)))
                || record.PacketCreationContexts is not { Count: > 0 } anchors
                || anchors.Any(anchor => !EvidenceJson.PythonEquals(anchor.Get("session_id"), observation.Get("sessionId")))
                || anchors.Any(anchor => !(sequence.Value > BuffEvidence.Integer(anchor.Get("operation_seq"))))
                || !EvidenceJson.PythonEquals(observation.Get("operationSeq"), sequence)
                || !EvidenceJson.PythonEquals(observation.Get("actionType"), new EvidenceInteger(refresh ? 31 : 7))) return;
            var candidates = Candidates(state.Roots.GetValueOrDefault(template) ?? (EvidenceValue)EvidenceNull.Value, action);
            if (candidates.Count != 1 || !candidates[0].Enabled || candidates[0].Definition.Get("$type") is not EvidenceText type
                || type.Value != (refresh ? "Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data" : "Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data")) return;
            state.MarkProjectionChanged(record);
            var pending = record.ResistanceState;
            if (pending is null)
            {
                record.ResistanceState = pending = new();
                foreach (var keyName in Keys) pending.Values[keyName] = record.BlackboardValues.TryGetValue(keyName, out var initial) ? initial : null;
            }
            var key = BuffEvidence.String(candidates[0].Definition.Get("key"));
            if (!refresh && key is not null && Keys.Contains(key, StringComparer.Ordinal))
            {
                if (fields.GetValueOrDefault("inst") != uid || fields.GetValueOrDefault("ownerId") != owner || skill != template
                    || actionId != action.Value || TraceFields.OptionalInteger(fields.GetValueOrDefault("seq")) != sequence.Value) return;
                var signature = (action.Value, key, value);
                if (pending.Seen.TryGetValue(sequence.Value, out var previous))
                {
                    if (previous != signature)
                    {
                        pending.Invalid.Add(key);
                        foreach (var saved in record.ResistanceParameterSnapshots ?? [])
                            if (BuffEvidence.Integer(saved.Get("operation_seq")) >= sequence.Value) saved.Set("status", new EvidenceText("conflicting_dynamic_operation"));
                    }
                }
                else if (sequence.Value < pending.LastSequence) pending.Invalid.Add(key);
                else
                {
                    pending.Seen[sequence.Value] = signature;
                    pending.LastSequence = sequence.Value;
                    pending.Values[key] = value;
                    if (value is null || value > 0) pending.Invalid.Add(key); else pending.Invalid.Remove(key);
                }
            }
            else if (refresh)
            {
                var complete = pending.Invalid.Count == 0 && sequence.Value > pending.LastSequence && Keys.All(name => pending.Values.GetValueOrDefault(name) <= 0);
                var values = new EvidenceObject(pending.Values.ToDictionary(pair => pair.Key,
                    pair => pair.Value is double numeric ? (EvidenceValue)new EvidenceReal(numeric) : EvidenceNull.Value, StringComparer.Ordinal));
                var saved = new BuffObservation(BuffEvidence.Object(("operation_seq", sequence), ("line_no", new EvidenceInteger(lineNumber)),
                    ("ts_ms", new EvidenceInteger(timestampMs)), ("bb_values", values),
                    ("status", new EvidenceText(complete ? "attribute_parameters_observed" : "missing_attribute_parameters")),
                    ("identity_source", new EvidenceText("legacy_packet_uid_owner_template_sequence")),
                    ("buff_uid", new EvidenceText(uid)), ("owner_id", new EvidenceText(owner)), ("action_id", action), ("session_id", observation.Get("sessionId"))));
                var prior = record.ResistanceParameterSnapshots ??= [];
                var duplicates = prior.Where(row => EvidenceJson.PythonEquals(row.Get("operation_seq"), sequence)).ToArray();
                if (duplicates.Length == 0) prior.Add(saved);
                else if (duplicates.Any(row => !EvidenceJson.PythonEquals(row.Get("bb_values"), values)))
                    foreach (var duplicate in duplicates) duplicate.Set("status", new EvidenceText("conflicting_dynamic_operation"));
            }
        }
        catch (FormatException) { }
    }

    private static bool Truth(EvidenceValue value) => value switch
    {
        EvidenceNull => false, EvidenceBoolean flag => flag.Value, EvidenceText text => text.Value.Length > 0,
        EvidenceInteger number => !number.Value.IsZero, EvidenceReal number => number.Value != 0,
        EvidenceObject obj => obj.Fields.Count > 0, EvidenceArray array => array.Items.Count > 0, _ => false,
    };

    private static IReadOnlyList<TypedActionNode> Candidates(EvidenceValue root, EvidenceInteger action)
    {
        List<TypedActionNode> matches = [];
        Stack<(EvidenceValue Node, bool Enabled)> pending = new([(root, true)]);
        while (pending.TryPop(out var item))
        {
            if (item.Node is EvidenceObject obj)
            {
                var enabled = item.Enabled && (!obj.Fields.ContainsKey("serverActionIndex") || obj.Get("isEnable") is EvidenceBoolean { Value: true });
                if (EvidenceJson.PythonEquals(obj.Get("serverActionIndex"), action)) matches.Add(new(obj, enabled));
                foreach (var value in obj.Fields.Values) pending.Push((value, enabled));
            }
            else if (item.Node is EvidenceArray array) foreach (var value in array.Items) pending.Push((value, item.Enabled));
        }
        return matches;
    }
}
