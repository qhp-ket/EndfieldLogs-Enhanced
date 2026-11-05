using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Immutable tuple identity with Python numeric equality for packet guards.</summary>
public sealed class EffectSignature : IEquatable<EffectSignature>
{
    private readonly bool hashable;
    public EvidenceArray Parts { get; }
    internal EffectSignature(IEnumerable<EvidenceValue> values, bool hashable = true)
    {
        Parts = new(values.Select(BuffEvidence.Clone).ToArray());
        this.hashable = hashable;
    }
    public bool Equals(EffectSignature? other) => other is not null && EvidenceJson.PythonEquals(Parts, other.Parts);
    public override bool Equals(object? obj) => obj is EffectSignature signature && Equals(signature);
    public override int GetHashCode() => hashable ? Hash(Parts) : throw new InvalidCastException("Unhashable effect signature");
    private static int Hash(EvidenceValue value) => value switch
    {
        EvidenceArray array => array.Items.Aggregate(17, (hash, item) => unchecked(hash * 31 + Hash(item))),
        EvidenceInteger integer => ((double)integer.Value).GetHashCode(),
        EvidenceReal real => real.Value.GetHashCode(),
        EvidenceBoolean boolean => (boolean.Value ? 1.0 : 0.0).GetHashCode(),
        EvidenceText text => StringComparer.Ordinal.GetHashCode(text.Value),
        EvidenceNull => 0,
        _ => throw new InvalidCastException("Unhashable effect signature"),
    };
}

