using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public sealed record EquipmentLevel(BigInteger Index, BigInteger Level);
public sealed record InlineEquipmentStat(string Slot, string Name, object Value, BigInteger? Level);

public static partial class TraceFields
{
    private static BigInteger? IntegerText(string text)
    {
        text = AsciiDigits(text.Trim());
        if (!Regex.IsMatch(text, @"^[+-]?\d+(?:_\d+)*$")) return null;
        return BigInteger.Parse(text.Replace("_", "", StringComparison.Ordinal), CultureInfo.InvariantCulture);
    }

    public static IReadOnlySet<string> LoadoutSuits(string? raw)
    {
        HashSet<string> result = new(StringComparer.Ordinal);
        foreach (Match match in Regex.Matches(raw ?? "", @"\[([^\]]+)\]=(\d+)"))
            if (IntegerText(match.Groups[2].Value) >= 3) result.Add(match.Groups[1].Value);
        return result;
    }

    public static IReadOnlyList<string> SkillIntegerIds(string line)
    {
        var match = Regex.Match(line, @"skillIntIds=\[([^\]]*)\]");
        return match.Success
            ? Regex.Matches(match.Groups[1].Value, @"\d+").Select(item => item.Value).ToArray() : [];
    }

    public static IReadOnlySet<string> LoadoutSkillIds(string raw) => SkillIntegerIds(raw).ToHashSet(StringComparer.Ordinal);

    public static IReadOnlyList<EquipmentLevel> EquipmentLevels(string? raw) =>
        Regex.Matches(raw ?? "", @"(\d+):(\d+)").Select(match =>
            new EquipmentLevel(IntegerText(match.Groups[1].Value)!.Value, IntegerText(match.Groups[2].Value)!.Value)).ToArray();

    public static IReadOnlyList<InlineEquipmentStat> InlineEquipmentStats(string? raw)
    {
        List<InlineEquipmentStat> result = [];
        foreach (var item in (raw ?? "").Split(';'))
        {
            var colon = item.IndexOf(':');
            var equals = item.IndexOf('=');
            if (colon < 0 || equals < 0) continue;
            // The first '=' after ':' belongs to the stat, even when the slot contains '='.
            equals = item.IndexOf('=', colon+1);
            if (equals < 0) throw new FormatException("not enough values to unpack");
            var rawValue = item[(equals+1)..];
            var value = rawValue;
            BigInteger? level = null;
            var at = rawValue.LastIndexOf('@');
            if (at >= 0)
            {
                value = rawValue[..at];
                level = IntegerText(rawValue[(at+1)..]);
            }
            result.Add(new(item[..colon], item[(colon+1)..equals],
                PositiveRate(value) is double number ? number : value, level));
        }
        return result;
    }

    public static IReadOnlyList<BigInteger> ContractTagIds(string? raw) =>
        Regex.Matches(raw ?? "", @"\d+").Select(match => IntegerText(match.Value)!.Value).ToArray();

    public static string? ShortActorNumber(string? value)
    {
        if (string.IsNullOrEmpty(value)) return null;
        var match = Regex.Match(value, @"^id_(\d+)$");
        return match.Success ? match.Groups[1].Value : null;
    }

    public static string BuildIsoDateTime(DateOnly date, long timestampMs, int rolloverDays=0, TimeZoneInfo? timeZone=null)
    {
        var local = date.ToDateTime(TimeOnly.MinValue).AddDays(rolloverDays).AddMilliseconds(timestampMs);
        var zone = timeZone ?? TimeZoneInfo.Local;
        // Logs without an offset use the local zone, as datetime.astimezone() does in the reference.
        var offset = zone.GetUtcOffset(local);
        return new DateTimeOffset(local, offset).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz", CultureInfo.InvariantCulture);
    }
}
