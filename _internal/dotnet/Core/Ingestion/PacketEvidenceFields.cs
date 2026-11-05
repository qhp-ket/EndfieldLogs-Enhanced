using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public sealed record RawDamageEvidence(BigInteger Sequence, double? Calculation, double? AttackScale,
    BigInteger? Blocked, string DamageTypeRaw, string DecorateMaskRaw, string Collider,
    IReadOnlyList<double?> AttackerZones, IReadOnlyList<double?> DefenderZones);
public sealed record BaselineEvidence(BigInteger Sequence, IReadOnlyDictionary<BigInteger, double> Values);
public sealed record PacketListEvidence(BigInteger Sequence, IReadOnlyList<string> Attacker, IReadOnlyList<string> Defender);

public static partial class TraceFields
{
    [GeneratedRegex("DPD_RAW\\s+#(?<seq>\\d+).*?\\bcalc=(?<calc>[-\\d.eE+]+)\\s+atkScale=(?<atk_scale>[-\\d.eE+]+)\\s+blocked=(?<blocked>\\d+)\\s+damageType=(?<damage_type>0x[0-9A-Fa-f]+|\\S+)\\s+decorateMask=(?<decorate_mask>0x[0-9A-Fa-f]+|\\S+)\\s+collider=\"(?<collider>[^\"]*)\"\\s+atkZones=\\[(?<atk_zones>[^\\]]*)\\]\\s+defZones=\\[(?<def_zones>[^\\]]*)\\]")]
    private static partial Regex RawDamagePattern();
    internal static Match RawDamageTokens(string line) => RawDamagePattern().Match(line);
    internal static Match BaselineTokens(string line) => Regex.Match(line, @"\bBASELINE\s+#(?<seq>\d+)\s+(?<body>.*)");

    public static RawDamageEvidence? RawDamage(string line)
    {
        var match = RawDamageTokens(line);
        if (!match.Success) return null;
        return new(IntegerText(match.Groups["seq"].Value)!.Value,
            OptionalFloat(match.Groups["calc"].Value), OptionalFloat(match.Groups["atk_scale"].Value),
            OptionalInteger(match.Groups["blocked"].Value), match.Groups["damage_type"].Value,
            match.Groups["decorate_mask"].Value, match.Groups["collider"].Value,
            ZoneValues(match.Groups["atk_zones"].Value), ZoneValues(match.Groups["def_zones"].Value));
    }

    // The reference deliberately does not infer an element from this evidence.
    public static string? DamageElement(RawDamageEvidence? evidence) => null;

    public static BaselineEvidence? Baseline(string line)
    {
        var match = BaselineTokens(line);
        if (!match.Success) return null;
        Dictionary<BigInteger, double> values = [];
        foreach (Match field in Regex.Matches(match.Groups["body"].Value, @"(-?\d+)=([-\d.eE+]+)"))
            values[IntegerText(field.Groups[1].Value)!.Value] = Float(field.Groups[2].Value);
        return new(IntegerText(match.Groups["seq"].Value)!.Value, values);
    }

    private static PacketListEvidence? PacketList(string line, string name)
    {
        var match = Regex.Match(line, @"\b"+name+@"\s+#(?<seq>\d+)\s+atk=\[(?<atk>[^\]]*)\]\s+def=\[(?<def>[^\]]*)\]");
        if (!match.Success) return null;
        static string[] Tokens(string value) => Regex.Split(value, @"\s+").Where(item => item.Length > 0).ToArray();
        return new(IntegerText(match.Groups["seq"].Value)!.Value, Tokens(match.Groups["atk"].Value), Tokens(match.Groups["def"].Value));
    }

    public static PacketListEvidence? PacketModifiers(string line) => PacketList(line, "PKT_MOD");
    public static PacketListEvidence? PacketAttributes(string line) => PacketList(line, "PKT_ATTR");
}