public static class EffectIdentity
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    public static IReadOnlySet<string> WindowUids(EvidenceObject window)
    {
        HashSet<string> aliases = new(StringComparer.Ordinal);
        var primary = Text(window.Get("uid"));
        if (primary.Length != 0) aliases.Add(primary);
        foreach (var alias in CatalogValues.Iterable(CatalogValues.Or(window.Get("uid_aliases"), new EvidenceArray([]))))
            if (Text(alias) is { Length: > 0 } text) aliases.Add(text);
        return aliases;
    }

    public static string Condition(EvidenceObject effect) => effect.Get("condition") is EvidenceObject condition
        ? PythonSortedJson.Serialize(condition) : "";

    internal static BigInteger Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceReal real when double.IsNaN(real.Value) => throw new FormatException("NaN integer"),
        EvidenceReal => throw new OverflowException("Infinite integer"),
        EvidenceText text when Regex.IsMatch(PythonDisplay.Strip(text.Value), @"\A[+-]?\d+(?:_\d+)*\z") =>
            TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid integer"),
        EvidenceText => throw new FormatException("Invalid integer"),
        _ => throw new InvalidCastException("Invalid integer evidence"),
    };

    internal static double Float(EvidenceValue value) => value switch
    {
        EvidenceReal real => real.Value,
        EvidenceInteger integer => PythonIntegerDivision.Divide(integer.Value, BigInteger.One),
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceText text => ParseFloat(text.Value),
        _ => throw new InvalidCastException("Invalid float evidence"),
    };

    private static double ParseFloat(string text)
    {
        if (!TraceFields.TryFloat(text, out var number)) throw new FormatException("Invalid float");
        if (double.IsNaN(number)) return BitConverter.UInt64BitsToDouble(PythonDisplay.Strip(text).StartsWith('-') ? 0xfff8000000000000UL : 0x7ff8000000000000UL);
        return number;
    }

    private static bool Scalar(EvidenceValue value) => value is not (EvidenceObject or EvidenceArray);
    private static EvidenceValue Element(EvidenceObject effect) => CatalogValues.Or(effect.Get("element"), new EvidenceText("all"));

    internal static int CompareKeys(EvidenceValue a, EvidenceValue b)
    {
        if (a is EvidenceText x && b is EvidenceText y) return PythonDisplay.CodePointComparer.Compare(x.Value, y.Value);
        if (a is EvidenceArray left && b is EvidenceArray right)
        {
            for (var index = 0; index < Math.Min(left.Items.Count, right.Items.Count); index++)
                if (!EvidenceJson.PythonEquals(left.Items[index], right.Items[index])) return CompareKeys(left.Items[index], right.Items[index]);
            return left.Items.Count.CompareTo(right.Items.Count);
        }
        if (a is EvidenceInteger or EvidenceReal or EvidenceBoolean && b is EvidenceInteger or EvidenceReal or EvidenceBoolean)
        {
            if (a is EvidenceReal { Value: var av } && b is EvidenceReal { Value: var bv }) return av < bv ? -1 : av > bv ? 1 : 0;
            static int IntegerReal(BigInteger integer, double real)
            {
                if (double.IsNaN(real)) return 0;
                if (double.IsInfinity(real)) return real > 0 ? -1 : 1;
                var comparison = integer.CompareTo(new BigInteger(real));
                return comparison != 0 || real == Math.Truncate(real) ? comparison : real > 0 ? -1 : 1;
            }
            if (a is EvidenceReal ar) return -IntegerReal(Integer(b), ar.Value);
            if (b is EvidenceReal br) return IntegerReal(Integer(a), br.Value);
            return Integer(a).CompareTo(Integer(b));
        }
        throw new InvalidCastException("Incomparable whitelist keys");
    }

    private static EvidenceArray Whitelist(EvidenceObject effect)
    {
        var items = CatalogValues.Iterable(CatalogValues.Or(effect.Get("rdps_whitelist_keys"), new EvidenceArray([]))).ToArray();
        for (var index = 1; index < items.Length; index++)
        {
            var item = items[index];
            var cursor = index;
            while (cursor > 0 && CompareKeys(item, items[cursor - 1]) < 0) { items[cursor] = items[cursor - 1]; cursor--; }
            items[cursor] = item;
        }
        return new(items);
    }

    public static EffectSignature Row(EvidenceObject effect)
    {
        EvidenceText Str(string key) => new(Text(effect.Get(key)));
        EvidenceReal Rate(string key) => new(PythonDecimalRounding.Round(Float(CatalogValues.Or(effect.Get(key), new EvidenceReal(0))), 6));
        List<EvidenceValue> parts = effect.Fields.ContainsKey("rate")
            ? [new EvidenceText("static"), Str("zone"), Element(effect), Rate("rate"), Str("bb_key"),
                effect.Get("attr_type") is EvidenceNull ? EvidenceNull.Value : new EvidenceInteger(Integer(effect.Get("attr_type")))]
            : [new EvidenceText("dynamic"), Str("zone"), Element(effect), Rate("base_rate"), Rate("tick_rate"), Rate("max_rate"),
                Rate("delayed_add_rate"), Rate("delay_sec"), Str("bb_key"), Str("add_bb_key"), Str("delay_bb_key")];
        parts.AddRange([new EvidenceText(Condition(effect)), effect.Get("recipient_side"), effect.Get("external_rdps_allowed"), Whitelist(effect)]);
        var hashable = Scalar(effect.Get("recipient_side")) && Scalar(effect.Get("external_rdps_allowed"))
            && Scalar(parts[2]) && ((EvidenceArray)parts[^1]).Items.All(Scalar);
        return new(parts, hashable);
    }

    public static EffectSignature PacketGuard(EvidenceObject effect)
    {
        var keys = new[] { "bb_key", "add_bb_key", "delay_bb_key", "tick_bb_key", "max_bb_key" }
            .Select(key => Text(effect.Get(key))).ToArray();
        BigInteger? attribute = null;
        try { if (effect.Get("attr_type") is not EvidenceNull) attribute = Integer(effect.Get("attr_type")); }
        catch (Exception error) when (error is FormatException or InvalidCastException) { }
        var condition = Condition(effect);
        if (keys.Any(key => key.Length > 0) || attribute is not null || condition.Length > 0)
            return new([new EvidenceText("keyed"), new EvidenceText(Text(effect.Get("zone"))), Element(effect),
                new EvidenceArray(keys.Select(key => (EvidenceValue)new EvidenceText(key)).ToArray()),
                attribute is null ? EvidenceNull.Value : new EvidenceInteger(attribute.Value), new EvidenceText(condition)], Scalar(Element(effect)));
        return Row(effect);
    }
}
