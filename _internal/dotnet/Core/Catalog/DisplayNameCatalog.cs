using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Exact display evidence has separate precedence from damage identity and attribution.</summary>
public sealed class DisplayNameCatalog
{
    private readonly ResourceFiles resources;
    private readonly CharacterResourceCatalog characters;
    private readonly SkillIdentityCatalog identities;
    private readonly Lazy<EvidenceObject> packet;
    private readonly Lazy<IReadOnlyDictionary<string, string>> enemies;
    private readonly Lazy<IReadOnlyDictionary<string, string>> exact;
    private readonly Lazy<IReadOnlyDictionary<string, string>> canonical;
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());

    public DisplayNameCatalog(ResourceFiles resources, CharacterResourceCatalog characters, SkillIdentityCatalog identities)
    {
        this.resources = resources;
        this.characters = characters;
        this.identities = identities;
        packet = new(LoadPacket);
        enemies = new(LoadEnemies);
        exact = new(LoadExact);
        canonical = new(LoadCanonical);
    }

    private static string Text(EvidenceValue value) => CharacterResourceCatalog.Text(value);
    private EvidenceObject Mappings => packet.Value.Get("mappings") as EvidenceObject ?? Empty;
    public IReadOnlyDictionary<string, string> ExactSkillNames => exact.Value;
    public IReadOnlyDictionary<string, string> CanonicalSkillNames => canonical.Value;
    public IReadOnlyDictionary<string, string> EnemyNames => enemies.Value;
    public string? Character(string? key) => characters.Name(key);
    public string? Enemy(string? key) => string.IsNullOrEmpty(key) ? null : EnemyNames.GetValueOrDefault(key, key);

    private EvidenceObject LoadPacket()
    {
        var path = resources.PathFor("data/packet_semantics/skill_numeric_map.json");
        EvidenceValue document;
        try { document = ResourceFiles.ReadStrict(path); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException) { return Empty; }
        return document as EvidenceObject ?? throw new InvalidDataException("Skill mapping must be an object");
    }

    private static string Strip(string value) => PythonDisplay.Strip(value);

    private IReadOnlyDictionary<string, string> LoadEnemies()
    {
        var path = resources.PathFor("data/akedata/enemy/manifest.json");
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        if (!File.Exists(path)) return result;
        foreach (var value in CatalogValues.Iterable(ResourceFiles.ReadStrict(path)))
        {
            if (value is not EvidenceObject entry) throw new InvalidDataException("Enemy entry must be an object");
            if (CatalogValues.Truth(entry.Get("templateId")) && CatalogValues.Truth(entry.Get("name")))
                result[CatalogValues.Text(entry.Get("templateId"))] = CatalogValues.Text(entry.Get("name"));
        }
        return result;
    }

    private IReadOnlyDictionary<string, string> LoadExact()
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        foreach (var (key, name) in characters.SkillNames) result[key] = name;
        if (CharacterResourceCatalog.ReadNameDocument(resources, "data/local_static/skill/display_name_catalog.json") is not EvidenceObject document
            || !EvidenceJson.PythonEquals(document.Get("schemaVersion"), new EvidenceInteger(1))
            || document.Get("source") is not EvidenceText { Value: "official_CharGrowth_I18n_typed_skill_display" }
            || document.Get("decoder") is not EvidenceObject decoder || !TypedResourceBinding.Matches(decoder)
            || document.Get("entries") is not EvidenceObject entries
            || (document.Fields.GetValueOrDefault("conflicts") ?? Empty) is not EvidenceObject conflicts) return result;
        foreach (var (key, value) in entries.Fields)
            if (key.Length > 0 && value is EvidenceObject entry && !conflicts.Fields.ContainsKey(key)
                && entry.Get("proofKind") is EvidenceText { Value: "official_char_growth_skill_list" or "typed_enabled_creation_path" }
                && entry.Get("displayName") is EvidenceText label && Strip(label.Value) is { Length: > 0 } name) result[key] = name;
        foreach (var key in conflicts.Fields.Keys) result[key] = "";
        return result;
    }

    private IReadOnlyDictionary<string, string> LoadCanonical()
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        void Add(string key, string name)
        {
            if (key.Length > 0 && name.Length > 0 && (!result.TryGetValue(key, out var existing)
                || name.EnumerateRunes().Count() > existing.EnumerateRunes().Count())) result[key] = name;
        }
        if (packet.Value.Get("canonical_display_names") is EvidenceObject preserved)
            foreach (var (key, value) in preserved.Fields) Add(Strip(key), Strip(Text(value)));
        foreach (var value in Mappings.Fields.Values.OfType<EvidenceObject>())
            Add(Text(value.Get("canonical_skill_id")), Strip(Text(value.Get("display_name"))));
        return result;
    }

    public string? Skill(string? key)
    {
        if (string.IsNullOrEmpty(key)) return null;
        if (ExactSkillNames.TryGetValue(key, out var exactName) && exactName.Length == 0) return null;
        if (key == "chr_0017_yvonne_skill_162") return "伊冯连携 / 机器人持续伤害";
        if (key == "chr_0017_yvonne_skill_163") return "伊冯连携 / 机器人终结爆炸";
        if (Mappings.Get(key) is EvidenceObject hint && CatalogValues.Truth(hint.Get("display_name")))
            return CatalogValues.Text(hint.Get("display_name"));
        if (exactName is { Length: > 0 }) return exactName;
        var canonicalKey = identities.CanonicalPacketSkill(key);
        return ExactSkillNames.TryGetValue(canonicalKey, out var canonicalName)
            ? canonicalName.Length == 0 ? null : canonicalName : CanonicalSkillNames.GetValueOrDefault(canonicalKey);
    }
}
