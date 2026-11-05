using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Skill classification from character declarations; display labels never infer a family.</summary>
public sealed class SkillProfileCatalog
{
    private readonly ResourceFiles resources;
    private readonly CharacterResourceCatalog characters;
    private readonly SkillIdentityCatalog identities;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> profiles;
    private static readonly Dictionary<string, string> Elements = new(StringComparer.Ordinal)
    { ["pd"]="physical", ["fire"]="fire", ["cryst"]="cryst", ["pulse"]="pulse", ["natur"]="natural", ["natural"]="natural" };

    public SkillProfileCatalog(ResourceFiles resources, CharacterResourceCatalog characters, SkillIdentityCatalog identities)
    {
        this.resources = resources;
        this.characters = characters;
        this.identities = identities;
        profiles = new(Load);
    }
    public IReadOnlyDictionary<string, EvidenceObject> Profiles => profiles.Value;
    public EvidenceObject? Resolve(string? key) => string.IsNullOrEmpty(key) ? null : Profiles.GetValueOrDefault(identities.CanonicalPacketSkill(key));
    public SkillHitProfile? ForHit(string key) => Resolve(key) is EvidenceObject row
        ? new((row.Get("group_type") as EvidenceInteger)?.Value, CharacterResourceCatalog.Text(row.Get("family_skill_key"))) : null;

    private static BigInteger Group(EvidenceValue value) => value switch
    {
        EvidenceInteger number => number.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal number when double.IsInfinity(number.Value) => throw new OverflowException("Infinite skill group"),
        EvidenceReal number => double.IsNaN(number.Value) ? BigInteger.Zero : new BigInteger(number.Value),
        EvidenceText text when Regex.IsMatch(PythonDisplay.Strip(text.Value), @"\A[+-]?\d+(?:_\d+)*\z") => TraceFields.OptionalInteger(text.Value) ?? BigInteger.Zero,
        _ => BigInteger.Zero,
    };

    private IReadOnlyDictionary<string, EvidenceObject> Load()
    {
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        if (!Directory.Exists(resources.PathFor("data/akedata/character/items"))) return result;
        var profiles = characters.Profiles;
        foreach (var item in characters.Items)
        {
            var character = CharacterResourceCatalog.Text(item.Get("charId"));
            if (character.Length == 0) continue;
            var profile = profiles.GetValueOrDefault(character) ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            foreach (var skill in CharacterResourceCatalog.Skills(item))
            {
                var group = Group(CatalogValues.Or(skill.Get("groupType"), new EvidenceInteger(0)));
                var keys = CatalogValues.Iterable(CatalogValues.Or(skill.Get("skillIds"), new EvidenceArray([])))
                    .Where(CatalogValues.Truth).Select(CatalogValues.Text).ToArray();
                var elements = Regex.Matches(CharacterResourceCatalog.Text(skill.Get("description")), @"<@ba\.([a-z_]+)>")
                    .Select(match => match.Groups[1].Value).Where(Elements.ContainsKey).Select(key => Elements[key]).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal);
                foreach (var key in keys)
                {
                    var metadata = resources.ReadRelative("data/akedata/skill/items/" + key + ".json");
                    if (metadata is not null and not EvidenceObject) throw new InvalidDataException("Skill item must be an object");
                    result[key] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
                    {
                        ["char_key"] = new EvidenceText(character),
                        ["char_type"] = new EvidenceText(CharacterResourceCatalog.Text(CatalogValues.Or(profile.Get("char_type"), item.Get("charType")))),
                        ["profession"] = new EvidenceText(CharacterResourceCatalog.Text(CatalogValues.Or(profile.Get("profession"), item.Get("profession")))),
                        ["weapon_type"] = new EvidenceText(CharacterResourceCatalog.Text(CatalogValues.Or(profile.Get("weapon_type"), item.Get("weapontype")))),
                        ["group_type"] = new EvidenceInteger(group),
                        ["skill_specification"] = new EvidenceText(metadata is EvidenceObject obj ? CharacterResourceCatalog.Text(obj.Get("skillSpecification")) : ""),
                        ["elements"] = new EvidenceArray(elements.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray()),
                        ["family_skill_key"] = new EvidenceText(group == 3 && keys.Length > 0 ? keys[0] : key),
                    });
                }
            }
        }
        return result;
    }
}
