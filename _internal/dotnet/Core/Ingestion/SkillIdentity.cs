using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public sealed record DamageUnitIdentity(string? Attribute, string? Element, BigInteger? Index);
public sealed record RuntimeBuffDamageProfile(IReadOnlyDictionary<string, IReadOnlyList<DamageUnitIdentity>> Actions);
public sealed record CharacterSkillLevels(string Owner, IReadOnlyDictionary<string, BigInteger> Levels);

/// <summary>Explicit numeric-table identities. Cast proximity never supplies a missing identity.</summary>
public sealed partial class SkillIdentityCatalog(
    IReadOnlyDictionary<string, string> skills,
    IReadOnlyDictionary<string, string> buffs,
    IReadOnlyDictionary<string, RuntimeBuffDamageProfile> damageProfiles)
{
    [GeneratedRegex(@"^(?:skill_)?(\d+)$")]
    private static partial Regex NumericSkillPattern();
    [GeneratedRegex(@"^(chr_\d{4}_[a-z0-9]+)_skill_(\d+)$")]
    private static partial Regex CompositeSkillPattern();

    public static string? RuntimeNumber(string? skill)
    {
        var text = skill ?? "";
        var match = NumericSkillPattern().Match(text);
        if (match.Success) return match.Groups[1].Value;
        match = CompositeSkillPattern().Match(text);
        return match.Success ? match.Groups[2].Value : null;
    }

    public static bool CharacterFamilyMatches(string? character, string? staticCharacter) =>
        string.IsNullOrEmpty(character) || string.IsNullOrEmpty(staticCharacter) || character == staticCharacter
        || character == "chr_9000_endmin" && staticCharacter is "chr_0002_endminm" or "chr_0003_endminf";

    public static bool OwnerDomainMatches(string? owner, string? staticId)
    {
        if (string.IsNullOrEmpty(owner) || string.IsNullOrEmpty(staticId)) return true;
        if (owner.StartsWith("chr_", StringComparison.Ordinal) && ActorIdentity.EnemyKey(staticId) is not null) return false;
        return !owner.StartsWith("eny_", StringComparison.Ordinal) || ActorIdentity.CharacterKey(staticId) is null;
    }

    private static string? CanonicalNumber(IReadOnlyDictionary<string, string> mapping, string? number, string? owner)
    {
        if (string.IsNullOrEmpty(number) || !mapping.TryGetValue(number, out var id) || string.IsNullOrEmpty(id)
            || !OwnerDomainMatches(owner, id)) return null;
        var character = ActorIdentity.CharacterKey(id);
        return character is not null && !CharacterFamilyMatches(owner, character) ? null : id;
    }

    public string? CanonicalSkillNumber(string? number, string? owner) => CanonicalNumber(skills, number, owner);
    public string? CanonicalSkill(string? skill, string? owner) => CanonicalSkillNumber(RuntimeNumber(skill), owner);
    public string? CanonicalBuffNumber(string? number, string? owner) => CanonicalNumber(buffs, number, owner);
    public string CanonicalPacketSkill(string? skill) => CanonicalSkill(skill, null) ?? skill ?? "";

    public string CanonicalHitSkill(string? skill, string? owner)
    {
        var raw = skill ?? "";
        var number = RuntimeNumber(raw);
        if (number is not null && CanonicalSkill(raw, owner) is not null && CanonicalBuffNumber(number, owner) is not null)
            return raw;
        return CanonicalSkill(raw, owner) ?? raw;
    }

    public string? CanonicalRuntimeBuff(string? skill, string? owner, BigInteger? actionId=null, BigInteger? unitIndex=null)
    {
        var buff = CanonicalBuffNumber(RuntimeNumber(skill), owner);
        if (buff is null || CanonicalSkill(skill, owner) is not null) return null;
        if (actionId is not null && damageProfiles.TryGetValue(buff, out var profile)
            && profile.Actions.TryGetValue(actionId.Value.ToString(System.Globalization.CultureInfo.InvariantCulture), out var units)
            && units.Count(unit => unit.Attribute == "hp" && !string.IsNullOrEmpty(unit.Element) && unit.Index == unitIndex) == 1)
            return buff;
        return null;
    }

    public string? HitFromTemplate(string? skill, string? owner, string? templateType, BigInteger? actionId=null, BigInteger? unitIndex=null)
    {
        if (RuntimeNumber(skill) is not null)
        {
            if (templateType == "buff") return CanonicalBuffNumber(RuntimeNumber(skill), owner) ?? skill;
            if (templateType == "skill") return CanonicalSkill(skill, owner) ?? skill;
        }
        return CanonicalRuntimeBuff(skill, owner, actionId, unitIndex);
    }

    public string FamilyKey(string? skill, string? profileFamily=null)
    {
        if (string.IsNullOrEmpty(skill)) return "";
        return string.IsNullOrEmpty(profileFamily) ? CanonicalPacketSkill(skill) : profileFamily;
    }

    private static bool IsPythonDigit(Rune value) => Rune.IsDigit(value) || value.Value is
        >= 0xB2 and <= 0xB3 or 0xB9 or >= 0x1369 and <= 0x1371 or 0x19DA or 0x2070
        or >= 0x2074 and <= 0x2079 or >= 0x2080 and <= 0x2089 or >= 0x2460 and <= 0x2468
        or >= 0x2474 and <= 0x247C or >= 0x2488 and <= 0x2490 or 0x24EA or >= 0x24F5 and <= 0x24FD
        or 0x24FF or >= 0x2776 and <= 0x277E or >= 0x2780 and <= 0x2788 or >= 0x278A and <= 0x2792
        or >= 0x10A40 and <= 0x10A43 or >= 0x10E60 and <= 0x10E68 or >= 0x11052 and <= 0x1105A
        or >= 0x1F100 and <= 0x1F10A;

    public static bool IsDigitText(string value) => value.Length > 0 && value.EnumerateRunes().All(IsPythonDigit);

    public CharacterSkillLevels? ParseCharacterSkills(string line)
    {
        var fields = TraceFields.Extract(line);
        var owner = fields.GetValueOrDefault("owner");
        var match = Regex.Match(line, @"skills=\[([^\]]*)\]");
        if (string.IsNullOrEmpty(owner) || !match.Success) return null;
        return CharacterSkills(owner, Regex.Split(match.Groups[1].Value, @"\s+").Select(token =>
        {
            var separator = token.LastIndexOf(':');
            return separator < 1 ? ("", "") : (token[..separator], token[(separator+1)..]);
        }));
    }

    public CharacterSkillLevels? CharacterSkills(string owner, IEnumerable<(string Skill, string Level)> observations)
    {
        if (owner.Length == 0) return null;
        Dictionary<string, BigInteger> levels = new(StringComparer.Ordinal);
        HashSet<string> conflicts = new(StringComparer.Ordinal);
        foreach (var (rawSkill, rawLevel) in observations)
        {
            var skill = rawSkill;
            var level = TraceFields.OptionalInteger(rawLevel);
            if (skill.Length == 0 || level is null || level <= 0) continue;
            // Python str.isdigit includes non-decimal digits; unresolved such IDs are discarded too.
            if (ActorIdentity.IsGenericRuntimeSkill(skill) || Regex.IsMatch(skill, @"\A.*_skill_\d+\z") || skill.EnumerateRunes().All(IsPythonDigit))
            {
                var canonical = CanonicalSkill(skill, owner);
                if (canonical is null) continue;
                skill = canonical;
            }
            if (conflicts.Contains(skill)) continue;
            if (levels.TryGetValue(skill, out var previous) && previous != level)
            {
                levels.Remove(skill);
                conflicts.Add(skill);
            }
            else levels[skill] = level.Value;
        }
        return levels.Count > 0 ? new(owner, levels) : null;
    }
}
