using System.Collections.ObjectModel;
using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Private immutable snapshots. Mutable report roots may share their protected descendants.</summary>
internal static class FrozenEvidence
{
    // Implemented only by containers that own recursively immutable evidence.
    internal interface FrozenFields : IReadOnlyDictionary<string, EvidenceValue> { }
    private sealed class Fields(Dictionary<string, EvidenceValue> values) : ReadOnlyDictionary<string, EvidenceValue>(values), FrozenFields;
    private sealed class OverlayFields(FrozenFields source, FrozenFields patch) : FrozenFields
    {
        public int Count { get; } = source.Count + patch.Keys.Count(key => !source.ContainsKey(key));
        public EvidenceValue this[string key] => TryGetValue(key, out var value) ? value : throw new KeyNotFoundException(key);
        public IEnumerable<string> Keys => this.Select(pair => pair.Key);
        public IEnumerable<EvidenceValue> Values => this.Select(pair => pair.Value);
        public bool ContainsKey(string key) => patch.ContainsKey(key) || source.ContainsKey(key);
        public bool TryGetValue(string key, out EvidenceValue value) => patch.TryGetValue(key, out value!) || source.TryGetValue(key, out value!);
        public IEnumerator<KeyValuePair<string, EvidenceValue>> GetEnumerator()
        {
            foreach (var pair in source) yield return new(pair.Key, patch.GetValueOrDefault(pair.Key, pair.Value));
            foreach (var pair in patch) if (!source.ContainsKey(pair.Key)) yield return pair;
        }
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }
    private sealed class Items(EvidenceValue[] values) : ReadOnlyCollection<EvidenceValue>(values);
    private sealed class Pairs(KeyValuePair<string, EvidenceValue>[] values) : ReadOnlyCollection<KeyValuePair<string, EvidenceValue>>(values);
    private sealed class Numbers(Dictionary<BigInteger, EvidenceValue> values) : ReadOnlyDictionary<BigInteger, EvidenceValue>(values);
    private static readonly EvidenceArray EmptyArray = new(new Items([]));
    private static readonly Numbers EmptyNumbers = new([]);

    // Cache-local field metadata is bounded; values remain owned by individual immutable snapshots.
    internal sealed class Context
    {
        internal readonly ResourceFieldPool Fields = new();
        internal readonly Func<EvidenceValue, EvidenceValue> CaptureValue;
        internal Context() => CaptureValue = Capture;
        internal EvidenceValue Capture(EvidenceValue value) => CaptureCore(value, this);
        internal void Clear() => Fields.Clear();
    }

    internal static bool IsFrozenNumbers(IReadOnlyDictionary<BigInteger, EvidenceValue> values) => values is Numbers;

    internal static IReadOnlyDictionary<BigInteger, EvidenceValue> CaptureNumbers(IReadOnlyDictionary<BigInteger, EvidenceValue> values)
        => values is Numbers ? values : values.Count == 0 ? EmptyNumbers
            : new Numbers(values.ToDictionary(pair => pair.Key, pair => Capture(pair.Value)));

    internal static EvidenceValue Capture(EvidenceValue value) => CaptureCore(value, null);

    // The caller relinquishes every mutable descendant. Existing protected values
    // stay shared; owned dictionaries and arrays need wrappers, not another copy.
    internal static EvidenceValue TakeOwnership(EvidenceValue value) => value switch
    {
        EvidenceObject row when IsFrozenRoot(row) => value,
        EvidenceArray { Items: Items } => value,
        EvidenceObject row => OwnObject(row),
        EvidenceArray rows => OwnArray(rows),
        _ => value,
    };

    private static EvidenceObject OwnObject(EvidenceObject row)
    {
        var fields = row.Fields as Dictionary<string, EvidenceValue> ?? row.Fields.ToDictionary();
        foreach (var (key, value) in fields) fields[key] = TakeOwnership(value);
        return new(new Fields(fields))
        {
            SourcePairs = row.SourcePairs is null ? null : CapturePairs(row.SourcePairs, TakeOwnership),
        };
    }

