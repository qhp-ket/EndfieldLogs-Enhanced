using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

internal static class BuffAttributeParameters
{
    public static BuffObservation Build(BuffInstanceState state, BoundDynamicIdentity bound, EvidenceObject root,
        BuffDynamicState pending, int lineNumber, long timestampMs)
    {
        if (root.Get("attributeModifier") is not EvidenceObject attributeRoot || attributeRoot.Get("attributeModifiers") is not EvidenceArray attributes)
            throw new FormatException("missing_current_attribute_modifiers");
        List<EvidenceValue> parameters = [];
        HashSet<string> missing = new(StringComparer.Ordinal), unverified = new(StringComparer.Ordinal);
        for (var index = 0; index < attributes.Items.Count; index++)
        {
            if (attributes.Items[index] is not EvidenceObject modifier) throw new FormatException("invalid_current_attribute_modifier");
            var param = modifier.Get("param") as EvidenceObject;
            var key = param?.Get("useBlackboardKey") is EvidenceBoolean { Value: true } ? param.Get("blackboardKey") : EvidenceNull.Value;
            var name = BuffEvidence.String(key);
            var operand = key is not EvidenceNull ? name is not null && pending.Values.TryGetValue(name, out var value) ? value : (double?)null
                : param is null ? null : BuffEvidence.OptionalFloat(param.Get("value"));
            var source = key is not EvidenceNull ? name is not null && pending.ValueSources.TryGetValue(name, out var savedSource) ? savedSource
                : BuffEvidence.Object(("kind", new EvidenceText("unknown"))) : BuffEvidence.Object(("kind", new EvidenceText("typed_static_literal")));
            if (source is EvidenceObject sourceFields && sourceFields.Get("kind") is EvidenceText { Value: "creation_observation" }
                && sourceFields.Get("creation_key") is EvidenceArray { Items.Count: 5 } creation)
            {
                var fields = creation.Items;
                var creationKey = new BuffCreationKey(new(((EvidenceText)fields[0]).Value, ((EvidenceText)fields[1]).Value, fields[2]), ((EvidenceInteger)fields[3]).Value, ((EvidenceText)fields[4]).Value);
                var sourceAnchor = state.CreationHistory.GetValueOrDefault(creationKey)?.Observation;
                source = new EvidenceObject(new Dictionary<string, EvidenceValue>(sourceFields.Fields, StringComparer.Ordinal)
                {
                    ["kind"] = sourceAnchor?.Get("bb_observation_source") is EvidenceText kind ? kind : new EvidenceText("unverified_creation_bb"),
                });
            }
            var label = string.IsNullOrEmpty(name) ? $"attribute:{index}" : name;
            if (operand is null || name is not null && pending.InvalidKeys.Contains(name) || pending.InvalidKeys.Contains("*")) missing.Add(label);
            else if (source is not EvidenceObject src || src.Get("kind") is not EvidenceText { Value: "typed_runtime_post_assignment" or "typed_post_create_runtime_bb" or "typed_static_literal" }) unverified.Add(label);
            parameters.Add(BuffEvidence.Object(("index", new EvidenceInteger(index)), ("attribute_type", modifier.Get("attributeType")),
                ("formula", modifier.Get("formulaItem")), ("bb_key", key), ("operand", operand is double number ? new EvidenceReal(number) : EvidenceNull.Value), ("operand_source", source)));
        }
        EvidenceArray Names(IEnumerable<string> values) => new(values.Order(StringComparer.Ordinal).Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
        return new(BuffEvidence.Object(("ts_ms", new EvidenceInteger(timestampMs)), ("line_no", new EvidenceInteger(lineNumber)),
            ("operation_seq", new EvidenceInteger(bound.Sequence)), ("identity", BuffEvidence.Clone(bound.Payload)), ("bb_values", BuffEvidence.Blackboard(pending.Values)),
            ("attribute_parameters", new EvidenceArray(parameters)), ("missing_parameters", Names(missing)), ("unverified_parameters", Names(unverified)),
            ("status", new EvidenceText(missing.Count > 0 ? "missing_attribute_parameters" : unverified.Count > 0 ? "unverified_attribute_parameters" : "attribute_parameters_observed")),
            ("enhance_multiplier", EvidenceNull.Value), ("final_modifiers_verified", new EvidenceBoolean(false)), ("instance_start_line_no", new EvidenceInteger(bound.Record.InstanceStartLineNumber))));
    }
}
