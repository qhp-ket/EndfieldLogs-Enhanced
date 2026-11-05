using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

public sealed record OfficialDamageProfile(string Key, EvidenceObject Definition,
    IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>> Actions);

/// <summary>Resource identities and complete, version-bound action evidence.</summary>
public sealed class SkillResourceCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<string, string>> skills;
    private readonly Lazy<IReadOnlyDictionary<string, string>> buffs;
    private readonly Lazy<IReadOnlyDictionary<string, OfficialDamageProfile>> profiles;

    public SkillResourceCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        skills = new(() => LoadNumbers("skill_id"));
        buffs = new(() => LoadNumbers("buff_id"));
        profiles = new(LoadProfiles);
    }

    public IReadOnlyDictionary<string, string> Skills => skills.Value;
    public IReadOnlyDictionary<string, string> Buffs => buffs.Value;
    public IReadOnlyDictionary<string, OfficialDamageProfile> Profiles => profiles.Value;

    public SkillIdentityCatalog CreateIdentityCatalog()
    {
        var identities = Profiles.ToDictionary(pair => pair.Key,
            pair => new RuntimeBuffDamageProfile(pair.Value.Actions.ToDictionary(action => action.Key,
                action => (IReadOnlyList<DamageUnitIdentity>)action.Value.Select(unit => new DamageUnitIdentity(
                    (unit.Get("damageAttribute") as EvidenceText)?.Value,
                    (unit.Get("element") as EvidenceText)?.Value,
                    IntegerValue(unit.Get("index")))).ToArray(), StringComparer.Ordinal)), StringComparer.Ordinal);
        return new(Skills, Buffs, identities);
    }

    private static BigInteger? IntegerValue(EvidenceValue value) => value switch
    {
        EvidenceInteger number => number.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal number when double.IsFinite(number.Value) && Math.Truncate(number.Value) == number.Value => new BigInteger(number.Value),
        _ => null,
    };

    private IReadOnlyDictionary<string, string> LoadNumbers(string section)
    {
        foreach (var path in resources.TableCandidates("NumIdStrTable.json"))
            if (resources.ReadOnly(path) is EvidenceObject document && document.Get(section) is EvidenceObject entries
                && entries.Get("dic") is EvidenceObject mapping)
                return mapping.Fields.Where(pair => pair.Value is not EvidenceNull)
                    .ToDictionary(pair => pair.Key, pair => CatalogValues.Text(pair.Value), StringComparer.Ordinal);
        return new Dictionary<string, string>(StringComparer.Ordinal);
    }

    private IReadOnlyDictionary<string, OfficialDamageProfile> LoadProfiles()
    {
        Dictionary<string, OfficialDamageProfile> verified = new(StringComparer.Ordinal);
        if (resources.ReadOnlyRelative("data/local_static/skill/damage_element_catalog.json") is not EvidenceObject document
            || document.Get("source") is not EvidenceText { Value: "official_local_skilldata_memorypack" }
            || !EvidenceJson.PythonEquals(document.Get("schemaVersion"), new EvidenceInteger(2))
            || document.Get("decoder") is not EvidenceObject decoder
            || decoder.Get("kind") is not EvidenceText { Value: "typed_root_deserialization" }
            || !TypedResourceBinding.Matches(decoder) || CatalogValues.Truth(document.Get("decodeErrors"))
            || document.Get("summary") is not EvidenceObject summary
            || summary.Get("inputResourceCount") is not EvidenceInteger count || count.Value <= 0
            || !EvidenceJson.PythonEquals(summary.Get("completeRootCount"), count)
            || document.Get("skills") is not EvidenceObject definitions) return verified;
        foreach (var (key, value) in definitions.Fields)
        {
            if (value is not EvidenceObject profile || CatalogValues.Truth(profile.Get("derivedFrom"))
                || profile.Get("proof") is not EvidenceObject proof
                || proof.Get("actionBoundaries") is not EvidenceText { Value: "typed_root_deserialization" }
                || proof.Get("sourceBytes") is not EvidenceInteger bytes || bytes.Value <= 0
                || !EvidenceJson.PythonEquals(proof.Get("consumedBytes"), bytes)
                || profile.Get("actions") is not EvidenceObject actions) continue;
            Dictionary<string, IReadOnlyList<EvidenceObject>> units = new(StringComparer.Ordinal);
            var valid = true;
            foreach (var (action, items) in actions.Fields)
            {
                if (items is not EvidenceArray array || array.Items.Any(item => item is not EvidenceObject unit
                        || unit.Get("source") is not EvidenceText { Value: "typed_memorypack_full_object" }))
                {
                    valid = false;
                    break;
                }
                units[action] = array.Items.Cast<EvidenceObject>().ToArray();
            }
            if (valid) verified[key] = new(key, profile, units);
        }
        return verified;
    }

}
