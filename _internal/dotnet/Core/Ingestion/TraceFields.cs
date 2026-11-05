using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public static partial class TraceFields
{
    [GeneratedRegex(@"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s+")]
    private static partial Regex Timestamp();
    [GeneratedRegex("(\\w+)=(\".*?\"|\\S+)")]
    private static partial Regex KeyValue();
    [GeneratedRegex(@"^[+-]?(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$")]
    private static partial Regex DecimalNumber();

    private static string AsciiDigits(string value)
    {
        StringBuilder result = new(value.Length);
        for (var i = 0; i < value.Length; i++)
        {
            var digit = CharUnicodeInfo.GetDecimalDigitValue(value, i);
            if (digit >= 0)
            {
                result.Append((char)('0'+digit));
                if (char.IsHighSurrogate(value[i])) i++;
            }
            else result.Append(value[i]);
        }
        return result.ToString();
    }

    public static long? PrefixedTimestampMs(string line)
    {
        var match = Timestamp().Match(line);
        if (!match.Success) return null;
        var hour = int.Parse(AsciiDigits(match.Groups[1].Value), CultureInfo.InvariantCulture);
        var minute = int.Parse(AsciiDigits(match.Groups[2].Value), CultureInfo.InvariantCulture);
        var second = int.Parse(AsciiDigits(match.Groups[3].Value), CultureInfo.InvariantCulture);
        var millisecond = int.Parse(AsciiDigits(match.Groups[4].Value), CultureInfo.InvariantCulture);
        return ((hour*60L+minute)*60+second)*1000+millisecond;
    }

    public static long? HintTimestampMs(string? value)
    {
        if (string.IsNullOrEmpty(value)) return null;
        var parts = value.Split('-');
        if (parts.Length != 4) return null;
        var numbers = parts.Select(part =>
        {
            var text = AsciiDigits(part.Trim());
            if (!Regex.IsMatch(text, @"^[+-]?\d+(?:_\d+)*$")) throw new FormatException("invalid timestamp component");
            return long.Parse(text.Replace("_", "", StringComparison.Ordinal), CultureInfo.InvariantCulture);
        }).ToArray();
        return ((numbers[0]*60+numbers[1])*60+numbers[2])*1000+numbers[3];
    }

    public static string? MillisecondTimeText(long? timestamp)
    {
        if (timestamp is not long value) return null;
        value = ((value%86400000)+86400000)%86400000;
        return string.Create(CultureInfo.InvariantCulture, $"{value/3600000:00}:{value/60000%60:00}:{value/1000%60:00}.{value%1000:000}");
    }

    public static Dictionary<string, string> Extract(string line)
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        foreach (Match match in KeyValue().Matches(line))
        {
            var value = match.Groups[2].Value;
            result[match.Groups[1].Value] = value.StartsWith('"') && value.EndsWith('"') ? value[1..^1] : value;
        }
        return result;
    }

    public static string? Token(string line, string key)
    {
        var match = Regex.Match(line, @"\b"+Regex.Escape(key)+@"=([^\s]+)");
        return match.Success ? match.Groups[1].Value : null;
    }

    public static string? Braced(string line, string key)
    {
        var marker = key+'=';
        var start = line.IndexOf(marker, StringComparison.Ordinal);
        if (start < 0) return null;
        var first = line.IndexOf('{', start+marker.Length);
        if (first < 0) return null;
        var depth = 0;
        for (var i = first; i < line.Length; i++)
        {
            if (line[i] == '{') depth++;
            else if (line[i] == '}' && --depth == 0) return line[(first+1)..i];
        }
        return null;
    }

    public static IReadOnlyList<string> SplitTopLevel(string value, char separator)
    {
        List<string> result = [];
        var start = 0;
        var depth = 0;
        void Add(int end)
        {
            var part = value[start..end].Trim();
            if (part.Length > 0) result.Add(part);
        }
        for (var i = 0; i < value.Length; i++)
        {
            if (value[i] == '{') depth++;
            else if (value[i] == '}') depth=Math.Max(0, depth-1);
            else if (value[i] == separator && depth == 0) { Add(i); start=i+1; }
        }
        Add(value.Length);
        return result;
    }

    public static BigInteger? OptionalInteger(object? input)
    {
        if (input is null or bool) return null;
        if (input is BigInteger integer) return integer;
        if (input is byte or short or int or long or sbyte or ushort or uint or ulong)
            return BigInteger.Parse(Convert.ToString(input, CultureInfo.InvariantCulture)!);
        if (input is double number)
            return double.IsFinite(number) && number == Math.Truncate(number) && Math.Abs(number) <= 9007199254740992d
                ? new BigInteger(number) : null;
        if (input is not string text) return null;
        text = AsciiDigits(text.Trim()).Replace("_", "", StringComparison.Ordinal);
        if (BigInteger.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out integer)) return integer;
        var match = DecimalNumber().Match(text);
        if (!match.Success) return null;
        var before = match.Groups[1].Value;
        var fraction = match.Groups[3].Success ? match.Groups[3].Value : match.Groups[2].Value;
        var coefficient = BigInteger.Parse((before.Length == 0 ? "0" : before)+fraction, CultureInfo.InvariantCulture);
        if (text.StartsWith('-')) coefficient = -coefficient;
        var exponent = match.Groups[4].Success ? BigInteger.Parse(match.Groups[4].Value, CultureInfo.InvariantCulture) : BigInteger.Zero;
        var scale = new BigInteger(fraction.Length)-exponent;
        if (coefficient.IsZero) return BigInteger.Zero;
        if (scale < int.MinValue || scale > int.MaxValue) return null;
        if (scale <= 0) return coefficient*BigInteger.Pow(10, checked(-(int)scale));
        // A nonzero integer cannot have more fractional zeroes than its digits.
        if (scale > before.Length+fraction.Length) return null;
        var divisor = BigInteger.Pow(10, (int)scale);
        var quotient = BigInteger.DivRem(coefficient, divisor, out var remainder);
        return remainder.IsZero ? quotient : null;
    }

    public static double Float(string? value, double fallback=0)
    {
        if (value is null) return fallback;
        return TryFloat(value, out var number) ? number : fallback;
    }

    internal static bool TryFloat(string value, out double number)
    {
        var text = AsciiDigits(value.Trim());
        if (text.Contains('_'))
        {
            text = Regex.Replace(text, @"(?<=\d)_(?=\d)", "");
            if (text.Contains('_')) { number=0; return false; }
        }
        var special = text.ToLowerInvariant();
        number = special switch
        {
            "inf" or "+inf" or "infinity" or "+infinity" => double.PositiveInfinity,
            "-inf" or "-infinity" => double.NegativeInfinity,
            "nan" or "+nan" or "-nan" => double.NaN,
            _ => 0,
        };
        return special is "inf" or "+inf" or "infinity" or "+infinity" or "-inf" or "-infinity" or "nan" or "+nan" or "-nan"
               || double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out number);
    }

    public static double? OptionalFloat(object? input)
    {
        if (input is null or bool) return null;
        double value;
        if (input is string text) value=Float(text, double.NaN);
        else if (input is BigInteger integer) value=double.Parse(integer.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
        else if (input is IConvertible convertible)
        {
            try { value=convertible.ToDouble(CultureInfo.InvariantCulture); }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException) { return null; }
        }
        else return null;
        return double.IsFinite(value) ? value : null;
    }

    public static double? PositiveRate(object? input) => OptionalFloat(input) is double value && value > 0 ? value : null;

    public static BigInteger? PositiveInteger(object? input)
    {
        double value;
        if (input is string text) { if (!TryFloat(text, out value)) return null; }
        else if (input is BigInteger integer)
        {
            value=double.Parse(integer.ToString(CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
            if (!double.IsFinite(value)) throw new OverflowException("int too large to convert to float");
        }
        else if (input is IConvertible convertible)
        {
            try { value=convertible.ToDouble(CultureInfo.InvariantCulture); }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException) { return null; }
        }
        else return null;
        if (value <= 0) return null;
        if (double.IsNaN(value)) throw new FormatException("cannot convert float NaN to integer");
        var rounded = Math.Round(value, MidpointRounding.ToEven);
        return Math.Abs(value-rounded) > 0.0001 ? null : new BigInteger(rounded);
    }

    public static IReadOnlyList<double?> ZoneValues(string? blob) => string.IsNullOrWhiteSpace(blob)
        ? [] : blob.Split(',').Select(part => OptionalFloat(part.Trim())).ToArray();

    public static long? DurationMs(string? input)
    {
        var seconds = Float(input, -1);
        if (seconds < 0 || seconds > 1000000) return null;
        if (double.IsNaN(seconds)) throw new FormatException("cannot convert float NaN to integer");
        return checked((long)Math.Round(seconds*1000, MidpointRounding.ToEven));
    }

    public static IReadOnlyDictionary<string, object> BlackboardAssignments(string? blob)
    {
        Dictionary<string, object> result = new(StringComparer.Ordinal);
        foreach (var item in SplitTopLevel(blob ?? "", ','))
        {
            var separator = item.IndexOf('=');
            if (separator < 0) continue;
            var value = item[(separator+1)..].Trim();
            result[item[..separator].Trim()] = OptionalFloat(value) is double number ? number : value;
        }
        return result;
    }
}
