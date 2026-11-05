using System.Collections;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Typed event boundary and insertion-ordered Python trace JSON, separate from transport projection.</summary>
internal static partial class TraceData
{
    internal static EvidenceValue Value(object? value) => value switch
    {
        null => EvidenceNull.Value,
        EvidenceValue item => EvidenceJson.Clone(item),
        string text => new EvidenceText(text),
        bool flag => new EvidenceBoolean(flag),
        BigInteger integer => new EvidenceInteger(integer),
        byte or sbyte or short or ushort or int or uint or long or ulong =>
            new EvidenceInteger(BigInteger.Parse(Convert.ToString(value, CultureInfo.InvariantCulture)!, CultureInfo.InvariantCulture)),
        double real => new EvidenceReal(real),
        float real => new EvidenceReal(real),
        IReadOnlyDictionary<string, object?> map => new EvidenceObject(map.ToDictionary(pair => pair.Key, pair => Value(pair.Value), StringComparer.Ordinal)),
        IDictionary map => new EvidenceObject(map.Cast<DictionaryEntry>().ToDictionary(pair => Convert.ToString(pair.Key, CultureInfo.InvariantCulture)!, pair => Value(pair.Value), StringComparer.Ordinal)),
        IEnumerable items => new EvidenceArray(items.Cast<object?>().Select(Value).ToArray()),
        _ => throw new InvalidDataException("Unsupported decoded trace value: " + value.GetType().Name),
    };

    internal static EvidenceObject Obj(EvidenceValue? value) => value as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>());
    internal static IEnumerable<EvidenceValue> Items(EvidenceValue value) => value is EvidenceArray array ? array.Items : [];
    internal static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => Items(value).OfType<EvidenceObject>();
    internal static EvidenceObject Make(params (string Key, object? Value)[] pairs) => new(pairs.ToDictionary(pair => pair.Key, pair => Value(pair.Value), StringComparer.Ordinal));
    internal static bool Truth(EvidenceValue value) => value switch
    {
        EvidenceNull => false, EvidenceBoolean flag => flag.Value, EvidenceInteger integer => !integer.Value.IsZero,
        EvidenceReal real => real.Value != 0, EvidenceText text => text.Value.Length > 0,
        EvidenceArray array => array.Items.Count > 0, EvidenceObject obj => obj.Fields.Count > 0, _ => true,
    };
    internal static string S(EvidenceValue value) => PythonDisplay.String(value);
    internal static string Text(EvidenceValue value, string fallback = "") => Truth(value) ? S(value) : fallback;
    internal static string Present(EvidenceValue value, string fallback = "unknown") => value is EvidenceNull ? fallback : S(value);
    internal static BigInteger? Int(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text when BigInteger.TryParse(text.Value.Trim(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var number) => number,
        _ => null,
    };
    internal static BigInteger? Id(EvidenceValue value) => Int(value) is { IsZero: false } id ? id : null;
    internal static double? Float(EvidenceValue value) => value switch
    {
        EvidenceReal real => real.Value, EvidenceInteger integer => (double)integer.Value,
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceText text when double.TryParse(text.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out var real) => real,
        _ => null,
    };
    internal static string I(BigInteger? value, string fallback = "unknown") => value?.ToString(CultureInfo.InvariantCulture) ?? fallback;
    internal static string General(double? value, int digits = 6)
    {
        if (value is null) return "unknown";
        if (!double.IsFinite(value.Value)) return PythonDisplay.Float(value.Value);
        return Exponent().Replace(value.Value.ToString("g" + digits, CultureInfo.InvariantCulture), "$1");
    }
    [GeneratedRegex(@"(e[+-])0(?=\d{2})")]
    private static partial Regex Exponent();
    internal static string Fixed(double value, int digits) => double.IsFinite(value)
        ? value.ToString("F" + digits, CultureInfo.InvariantCulture) : PythonDisplay.Float(value);
    internal static bool Digits(string text) => text.Length > 0 && text.All(char.IsDigit);
    internal static string? Character(string? text)
    {
        var parts = (text ?? "").Split('_');
        return parts.Length >= 3 && parts[0] == "chr" && Digits(parts[1]) ? string.Join('_', parts[..3]) : null;
    }
    internal static string? Template(EvidenceValue value)
    {
        if (value is EvidenceText { Value.Length: > 0 } text) return text.Value;
        if (value is not EvidenceObject obj) return null;
        if (obj.Get("str_id") is EvidenceText { Value.Length: > 0 } key) return key.Value;
        return Id(obj.Get("int_id")) is { } id ? Text(obj.Get("type"), "template").ToLowerInvariant() + "_" + I(id) : null;
    }
    internal static Dictionary<string, double> Blackboard(EvidenceValue value)
    {
        Dictionary<string, double> result = new(StringComparer.Ordinal);
        foreach (var (key, raw) in Obj(Obj(value).Get("blackboard")).Fields)
        {
            if (raw is not EvidenceObject entry) continue;
            var number = Float(entry.Get("float_value")) ?? Float(entry.Get("numeric_value")) ?? Float(entry.Get("value"));
            if (number is not null) result[key] = number.Value;
        }
        return result;
    }
    internal static string Json(EvidenceValue value, bool ascii = false, bool finite = false) => value switch
    {
        EvidenceObject obj => "{" + string.Join(',', obj.Fields.Select(pair => Quote(pair.Key, ascii) + ":" + Json(pair.Value, ascii, finite))) + "}",
        EvidenceArray array => "[" + string.Join(',', array.Items.Select(item => Json(item, ascii, finite))) + "]",
        EvidenceText text => Quote(text.Value, ascii),
        EvidenceReal real when finite && !double.IsFinite(real.Value) => throw new InvalidDataException("Non-finite number in canonical trace JSON"),
        _ => PythonSortedJson.Serialize(value, compact: true),
    };
    internal static string Quote(string text, bool ascii = false)
    {
        var quoted = PythonSortedJson.Serialize(new EvidenceText(text));
        if (!ascii) return quoted;
        StringBuilder result = new();
        foreach (var unit in quoted) result.Append(unit >= 127 ? "\\u" + ((int)unit).ToString("x4", CultureInfo.InvariantCulture) : unit.ToString());
        return result.ToString();
    }
}
