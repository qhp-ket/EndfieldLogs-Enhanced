using System.Globalization;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Text;

namespace EndfieldLogs.Core.Compatibility;

public abstract record EvidenceValue;
public sealed record EvidenceNull : EvidenceValue
{
    public static EvidenceNull Value { get; } = new();
}
public sealed record EvidenceBoolean(bool Value) : EvidenceValue;
public sealed record EvidenceInteger(BigInteger Value) : EvidenceValue;
public sealed record EvidenceReal(double Value) : EvidenceValue;
public sealed record EvidenceText(string Value) : EvidenceValue;
public sealed record EvidenceArray(IReadOnlyList<EvidenceValue> Items) : EvidenceValue;
public sealed record EvidenceObject(IReadOnlyDictionary<string, EvidenceValue> Fields) : EvidenceValue
{
    public IReadOnlyList<KeyValuePair<string, EvidenceValue>>? SourcePairs { get; init; }
    public EvidenceValue Get(string key) => Fields.GetValueOrDefault(key) ?? EvidenceNull.Value;
}

/// <summary>Trace JSON boundary: exact integers, duplicate last-wins keys and existing named float constants.</summary>
public static class EvidenceJson
{
    public static EvidenceValue Parse(string text) => new Reader<TextSource>(new(text)).ReadDocument();
    public static EvidenceValue ParseWithPairs(string text) => new Reader<TextSource>(new(text), true).ReadDocument();
    public static EvidenceValue ParseReadOnly(string text) => new Reader<TextSource>(new(text), readOnly: true).ReadDocument();

    /// <summary>Transfer exclusive ownership of all mutable containers into a recursively read-only snapshot.
    /// The caller must abandon the input and every mutable descendant; use Clone first when ownership is shared.</summary>
    public static EvidenceValue TakeReadOnlyOwnership(EvidenceValue value) => FrozenEvidence.TakeOwnership(value);

    private static readonly UTF8Encoding StrictResourceUtf8 = new(false, true);
    internal static EvidenceValue ParseReadOnlyUtf8(ReadOnlyMemory<byte> bytes, bool surrogatePass = false)
    {
        // Validate the whole document before parsing, as the text loader does. Rare
        // encoded surrogate code points retain the existing Python-compatible decoder.
        try { StrictResourceUtf8.GetCharCount(bytes.Span); }
        catch (DecoderFallbackException) when (surrogatePass)
        {
            return ParseReadOnly(JsonByteEncoding.DecodeUtf8(bytes.Span));
        }
        return new Reader<Utf8Source>(new(bytes), readOnly: true).ReadDocument();
    }

    private interface JsonSource
    {
        int Length { get; }
        char this[int index] { get; }
        bool HasBom { get; }
        string Slice(int start, int end);
        bool Matches(int index, string literal);
        bool TryHex(int index, out ushort value);
    }
    private readonly struct TextSource(string text) : JsonSource
    {
        public int Length => text.Length;
        public char this[int index] => text[index];
        public bool HasBom => text.StartsWith('\ufeff');
        public string Slice(int start, int end) => text[start..end];
        public bool Matches(int index, string literal) => text.AsSpan(index).StartsWith(literal, StringComparison.Ordinal);
        public bool TryHex(int index, out ushort value) => ushort.TryParse(text.AsSpan(index, 4),
            NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out value);
    }
    private readonly struct Utf8Source(ReadOnlyMemory<byte> bytes) : JsonSource
    {
        public int Length => bytes.Length;
        public char this[int index] => (char)bytes.Span[index];
        public bool HasBom => bytes.Span.StartsWith("\ufeff"u8);
        public string Slice(int start, int end) => StrictResourceUtf8.GetString(bytes.Span[start..end]);
        public bool TryHex(int index, out ushort value) => ushort.TryParse(bytes.Span.Slice(index, 4),
            NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out value);
        public bool Matches(int index, string literal)
        {
            if (literal.Length > bytes.Length - index) return false;
            var remaining = bytes.Span[index..];
            for (var offset = 0; offset < literal.Length; offset++)
                if (remaining[offset] != literal[offset]) return false;
            return true;
        }
    }

    // Immutable constants only: fixed capacity, no resource IDs or session history retained.
    private static readonly EvidenceInteger[] SmallIntegers = Enumerable.Range(-1, 257).Select(value => new EvidenceInteger(value)).ToArray();
    private static readonly EvidenceReal PositiveZero = new(0.0), NegativeZero = new(-0.0), One = new(1.0);
    private static readonly (string Text, EvidenceValue Value)[] Literals =
    [ ("null",EvidenceNull.Value), ("true",new EvidenceBoolean(true)), ("false",new EvidenceBoolean(false)),
      ("NaN",new EvidenceReal(BitConverter.UInt64BitsToDouble(0x7ff8000000000000))), ("Infinity",new EvidenceReal(double.PositiveInfinity)),
      ("-Infinity",new EvidenceReal(double.NegativeInfinity)) ];

