using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Configuration;

internal static class SettingsData
{
    internal static EvidenceObject Empty() => new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal));
    internal static EvidenceObject Object(EvidenceValue value) => value is EvidenceObject map ? (EvidenceObject)EvidenceJson.Clone(map) : Empty();
    internal static EvidenceObject Make(params (string Key, object? Value)[] pairs) => TraceData.Make(pairs);
    internal static EvidenceValue Value(object? value) => TraceData.Value(value);
    internal static string String(EvidenceValue value) => PythonDisplay.String(value);
    internal static string Or(EvidenceValue value, string fallback) => TraceData.Text(value, fallback);
    internal static bool Truth(EvidenceValue value) => TraceData.Truth(value);
    internal static bool IsTrue(EvidenceValue value) => value is EvidenceBoolean { Value: true };
    internal static EvidenceValue Get(EvidenceObject map, string key, object? fallback) => map.Fields.GetValueOrDefault(key) ?? Value(fallback);
    internal static BigInteger? Integer(EvidenceValue value, bool allowBoolean = false)
    {
        if (value is EvidenceBoolean && !allowBoolean) return null;
        if (value is EvidenceText text)
        {
            // Python int accepts digit separators and Unicode decimal digits, but never decimal text.
            var raw = text.Value.Trim();
            if (raw.Length == 0) return null;
            System.Text.StringBuilder normalized = new();
            for (var index = 0; index < raw.Length; index++)
            {
                var token = raw[index];
                if (index == 0 && token is '+' or '-') { normalized.Append(token); continue; }
                if (token == '_' && index > 0 && index + 1 < raw.Length && char.IsDigit(raw[index - 1]) && char.IsDigit(raw[index + 1])) continue;
                if (char.GetUnicodeCategory(token) != UnicodeCategory.DecimalDigitNumber) return null;
                normalized.Append((int)char.GetNumericValue(token));
            }
            return BigInteger.TryParse(normalized.ToString(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var integer) ? integer : null;
        }
        return TraceData.Int(value);
    }
    internal static int Int(EvidenceValue value, int fallback, int min = int.MinValue, int max = int.MaxValue, bool allowBoolean = false)
    {
        var integer = Integer(value, allowBoolean);
        return integer is null ? fallback : (int)BigInteger.Clamp(integer.Value, min, max);
    }
    internal static double Number(EvidenceValue value, double fallback)
    {
        if (value is EvidenceBoolean) return fallback;
        var real = TraceData.Float(value);
        return real is not null && double.IsFinite(real.Value) ? real.Value : fallback;
    }
    internal static string? PathValue(EvidenceValue value, string workingDirectory)
    {
        if (value is not EvidenceText text || string.IsNullOrWhiteSpace(text.Value) || text.Value.Contains('\0')) return null;
        try { return Path.GetFullPath(text.Value, workingDirectory); }
        catch (Exception error) when (error is ArgumentException or NotSupportedException or IOException) { return null; }
    }
    internal static IEnumerable<string> Strings(EvidenceValue value) => value is EvidenceArray list ? list.Items.OfType<EvidenceText>().Select(item => item.Value) : [];
    internal static string Slice(string value, int count) => string.Concat(value.EnumerateRunes().Take(count).Select(rune => rune.ToString()));
    internal static int Length(string value) => value.EnumerateRunes().Count();
}