    private static EvidenceArray OwnArray(EvidenceArray rows)
    {
        if (rows.Items.Count == 0) return EmptyArray;
        var values = rows.Items as EvidenceValue[] ?? rows.Items.ToArray();
        for (var index = 0; index < values.Length; index++) values[index] = TakeOwnership(values[index]);
        return new(new Items(values));
    }

    private static EvidenceValue CaptureCore(EvidenceValue value, Context? context) => value switch
    {
        EvidenceObject row when IsFrozenRoot(row) => value,
        EvidenceArray { Items: Items } => value,
        EvidenceObject row => CaptureObject(row, context),
        EvidenceArray rows => rows.Items.Count == 0 ? EmptyArray
            : new EvidenceArray(new Items(rows.Items.Select(context?.CaptureValue ?? Capture).ToArray())),
        _ => value,
    };

    private static EvidenceObject CaptureObject(EvidenceObject row, Context? context)
    {
        Func<EvidenceValue, EvidenceValue> capture = context?.CaptureValue ?? Capture;
        return new(context is null ? CaptureFields(row.Fields, capture) : context.Fields.Capture(row.Fields, capture))
        {
            SourcePairs = row.SourcePairs is null ? null : CapturePairs(row.SourcePairs, capture),
        };
    }

    private static Fields CaptureFields(IReadOnlyDictionary<string, EvidenceValue> fields, Func<EvidenceValue, EvidenceValue> capture)
        => new(fields.ToDictionary(pair => pair.Key, pair => capture(pair.Value), StringComparer.Ordinal));

    private static Pairs CapturePairs(IReadOnlyList<KeyValuePair<string, EvidenceValue>> pairs, Func<EvidenceValue, EvidenceValue> capture)
        => new(pairs.Select(pair => new KeyValuePair<string, EvidenceValue>(pair.Key, capture(pair.Value))).ToArray());

    // The parser transfers its own recursively read-only containers through this same boundary.
    internal static EvidenceArray OwnParsedArray(List<EvidenceValue> values) => values.Count == 0 ? EmptyArray : new(new Items(values.ToArray()));

    internal static bool IsFrozenRoot(EvidenceObject value) => value.Fields is FrozenFields && value.SourcePairs is null or Pairs;

    // Both operands were recursively captured. The view preserves dictionary replacement/insertion order.
    internal static EvidenceObject MergeRoot(EvidenceObject source, EvidenceObject patch)
        => IsFrozenRoot(source) && IsFrozenRoot(patch) && source.Fields is FrozenFields a && patch.Fields is FrozenFields b
            ? new(new OverlayFields(a, b)) { SourcePairs = source.SourcePairs }
            : throw new InvalidOperationException("Expected immutable evidence roots");

    internal static EvidenceObject MutableRoot(EvidenceObject value) => IsFrozenRoot(value)
        ? new(new Dictionary<string, EvidenceValue>(value.Fields, StringComparer.Ordinal)) { SourcePairs = value.SourcePairs }
        : throw new InvalidOperationException("Expected an immutable evidence snapshot");

    internal static EvidenceObject OwnedMutableRoot(EvidenceObject value) => IsFrozenRoot(value) ? MutableRoot(value) : value;

    // Private report copies may retain protected descendants. Public copies still use EvidenceJson.Clone.
    internal static EvidenceValue CopyOwned(EvidenceValue value) => value switch
    {
        EvidenceObject row when IsFrozenRoot(row) => value,
        EvidenceArray { Items: Items } => value,
        EvidenceObject row => new EvidenceObject(row.Fields.ToDictionary(pair => pair.Key,
            pair => CopyOwned(pair.Value), StringComparer.Ordinal))
        {
            SourcePairs = row.SourcePairs?.Select(pair => new KeyValuePair<string, EvidenceValue>(pair.Key, CopyOwned(pair.Value))).ToArray(),
        },
        EvidenceArray rows => new EvidenceArray(rows.Items.Select(CopyOwned).ToArray()),
        _ => value,
    };
}
