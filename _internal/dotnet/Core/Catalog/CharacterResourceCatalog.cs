using EndfieldLogs.Core.Compatibility;
using System.Text;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Character display and classification resources, independent of an analysis state.</summary>
public sealed class CharacterResourceCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<string, string>> names;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> profiles;
    private readonly Lazy<IReadOnlyList<EvidenceObject>> items;
    private readonly Lazy<IReadOnlyList<(string Key, string Name)>> skillNames;

    public CharacterResourceCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        names = new(LoadNames);
        profiles = new(LoadProfiles);
        items = new(LoadItems);
        skillNames = new(() => Items.SelectMany(item => Skills(item).SelectMany(skill =>
        {
            var name = Text(skill.Get("name"));
            return name.Length == 0 ? [] : CatalogValues.Iterable(CatalogValues.Or(skill.Get("skillIds"), new EvidenceArray([])))
                .Select(id => (Key: Text(id), Name: name)).Where(row => row.Key.Length > 0);
        })).OrderByDescending(row => row.Key.EnumerateRunes().Count()).ToArray());
    }

    internal static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    internal static IEnumerable<EvidenceObject> Skills(EvidenceObject item) =>
        CatalogValues.Iterable(CatalogValues.Or(item.Get("skills"), new EvidenceArray([])))
            .Select(value => value as EvidenceObject ?? throw new InvalidDataException("Character skill must be an object"));

    public IReadOnlyDictionary<string, string> Names => names.Value;
    public IReadOnlyDictionary<string, EvidenceObject> Profiles => profiles.Value;
    public IReadOnlyList<EvidenceObject> Items => items.Value;
    public IReadOnlyList<(string Key, string Name)> SkillNames => skillNames.Value;
    public string? Name(string? key) => string.IsNullOrEmpty(key) ? null : Names.GetValueOrDefault(key, key);

    internal static EvidenceValue? ReadNameDocument(ResourceFiles files, string path)
    {
        try { return files.ReadRelative(path); }
        catch (DecoderFallbackException) { return null; }
    }

    private IReadOnlyDictionary<string, string> LoadNames()
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        foreach (var source in new[] { "akedata", "local_tables" })
            foreach (var entry in CatalogValues.Entries(ReadNameDocument(resources, $"data/{source}/character/manifest.json")))
                if (CatalogValues.Truth(entry.Get("charId")) && CatalogValues.Truth(entry.Get("name")))
                    result[CatalogValues.Text(entry.Get("charId"))] = CatalogValues.Text(entry.Get("name"));
        return result;
    }

    private IReadOnlyDictionary<string, EvidenceObject> LoadProfiles()
    {
        var path = resources.PathFor("data/local_tables/character/manifest.json");
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        if (!File.Exists(path)) return result;
        var document = ResourceFiles.ReadStrict(path);
        var entries = document is EvidenceObject obj ? obj.Get("entries") : document;
        foreach (var value in CatalogValues.Iterable(CatalogValues.Or(entries, new EvidenceArray([]))))
        {
            if (value is not EvidenceObject row) throw new InvalidDataException("Character profile must be an object");
            if (!CatalogValues.Truth(row.Get("charId"))) continue;
            result[CatalogValues.Text(row.Get("charId"))] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
            {
                ["name"] = new EvidenceText(Text(row.Get("name"))),
                ["char_type"] = new EvidenceText(Text(CatalogValues.Or(row.Get("charTypeId"), row.Get("charTypeName")))),
                ["profession"] = new EvidenceText(Text(CatalogValues.Or(row.Get("professionName"), row.Get("profession")))),
                ["weapon_type"] = new EvidenceText(Text(row.Get("weaponTypeName"))),
            });
        }
        return result;
    }

    private IReadOnlyList<EvidenceObject> LoadItems()
    {
        var path = resources.PathFor("data/akedata/character/items");
        List<EvidenceObject> result = [];
        if (!Directory.Exists(path)) return result;
        foreach (var file in Directory.EnumerateFileSystemEntries(path, "*.json"))
        {
            EvidenceValue value;
            try { value = ResourceFiles.ReadStrict(file); }
            catch (FormatException) { continue; }
            result.Add(value as EvidenceObject ?? throw new InvalidDataException("Character item must be an object"));
        }
        return result;
    }
}
