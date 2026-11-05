using System.Collections;
using System.Collections.ObjectModel;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Read-only objects share ordered field indices within one bounded parsing context.</summary>
internal sealed class ResourceFieldPool
{
    private sealed class Shape(string[] names)
    {
        internal readonly ReadOnlyCollection<string> Names = Array.AsReadOnly(names);
        internal readonly Dictionary<string, int> Indices = names.Select((name, index) => (name, index))
            .ToDictionary(pair => pair.name, pair => pair.index, StringComparer.Ordinal);
    }
    private sealed class Fields(Shape shape, EvidenceValue[] values) : FrozenEvidence.FrozenFields, IDictionary<string, EvidenceValue>
    {
        public int Count => values.Length;
        public IEnumerable<string> Keys => shape.Names;
        public IEnumerable<EvidenceValue> Values { get { foreach (var value in values) yield return value; } }
        public EvidenceValue this[string key] => values[shape.Indices[key]];
        public bool ContainsKey(string key) => shape.Indices.ContainsKey(key);
        public bool TryGetValue(string key, out EvidenceValue value)
        {
            if (shape.Indices.TryGetValue(key, out var index)) { value = values[index]; return true; }
            value = null!; return false;
        }
        EvidenceValue IDictionary<string, EvidenceValue>.this[string key] { get => this[key]; set => throw new NotSupportedException(); }
        ICollection<string> IDictionary<string, EvidenceValue>.Keys => shape.Names;
        ICollection<EvidenceValue> IDictionary<string, EvidenceValue>.Values => Array.AsReadOnly(values);
        bool ICollection<KeyValuePair<string, EvidenceValue>>.IsReadOnly => true;
        void IDictionary<string, EvidenceValue>.Add(string key, EvidenceValue value) => throw new NotSupportedException();
        bool IDictionary<string, EvidenceValue>.Remove(string key) => throw new NotSupportedException();
        void ICollection<KeyValuePair<string, EvidenceValue>>.Add(KeyValuePair<string, EvidenceValue> item) => throw new NotSupportedException();
        void ICollection<KeyValuePair<string, EvidenceValue>>.Clear() => throw new NotSupportedException();
        bool ICollection<KeyValuePair<string, EvidenceValue>>.Remove(KeyValuePair<string, EvidenceValue> item) => throw new NotSupportedException();
        bool ICollection<KeyValuePair<string, EvidenceValue>>.Contains(KeyValuePair<string, EvidenceValue> item)
            => TryGetValue(item.Key, out var value) && EqualityComparer<EvidenceValue>.Default.Equals(value, item.Value);
        void ICollection<KeyValuePair<string, EvidenceValue>>.CopyTo(KeyValuePair<string, EvidenceValue>[] array, int index)
        {
            ArgumentNullException.ThrowIfNull(array);
            if (index < 0 || index > array.Length) throw new ArgumentOutOfRangeException(nameof(index));
            if (array.Length - index < Count) throw new ArgumentException("Insufficient destination space", nameof(array));
            foreach (var pair in this) array[index++] = pair;
        }
        public IEnumerator<KeyValuePair<string, EvidenceValue>> GetEnumerator()
        {
            for (var index = 0; index < values.Length; index++) yield return new(shape.Names[index], values[index]);
        }
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
    private sealed class WideFields(Dictionary<string, EvidenceValue> values) : ReadOnlyDictionary<string, EvidenceValue>(values), FrozenEvidence.FrozenFields;
    private readonly Dictionary<int, List<Shape>> shapes = [];
    private int count;

    internal void Clear() { shapes.Clear(); count = 0; }

    private Shape? FindShape(IReadOnlyDictionary<string, EvidenceValue> fields)
    {
        // Wide identifier maps seldom repeat; retain their ordinary read-only dictionary.
        if (fields.Count > 128) return null;
        HashCode hash = new(); foreach (var key in fields.Keys) hash.Add(key, StringComparer.Ordinal);
        var code = hash.ToHashCode();
        if (shapes.TryGetValue(code, out var candidates))
            foreach (var shape in candidates)
                if (shape.Names.Count == fields.Count && shape.Names.SequenceEqual(fields.Keys, StringComparer.Ordinal))
                    return shape;
        if (count >= 1024) return null;
        Shape created = new(fields.Keys.ToArray());
        if (candidates is null) shapes[code] = candidates = [];
        candidates.Add(created); count++;
        return created;
    }

    // The parser transfers ownership of its completed dictionary and immutable descendants.
    internal IReadOnlyDictionary<string, EvidenceValue> Store(Dictionary<string, EvidenceValue> fields)
        => FindShape(fields) is { } shape ? new Fields(shape, fields.Values.ToArray()) : new WideFields(fields);

    // Snapshot callers retain ownership: copy every value through their recursive capture boundary.
    internal IReadOnlyDictionary<string, EvidenceValue> Capture(IReadOnlyDictionary<string, EvidenceValue> fields,
        Func<EvidenceValue, EvidenceValue> capture)
        => FindShape(fields) is { } shape ? new Fields(shape, fields.Values.Select(capture).ToArray())
            : CaptureWide(fields, capture);

    private static WideFields CaptureWide(IReadOnlyDictionary<string, EvidenceValue> fields, Func<EvidenceValue, EvidenceValue> capture)
        => new(fields.ToDictionary(pair => pair.Key, pair => capture(pair.Value), StringComparer.Ordinal));
}
