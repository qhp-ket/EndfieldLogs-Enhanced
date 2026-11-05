using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Protocol identity hints retain their loadout guards and ambiguity.</summary>
public sealed class PacketBuffCatalog
{
    private readonly IReadOnlyDictionary<string, EvidenceObject> numeric;
    private readonly IReadOnlyDictionary<string, EvidenceObject> canonical;
    private readonly IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>> mechanisms;
    private readonly IReadOnlyDictionary<string, string> numbers;
    private readonly SkillIdentityCatalog identities;

    public PacketBuffCatalog(IReadOnlyDictionary<string, EvidenceObject> numeric,
        IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>> mechanisms, IReadOnlyDictionary<string, string> numbers)
    {
        this.numeric = numeric;
        this.mechanisms = mechanisms;
        this.numbers = numbers;
        identities = new(new Dictionary<string, string>(), numbers, new Dictionary<string, RuntimeBuffDamageProfile>());
        canonical = numeric.Values.GroupBy(row => Text(row.Get("canonical_buff_id")))
            .Where(group => group.Key.Length > 0).ToDictionary(group => group.Key, group => Merge(group.ToArray()), StringComparer.Ordinal);
    }

    public static PacketBuffCatalog Load(ResourceFiles resources, SkillResourceCatalog skills)
    {
        var mappings = (resources.ReadRelative("data/packet_semantics/buff_numeric_map.json") as EvidenceObject)?.Get("mappings") as EvidenceObject;
        var registry = (resources.ReadRelative("data/packet_semantics/mechanism_registry.json") as EvidenceObject)?.Get("by_buff_id") as EvidenceObject;
        return new(mappings?.Fields.Where(pair => pair.Value is EvidenceObject)
                .ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal) ?? [],
            registry?.Fields.Where(pair => pair.Value is EvidenceArray array && array.Items.OfType<EvidenceObject>().Any())
                .ToDictionary(pair => pair.Key, pair => (IReadOnlyList<EvidenceObject>)((EvidenceArray)pair.Value).Items.OfType<EvidenceObject>().ToArray(), StringComparer.Ordinal) ?? [],
            skills.Buffs);
    }

    internal static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));

    private static EvidenceObject Merge(IReadOnlyList<EvidenceObject> rows)
    {
        var fields = new Dictionary<string, EvidenceValue>(rows[0].Fields, StringComparer.Ordinal);
        foreach (var field in new[] { "effects", "dynamic_effects" })
        {
            List<EvidenceValue> merged = [];
            HashSet<string> markers = new(StringComparer.Ordinal);
            foreach (var row in rows)
                if (row.Get(field) is EvidenceArray array)
                    foreach (var item in array.Items.OfType<EvidenceObject>())
                        // json.dumps(sort_keys=True) distinguishes integer and real literals.
                        if (markers.Add(EvidenceJsonSignature.Sorted(item))) merged.Add(item);
            if (merged.Count > 0) fields[field] = new EvidenceArray(merged);
            fields.TryAdd(field, new EvidenceArray([]));
        }
        foreach (var row in rows.Skip(1))
        {
            foreach (var key in new[] { "reason", "confidence" })
                if (!CatalogValues.Truth(fields.GetValueOrDefault(key)) && CatalogValues.Truth(row.Get(key))) fields[key] = row.Get(key);
            static bool Missing(EvidenceValue? value) => value is null or EvidenceNull or EvidenceText { Value: "" }
                || EvidenceJson.PythonEquals(value, new EvidenceInteger(0));
            if (Missing(fields.GetValueOrDefault("stack_limit")) && !Missing(row.Get("stack_limit"))) fields["stack_limit"] = row.Get("stack_limit");
        }
        return new(fields);
    }

    public EvidenceObject? Hint(string key)
    {
        if (numeric.TryGetValue(key, out var direct)) return direct;
        if (canonical.TryGetValue(key, out var mapped)) return mapped;
        var canonicalKey = SkillIdentityCatalog.IsDigitText(key) ? numbers.GetValueOrDefault(key, key) : key;
        if (!mechanisms.TryGetValue(canonicalKey, out var rows) || rows.Count != 1) return null;
        var fields = new Dictionary<string, EvidenceValue>(rows[0].Fields, StringComparer.Ordinal);
        fields["canonical_buff_id"] = new EvidenceText(Text(rows[0].Get("canonical_buff_id")) is { Length: > 0 } id ? id : canonicalKey);
        var source = rows[0].Get("source_id");
        foreach (var kind in new[] { "weapon", "suit" })
            if (rows[0].Get("source_kind") is EvidenceText type && type.Value == kind && CatalogValues.Truth(source)
                && !CatalogValues.Truth(rows[0].Get(kind+"_id"))) fields[kind+"_id"] = source;
        fields.TryAdd("scope", new EvidenceText("loadout_guarded"));
        fields.TryAdd("confidence", new EvidenceText("compiled_from_unpack"));
        return new(fields);
    }

    public static bool Applies(EvidenceObject mapping, string? owner, string? source,
        IReadOnlyDictionary<string, HashSet<string>> suits, IReadOnlyDictionary<string, string> weapons)
    {
        var character = Text(mapping.Get("character_id"));
        if (character.Length > 0 && character != owner && character != source) return false;
        var key = !string.IsNullOrEmpty(source) ? source : owner ?? "";
        var suit = Text(mapping.Get("suit_id"));
        if (suit.Length > 0 && suits.TryGetValue(key, out var active) && !active.Contains(suit)) return false;
        var weapon = Text(mapping.Get("weapon_id"));
        return weapon.Length == 0 || !weapons.TryGetValue(key, out var equipped) || equipped.Length == 0 || weapon == equipped;
    }

    public string Canonical(string raw, string? owner, string? source,
        IReadOnlyDictionary<string, HashSet<string>> suits, IReadOnlyDictionary<string, string> weapons)
    {
        if (raw == "buff_equipsuit_usp_02_dmgup") return "buff_equipsuit_usp_02_AddAttack";
        var hint = Hint(raw);
        if (hint is not null && hint.Fields.Count > 0 && !Applies(hint, owner, source, suits, weapons)) return raw;
        if (hint is not null && CatalogValues.Truth(hint.Get("canonical_buff_id"))) return CatalogValues.Text(hint.Get("canonical_buff_id"));
        var fallback = new[] { source, owner, null }.Select(key => identities.CanonicalBuffNumber(raw, key))
            .Where(value => !string.IsNullOrEmpty(value)).Distinct(StringComparer.Ordinal).ToArray();
        return fallback.Length == 1 ? fallback[0]! : raw;
    }
}
