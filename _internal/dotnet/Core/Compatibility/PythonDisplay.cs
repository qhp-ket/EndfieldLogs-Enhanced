using System.Globalization;
using System.Text;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Existing resource tables use Python str/repr at their JSON compatibility boundary.</summary>
public static class PythonDisplay
{
    public static IComparer<string> CodePointComparer { get; } = Comparer<string>.Create(CompareCodePoints);

    private static int CompareCodePoints(string? left, string? right)
    {
        if (left is null || right is null) return left is null ? right is null ? 0 : -1 : 1;
        static int Next(string value, ref int index)
        {
            var first = value[index++];
            return char.IsHighSurrogate(first) && index < value.Length && char.IsLowSurrogate(value[index])
                ? char.ConvertToUtf32(first, value[index++]) : first;
        }
        var a = 0;
        var b = 0;
        while (a < left.Length && b < right.Length)
        {
            var comparison = Next(left, ref a).CompareTo(Next(right, ref b));
            if (comparison != 0) return comparison;
        }
        return (left.Length - a).CompareTo(right.Length - b);
    }

    public static string Strip(string value)
    {
        static bool Space(char unit) => char.IsWhiteSpace(unit) || unit is >= '\u001c' and <= '\u001f';
        var first = 0;
        var end = value.Length;
        while (first < end && Space(value[first])) first++;
        while (end > first && Space(value[end - 1])) end--;
        return value[first..end];
    }

    public static string String(EvidenceValue value) => value is EvidenceText text ? text.Value : Repr(value);

    public static string Repr(EvidenceValue value) => value switch
    {
        EvidenceNull => "None",
        EvidenceBoolean flag => flag.Value ? "True" : "False",
        EvidenceInteger number => number.Value.ToString(CultureInfo.InvariantCulture),
        EvidenceReal number => Float(number.Value),
        EvidenceText text => Quoted(text.Value),
        EvidenceArray array => "[" + string.Join(", ", array.Items.Select(Repr)) + "]",
        EvidenceObject obj => "{" + string.Join(", ", obj.Fields.Select(pair => Quoted(pair.Key) + ": " + Repr(pair.Value))) + "}",
        _ => throw new InvalidDataException("Unknown evidence value"),
    };

    public static string Float(double value)
    {
        if (double.IsNaN(value)) return "nan";
        if (double.IsPositiveInfinity(value)) return "inf";
        if (double.IsNegativeInfinity(value)) return "-inf";
        var sign = BitConverter.DoubleToInt64Bits(value) < 0 ? "-" : "";
        if (value == 0) return sign + "0.0";
        var text = Math.Abs(value).ToString("R", CultureInfo.InvariantCulture);
        var parts = text.Split('E', 'e');
        var exponent = parts.Length == 2 ? int.Parse(parts[1], CultureInfo.InvariantCulture) : 0;
        var point = parts[0].IndexOf('.');
        if (point < 0) point = parts[0].Length;
        var digits = parts[0].Replace(".", "", StringComparison.Ordinal);
        exponent += point - 1;
        var leading = digits.Length - digits.TrimStart('0').Length;
        digits = digits[leading..].TrimEnd('0');
        exponent -= leading;
        if (exponent is < -4 or >= 16)
            return sign + digits[0] + (digits.Length > 1 ? "." + digits[1..] : "")
                + "e" + (exponent < 0 ? "-" : "+") + Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture);
        var position = exponent + 1;
        if (position <= 0) return sign + "0." + new string('0', -position) + digits;
        if (position >= digits.Length) return sign + digits + new string('0', position - digits.Length) + ".0";
        return sign + digits[..position] + "." + digits[position..];
    }

    private static string Quoted(string value)
    {
        var quote = value.Contains('\'') && !value.Contains('"') ? '"' : '\'';
        StringBuilder result = new();
        result.Append(quote);
        for (var index = 0; index < value.Length; index++)
        {
            var code = (int)value[index];
            if (char.IsHighSurrogate(value[index]) && index + 1 < value.Length && char.IsLowSurrogate(value[index + 1]))
                code = char.ConvertToUtf32(value[index++], value[index]);
            if (code == quote || code == '\\') result.Append('\\').Append((char)code);
            else if (code == '\t') result.Append("\\t");
            else if (code == '\n') result.Append("\\n");
            else if (code == '\r') result.Append("\\r");
            else
            {
                var category = code is >= 0xd800 and <= 0xdfff ? UnicodeCategory.Surrogate
                    : Rune.GetUnicodeCategory(new Rune(code));
                if (code != 32 && category is UnicodeCategory.Control or UnicodeCategory.Format or UnicodeCategory.Surrogate
                    or UnicodeCategory.PrivateUse or UnicodeCategory.OtherNotAssigned or UnicodeCategory.SpaceSeparator
                    or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator)
                    result.Append(code <= 255 ? "\\x" : code <= 65535 ? "\\u" : "\\U")
                        .Append(code.ToString(code <= 255 ? "x2" : code <= 65535 ? "x4" : "x8", CultureInfo.InvariantCulture));
                else if (code <= 65535) result.Append((char)code);
                else result.Append(char.ConvertFromUtf32(code));
            }
        }
        return result.Append(quote).ToString();
    }
}
