using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Canonical stage grouping and maintained alias overrides.</summary>
public sealed class DungeonCatalog
{
    public const string UnknownName = "未知副本";
    private readonly ResourceFiles resources;
    private readonly Dictionary<string, DungeonContext> aliases;
    private readonly Lazy<IReadOnlyDictionary<string, DungeonContext>> byId;

    public DungeonCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        aliases = DefaultAliases();
        if (resources.ReadRelative("data/local_tables/dungeon_catalog.json") is EvidenceObject catalog
            && catalog.Get("parser") is EvidenceObject parser
            && parser.Get("dungeon_context_aliases") is EvidenceObject overrides)
            foreach (var (key, value) in overrides.Fields)
                if (value is EvidenceArray { Items.Count: 2 } pair)
                    aliases[key] = new(CatalogValues.Text(pair.Items[0]), CatalogValues.Text(pair.Items[1]));
        byId = new(Load);
    }

    public DungeonContext? Resolve(string? id) => string.IsNullOrEmpty(id) ? null
        : aliases.GetValueOrDefault(id) ?? byId.Value.GetValueOrDefault(id);

    public IReadOnlyDictionary<string, DungeonContext> Entries => byId.Value;

    private IReadOnlyDictionary<string, DungeonContext> Load()
    {
        Dictionary<string, DungeonContext> result = new(StringComparer.Ordinal);
        foreach (var source in new[] { "akedata", "local_tables" })
        {
            var items = resources.PathFor($"data/{source}/dungeon/items");
            if (!Directory.Exists(items)) continue;
            foreach (var entry in CatalogValues.Entries(resources.ReadRelative($"data/{source}/dungeon/manifest.json")))
            {
                var itemPath = ItemPath(entry, items);
                if (itemPath is null || resources.Read(itemPath) is not EvidenceObject data) continue;
                var template = CatalogValues.Text(CatalogValues.Or(entry.Get("templateId"), new EvidenceText("")));
                if (template.Length == 0) continue;
                var series = CatalogValues.Text(CatalogValues.Or(data.Get("dungeonSeriesId"), new EvidenceText(template)));
                var name = CatalogValues.Text(CatalogValues.Or(data.Get("dungeonSeriesname"), entry.Get("name"), new EvidenceText(UnknownName)));
                result.TryAdd(series, new(series, name));
                if (CatalogValues.Or(data.Get("dungeons"), data.Get("childDungeons")) is EvidenceObject children)
                    foreach (var (id, value) in children.Fields)
                    {
                        if (value is not EvidenceObject child) throw new InvalidDataException("Invalid dungeon child");
                        var childName = CatalogValues.Text(CatalogValues.Or(child.Get("name"), new EvidenceText(name)));
                        result[id] = id.StartsWith("indie_hard", StringComparison.Ordinal) || name == UnknownName && childName != UnknownName
                            ? new(id, childName) : new(series, name);
                    }
                if (data.Get("includeDungeonIds") is EvidenceArray included)
                    foreach (var value in included.Items)
                    {
                        var id = CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
                        if (id.Length > 0) result.TryAdd(id, new(id.StartsWith("indie_hard", StringComparison.Ordinal) ? id : series, name));
                    }
            }
        }
        return result;
    }

    private string? ItemPath(EvidenceObject entry, string items)
    {
        var detail = CatalogValues.Text(CatalogValues.Or(entry.Get("detailPath"), new EvidenceText("")));
        var content = CatalogValues.Text(CatalogValues.Or(entry.Get("contentFile"), new EvidenceText("")));
        if (detail.Length > 0 && File.Exists(resources.PathFor(detail))) return resources.PathFor(detail);
        return content.Length > 0 ? Path.Combine(items, Path.GetFileName(content))
            : detail.Length > 0 ? Path.Combine(items, Path.GetFileName(detail)) : null;
    }

    private static Dictionary<string, DungeonContext> DefaultAliases()
    {
        Dictionary<string, DungeonContext> result = new(StringComparer.Ordinal);
        foreach (var id in new[] { "indie_contract001", "indie_group_ccdg", "indie_ccdg001" })
            result[id] = new("indie_group_ccdg", "危机合约");
        foreach (var (number, name) in new[] { (16,"仪式旋流"), (17,"死寂表象"), (18,"忿鼓咆声"),
                     (19,"刺痛盾阵"), (20,"溶解窥看"), (21,"冯河断水") })
        {
            var id = $"indie_hard{number:000}";
            result[id] = new(id, name);
            result[id + "_s"] = new(id + "_s", name + "·苦难");
        }
        return result;
    }
}
