using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Per-volume symbol definitions; never merges observations or infers bindings.</summary>
internal sealed class TraceReferences
{
    private readonly Dictionary<string, Dictionary<int, EvidenceText>> values = new() { ["entity"] = [], ["template"] = [] };
    private readonly Dictionary<string, Dictionary<string, int>> indices = new() { ["entity"] = new(StringComparer.Ordinal), ["template"] = new(StringComparer.Ordinal) };
    private static string? Kind(string key) => TraceModel.Identities.Contains(key) ? "entity" : key is "skill" or "template" or "weapon_template" ? "template" : null;

    public void Define(EvidenceObject definition)
    {
        if (definition.Get("kind") is not EvidenceText kind || !values.TryGetValue(kind.Value, out var table)
            || definition.Get("ref") is not EvidenceInteger reference || reference.Value != table.Count + 1
            || definition.Get(kind.Value == "entity" ? "id" : "template") is not EvidenceText { Value.Length: > 0 } text
            || indices[kind.Value].ContainsKey(text.Value)
            || kind.Value == "entity" && text.Value.Any(unit => unit is < '0' or > '9'))
            throw new InvalidDataException("Invalid or duplicate trace definition");
        var index = (int)reference.Value; table[index] = text; indices[kind.Value][text.Value] = index;
    }

    public EvidenceValue Encode(EvidenceValue value, Action<EvidenceObject> emit, string key = "")
    {
        if (TraceModel.OpaqueFields.Contains(key)) return value;
        if (Kind(key) is { } kind && value is EvidenceText { Value.Length: > 0 } text)
        {
            if (!indices[kind].TryGetValue(text.Value, out var reference))
            {
                reference = values[kind].Count + 1;
                EvidenceObject definition = new(new Dictionary<string, EvidenceValue>
                {
                    ["type"] = new EvidenceText("definition"), ["kind"] = new EvidenceText(kind), ["ref"] = new EvidenceInteger(reference),
                    [kind == "entity" ? "id" : "template"] = text,
                });
                Define(definition); emit(definition);
            }
            return new EvidenceObject(new Dictionary<string, EvidenceValue> { [kind + "_ref"] = new EvidenceInteger(reference) });
        }
        return value switch
        {
            EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => Encode(pair.Value, emit, pair.Key))),
            EvidenceArray array => new EvidenceArray(array.Items.Select(child => Encode(child, emit)).ToArray()),
            _ => value,
        };
    }

    public EvidenceValue Decode(EvidenceValue value, string key = "")
    {
        if (TraceModel.OpaqueFields.Contains(key)) return value;
        if (value is EvidenceObject obj)
        {
            if (Kind(key) is { } kind && obj.Fields.Count == 1 && obj.Fields.ContainsKey(kind + "_ref"))
            {
                if (obj.Get(kind + "_ref") is not EvidenceInteger reference || reference.Value < 1 || reference.Value > int.MaxValue
                    || !values[kind].TryGetValue((int)reference.Value, out var text)) throw new InvalidDataException("Undefined trace reference");
                return text;
            }
            Dictionary<string, EvidenceValue>? fields = null;
            foreach (var (name, child) in obj.Fields)
            {
                var decoded = Decode(child, name);
                if (!ReferenceEquals(decoded, child)) (fields ??= obj.Fields.ToDictionary())[name] = decoded;
            }
            return fields is null ? obj : FrozenEvidence.Capture(new EvidenceObject(fields));
        }
        if (value is EvidenceArray array)
        {
            EvidenceValue[]? children = null;
            for (var index = 0; index < array.Items.Count; index++)
            {
                var child = Decode(array.Items[index]);
                if (!ReferenceEquals(child, array.Items[index])) (children ??= array.Items.ToArray())[index] = child;
            }
            return children is null ? array : FrozenEvidence.Capture(new EvidenceArray(children));
        }
        return value;
    }
}