    // Python container equality treats the shared named NaN literal by identity.
    internal static EvidenceValue ResourceNaN => Literals[3].Value;

    // One serial reader may share bounded immutable field shapes and short scalar strings.
    // Neither cache retains parsed object/array values or an event history.
    internal sealed class ReadOnlyContext
    {
        internal readonly Dictionary<string, EvidenceText> Strings = new(StringComparer.Ordinal);
        internal readonly ResourceFieldPool Fields = new();
        internal EvidenceValue Parse(string text) => new Reader<TextSource>(new(text), readOnly: true, context: this).ReadDocument();
        internal void Clear() { Strings.Clear(); Fields.Clear(); }
    }

    public static EvidenceValue Clone(EvidenceValue value) => value switch
    {
        EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => Clone(pair.Value), StringComparer.Ordinal))
        {
            SourcePairs = obj.SourcePairs?.Select(pair => new KeyValuePair<string, EvidenceValue>(pair.Key, Clone(pair.Value))).ToArray(),
        },
        EvidenceArray array => new EvidenceArray(array.Items.Select(Clone).ToArray()),
        _ => value,
    };

    public static bool PythonEquals(EvidenceValue left, EvidenceValue right)
    {
        if (left is EvidenceObject a && right is EvidenceObject b)
            return a.Fields.Count == b.Fields.Count && a.Fields.All(pair => b.Fields.TryGetValue(pair.Key, out var other) && ContainerValueEquals(pair.Value, other));
        if (left is EvidenceArray listA && right is EvidenceArray listB)
            return listA.Items.Count == listB.Items.Count && listA.Items.Zip(listB.Items).All(pair => ContainerValueEquals(pair.First, pair.Second));
        if (left is EvidenceText textA && right is EvidenceText textB) return textA.Value == textB.Value;
        if (left is EvidenceNull || right is EvidenceNull) return left is EvidenceNull && right is EvidenceNull;
        if (left is EvidenceReal realA && right is EvidenceReal realB) return realA.Value == realB.Value;
        static BigInteger? Integer(EvidenceValue value) => value switch
        {
            EvidenceInteger integer => integer.Value,
            EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
            EvidenceReal real when double.IsFinite(real.Value) && Math.Truncate(real.Value) == real.Value => new BigInteger(real.Value),
            _ => null,
        };
        var intA = Integer(left);
        return intA is not null && Integer(right) is BigInteger intB && intA.Value == intB;
    }

    private static bool ContainerValueEquals(EvidenceValue left, EvidenceValue right) => ReferenceEquals(left,right) || PythonEquals(left,right);

    private sealed class Reader<TSource>(TSource text, bool preservePairs = false, bool readOnly = false, ReadOnlyContext? context = null)
        where TSource : struct, JsonSource
    {
        private int index;
        private readonly Dictionary<string, EvidenceText>? strings = readOnly ? context?.Strings ?? new(StringComparer.Ordinal) : null;
        private readonly ResourceFieldPool? fieldPool = readOnly ? context?.Fields ?? new() : null;
        private string ResourceString(string value)
        {
            if (strings is null || value.Length > 96) return value;
            if (strings.TryGetValue(value, out var saved)) return saved.Value;
            if (strings.Count < 8192) strings[value] = new(value);
            return value;
        }
        private FormatException Invalid(string reason = "Expecting value", int? position = null)
        {
            var offset = Math.Clamp(position ?? index, 0, text.Length);
            var prefix = text.Slice(0, offset);
            var lastLine = prefix.LastIndexOf('\n');
            var line = prefix.Count(value => value == '\n') + 1;
            var character = prefix.EnumerateRunes().Count();
            var column = prefix[(lastLine + 1)..].EnumerateRunes().Count() + 1;
            return new($"{reason}: line {line} column {column} (char {character})");
        }
        private void WhiteSpace()
        {
            while (index < text.Length && text[index] is ' ' or '\t' or '\r' or '\n') index++;
        }
        private bool Take(char token)
        {
            WhiteSpace();
            if (index >= text.Length || text[index] != token) return false;
            index++;
            return true;
        }
        public EvidenceValue ReadDocument()
        {
            if (text.HasBom) throw Invalid("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0);
            var result = Read(0);
            WhiteSpace();
            if (index != text.Length) throw Invalid("Extra data");
            return result;
        }
        [MethodImpl(MethodImplOptions.AggressiveOptimization)]
        private EvidenceValue Read(int depth)
        {
            if (depth > 1000) throw Invalid();
            WhiteSpace();
            if (index >= text.Length) throw Invalid();
            if (text[index] == '"')
            {
                var value = String();
                return strings is not null && strings.TryGetValue(value, out var saved) ? saved : new EvidenceText(value);
            }
            if (Take('{'))
            {
                Dictionary<string, EvidenceValue> fields = new(StringComparer.Ordinal);
                List<KeyValuePair<string, EvidenceValue>>? pairs = preservePairs ? [] : null;
                EvidenceObject Object() => new(fieldPool?.Store(fields) ?? fields) { SourcePairs = pairs };
                if (Take('}')) return Object();
                var comma = -1;
                while (true)
                {
                    WhiteSpace();
                    if (index >= text.Length || text[index] != '"')
                        throw comma >= 0 && index < text.Length && text[index] == '}'
                            ? Invalid("Illegal trailing comma before end of object", comma)
                            : Invalid("Expecting property name enclosed in double quotes");
                    var key = String();
                    if (!Take(':')) throw Invalid("Expecting ':' delimiter");
                    var value = Read(depth+1);
                    pairs?.Add(new(key, value));
                    fields[key] = value;
                    if (Take('}')) return Object();
                    if (!Take(',')) throw Invalid("Expecting ',' delimiter");
                    comma = index - 1;
                }
            }
            if (Take('['))
            {
                List<EvidenceValue> items = [];
                EvidenceArray Array() => readOnly ? FrozenEvidence.OwnParsedArray(items) : new(items);
                if (Take(']')) return Array();
                var comma = -1;
                while (true)
                {
                    WhiteSpace();
                    if (comma >= 0 && index < text.Length && text[index] == ']')
                        throw Invalid("Illegal trailing comma before end of array", comma);
                    items.Add(Read(depth+1));
                    if (Take(']')) return Array();
                    if (!Take(',')) throw Invalid("Expecting ',' delimiter");
                    comma = index - 1;
                }
            }
            foreach (var (literal, value) in Literals)
                if (text.Matches(index, literal))
                {
                    index += literal.Length;
                    return value;
                }
            var start = index;
            if (text[index] == '-') index++;
            if (index >= text.Length || text[index] is < '0' or > '9') throw Invalid(position: start);
            if (text[index++] != '0') while (index < text.Length && text[index] is >= '0' and <= '9') index++;
            var real = false;
            if (index < text.Length && text[index] == '.')
            {
                var point = index;
                index++;
                var fraction = index;
                while (index < text.Length && text[index] is >= '0' and <= '9') index++;
                if (index == fraction) index = point;
                else real = true;
            }
            if (index < text.Length && text[index] is 'e' or 'E')
            {
                var exponentMarker = index;
                index++;
                if (index < text.Length && text[index] is '+' or '-') index++;
                var exponent = index;
                while (index < text.Length && text[index] is >= '0' and <= '9') index++;
                if (index == exponent) index = exponentMarker;
                else real = true;
            }
            var number = text.Slice(start, index);
            if (real)
            {
                var value = double.Parse(number, NumberStyles.Float, CultureInfo.InvariantCulture);
                if (readOnly)
                {
                    if (value == 0) return BitConverter.DoubleToInt64Bits(value) < 0 ? NegativeZero : PositiveZero;
                    if (value == 1) return One;
                }
                return new EvidenceReal(value);
            }
            var integer = BigInteger.Parse(number, CultureInfo.InvariantCulture);
            return readOnly && integer >= -1 && integer <= 255 ? SmallIntegers[(int)integer + 1] : new EvidenceInteger(integer);
        }

        [MethodImpl(MethodImplOptions.AggressiveOptimization)]
        private string String()
        {
            var start = index;
            if (index >= text.Length || text[index++] != '"') throw Invalid("Expecting property name enclosed in double quotes", start);
            var content = index;
            StringBuilder? value = null;
            while (index < text.Length)
            {
                var token = text[index++];
                if (token == '"')
                {
                    var plain = text.Slice(content, index - 1);
                    return ResourceString(value is null ? plain : value.Append(plain).ToString());
                }
                if (token < 32) throw Invalid("Invalid control character at", index - 1);
                if (token != '\\') continue;
                value ??= new();
                value.Append(text.Slice(content, index - 1));
                if (index >= text.Length) throw Invalid("Unterminated string starting at", start);
                token = text[index++];
                if (token == 'u')
                {
                    if (index+4 > text.Length || !text.TryHex(index, out var escaped))
                        throw Invalid("Invalid \\uXXXX escape", index - 1);
                    value.Append((char)escaped);
                    index += 4;
                }
                else value.Append(token switch
                {
                    '"' or '\\' or '/' => token, 'b' => '\b', 'f' => '\f', 'n' => '\n', 'r' => '\r', 't' => '\t',
                    _ => throw Invalid("Invalid \\escape", index - 2),
                });
                content = index;
            }
            throw Invalid("Unterminated string starting at", start);
        }
    }
}
