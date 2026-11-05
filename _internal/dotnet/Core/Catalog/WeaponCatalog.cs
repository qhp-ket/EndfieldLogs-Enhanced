using System.Security.Cryptography;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Display metadata and version-bound static attack evidence for observed weapons.</summary>
public sealed class WeaponCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> entries;
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static readonly EvidenceArray NoItems = new([]);

    public WeaponCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        entries = new(Load);
    }
    public IReadOnlyDictionary<string, EvidenceObject> Entries => entries.Value;

    private IReadOnlyDictionary<string, EvidenceObject> Load()
    {
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        var attack = resources.ReadRelative("data/packet_semantics/weapon_static_attack_catalog.json") ?? Empty;
        if (attack is not EvidenceObject attackDocument) throw new InvalidDataException("Weapon attack catalog must be an object");
        var attackRows = EvidenceJson.PythonEquals(attackDocument.Get("schemaVersion"), new EvidenceInteger(1))
            && attackDocument.Get("source") is EvidenceText { Value: "current_WeaponSkill_cardAttributeModifier" }
            && EvidenceJson.PythonEquals(attackDocument.Get("decoder"), NativeDamageSemanticsBinding.Evidence)
                ? CatalogValues.Or(attackDocument.Get("entries"), NoItems) : NoItems;
        foreach (var (path, payload) in resources.JsonObjects("data/akedata/weapon/items"))
        {
            var id = CatalogValues.Text(CatalogValues.Or(payload.Get("weaponId"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
            result[id] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
            {
                ["weapon_template"] = new EvidenceText(id),
                ["weapon_name"] = new EvidenceText(CatalogValues.Text(CatalogValues.Or(payload.Get("title"), payload.Get("name"), new EvidenceText(id)))),
                ["weapon_type"] = payload.Get("weapontype"), ["rarity"] = payload.Get("rarity"),
                ["base_atk_values"] = payload.Get("baseAtk") is EvidenceArray values ? values : NoItems,
                ["skilllist"] = payload.Get("skilllist") is EvidenceArray skills ? skills : NoItems,
            });
        }
        var manifest = resources.ReadRelative("data/local_tables/weapon/manifest.json") as EvidenceObject;
        foreach (var row in manifest is null ? [] : CatalogValues.Iterable(manifest.Fields.GetValueOrDefault("entries") ?? NoItems))
        {
            if (row is not EvidenceObject item) continue;
            var id = CatalogValues.Text(CatalogValues.Or(item.Get("weaponId"), item.Get("id"), new EvidenceText("")));
            if (id.Length == 0) continue;
            var fields = result.TryGetValue(id, out var existing) ? new Dictionary<string, EvidenceValue>(existing.Fields, StringComparer.Ordinal)
                : new(StringComparer.Ordinal) { ["weapon_template"] = new EvidenceText(id), ["base_atk_values"] = NoItems, ["skilllist"] = NoItems };
            var current = new EvidenceObject(fields);
            fields["weapon_name"] = new EvidenceText(CatalogValues.Text(CatalogValues.Or(item.Get("name"), current.Get("weapon_name"), new EvidenceText(id))));
            fields["weapon_type"] = CatalogValues.Or(item.Get("weaponType"), current.Get("weapon_type"));
            fields["rarity"] = CatalogValues.Or(item.Get("rarity"), current.Get("rarity"));
            result[id] = current;
            byte[] bytes;
            EvidenceValue definition;
            try
            {
                bytes = File.ReadAllBytes(resources.PathFor("data/local_tables/weapon/items/" + id + ".json"));
                definition = JsonByteEncoding.Parse(bytes);
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException) { continue; }
            if (definition is not EvidenceObject document || CatalogValues.Or(document.Get("raw"), Empty) is not EvidenceObject raw)
                throw new InvalidDataException("Weapon definition must contain an object");
            if (raw.Get("weaponSkillList") is not EvidenceArray skillIds || skillIds.Items.Any(value => value is not EvidenceText)) continue;
            fields["weapon_skill_ids"] = new EvidenceArray(skillIds.Items.ToArray());
            fields["weapon_definition_sha256"] = new EvidenceText(Convert.ToHexStringLower(SHA256.HashData(bytes)));
            List<EvidenceValue> bound = [];
            foreach (var attackRow in CatalogValues.Iterable(attackRows))
            {
                if (attackRow is not EvidenceObject field) throw new InvalidDataException("Weapon attack row must be an object");
                if (field.Get("weaponId") is EvidenceText weapon && weapon.Value == id
                    && skillIds.Items.Any(value => EvidenceJson.PythonEquals(value, field.Get("skillId")))
                    && field.Get("modifyAttributeType") is EvidenceText { Value: "Specific" }
                    && field.Get("formulaItem") is EvidenceText { Value: "BaseMultiplier" or "BaseFinalAddition" }
                    && field.Get("bbKey") is EvidenceText && field.Get("sourceRootSha256") is EvidenceText hash
                    && Regex.IsMatch(hash.Value, @"\A[0-9a-f]{64}\z"))
                    bound.Add(new EvidenceObject(new Dictionary<string, EvidenceValue>(field.Fields, StringComparer.Ordinal)));
            }
            fields["static_attack_fields"] = new EvidenceArray(bound);
        }
        return result;
    }
}
