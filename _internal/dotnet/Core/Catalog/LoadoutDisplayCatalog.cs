using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Observed loadout display fields, distinct from version-bound damage baseline evidence.</summary>
public sealed class LoadoutDisplayCatalog
{
    private readonly Dictionary<string, EvidenceObject> weapons = new(StringComparer.Ordinal);
    private readonly Dictionary<string, EvidenceObject> equipment = new(StringComparer.Ordinal);
    private readonly Dictionary<BigInteger, string> attributes = [];
    public WeaponRefinementRules Refinement { get; }
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? Empty;
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => value is EvidenceArray list ? list.Items : [];
    private static string Clean(EvidenceValue value) => Regex.Replace(CatalogValues.Truth(value) ? PythonDisplay.String(value) : "", @"\s+", " ").Trim();
    private static EvidenceValue Option(EvidenceValue value, BigInteger? level)
    {
        var list = value is EvidenceArray array ? array.Items : new[] { value };
        return level is { Sign: >= 0 } index && index < list.Count ? list[(int)index] : EvidenceNull.Value;
    }
    public static string ValueText(EvidenceValue value, int precision = 6) => value is EvidenceReal real
        ? double.IsFinite(real.Value) ? real.Value.ToString("g" + precision, CultureInfo.InvariantCulture) : PythonDisplay.Float(real.Value)
        : PythonDisplay.String(value);

    public LoadoutDisplayCatalog(ResourceFiles resources)
    {
        Refinement = WeaponRefinementRules.Load(resources);
        foreach (var kind in new[] { "akedata", "local_tables" })
        {
            foreach (var (path, row) in resources.JsonObjects($"data/{kind}/weapon/items").OrderBy(row => row.Path, PythonDisplay.CodePointComparer))
            {
                var id = Clean(CatalogValues.Or(row.Get("weaponId"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
                var previous = weapons.GetValueOrDefault(id) ?? Empty;
                weapons[id] = new(new Dictionary<string, EvidenceValue>
                {
                    ["base_atk"] = row.Get("baseAtk") is EvidenceArray atk ? atk : previous.Get("base_atk"),
                    ["skilllist"] = row.Get("skilllist") is EvidenceArray skills ? skills : previous.Get("skilllist"),
                });
            }
            foreach (var (path, row) in resources.JsonObjects($"data/{kind}/equip/items").OrderBy(row => row.Path, PythonDisplay.CodePointComparer))
            foreach (var (key, value) in Obj(row.Get("equip")).Fields)
            {
                if (value is not EvidenceObject item) continue;
                var id = Clean(CatalogValues.Or(item.Get("itemId"), new EvidenceText(key)));
                List<EvidenceValue> affixes = [];
                void Affix(string type, int index, EvidenceObject attr) => affixes.Add(new EvidenceObject(new Dictionary<string, EvidenceValue>
                    { ["kind"] = new EvidenceText(type), ["index"] = new EvidenceInteger(index), ["desc"] = new EvidenceText(Clean(attr.Get("desc"))), ["value"] = attr.Get("value") }));
                if (item.Get("主词条") is EvidenceObject main) Affix("main", 0, main);
                static int Index(string key) => Regex.Match(key, @"\d+") is { Success: true } match ? int.Parse(match.Value, CultureInfo.InvariantCulture) : 99;
                var ordered = Obj(item.Get("副词条")).Fields.OrderBy(pair => Index(pair.Key)).ThenBy(pair => pair.Key, PythonDisplay.CodePointComparer).ToArray();
                for (var index = 0; index < ordered.Length; index++)
                    if (ordered[index].Value is EvidenceObject attr) Affix("sub", index, attr);
                equipment[id] = new(new Dictionary<string, EvidenceValue> { ["affixes"] = new EvidenceArray(affixes), ["valid_slots"] = new EvidenceArray([]) });
            }
        }
        var pieces = Obj(resources.ReadRelative("data/local_tables/equip/pieces.json") ?? EvidenceNull.Value);
        var slotParts = Items(pieces.Get("slotPartTypes"));
        var validParts = pieces.Get("slotPartTypes") is EvidenceArray && slotParts.All(value => value is EvidenceInteger)
            && pieces.Get("sourceGlobalConstSha256") is EvidenceText hash && Regex.IsMatch(hash.Value, @"\A[0-9a-f]{64}\z");
        foreach (var item in Items(pieces.Get("entries")).OfType<EvidenceObject>())
        {
            var id = Clean(CatalogValues.Or(item.Get("itemId"), item.Get("id"), new EvidenceText("")));
            if (id.Length == 0) continue;
            var slots = validParts && item.Get("partType") is EvidenceInteger part
                ? slotParts.Select((value, index) => (value, index)).Where(row => EvidenceJson.PythonEquals(row.value, part)).Select(row => (EvidenceValue)new EvidenceInteger(row.index)).ToArray() : [];
            if (equipment.TryGetValue(id, out var previous))
            { equipment[id] = new(new Dictionary<string, EvidenceValue>(previous.Fields) { ["valid_slots"] = new EvidenceArray(slots) }); continue; }
            List<EvidenceValue> affixes = [];
            if (item.Get("displayBaseAttrModifier") is EvidenceObject main)
                affixes.Add(new EvidenceObject(new Dictionary<string, EvidenceValue> { ["kind"] = new EvidenceText("main"), ["index"] = new EvidenceInteger(0),
                    ["desc"] = new EvidenceText("attribute_type_" + PythonDisplay.String(main.Get("attrType"))), ["value"] = main.Get("attrValue") }));
            var index = 0;
            foreach (var raw in Items(item.Get("displayAttrModifiers")))
            {
                if (raw is EvidenceObject attr) affixes.Add(new EvidenceObject(new Dictionary<string, EvidenceValue> { ["kind"] = new EvidenceText("sub"),
                    ["index"] = new EvidenceInteger(index), ["desc"] = new EvidenceText("attribute_type_" + PythonDisplay.String(attr.Get("attrType"))),
                    ["value"] = new EvidenceArray([attr.Get("attrValue"), ..Items(attr.Get("enhancedAttrValues"))]) }));
                index++;
            }
            equipment[id] = new(new Dictionary<string, EvidenceValue> { ["affixes"] = new EvidenceArray(affixes), ["valid_slots"] = new EvidenceArray(slots) });
        }
        foreach (var (path, row) in resources.JsonObjects("data/akedata/attribute_type/items").OrderBy(row => row.Path, PythonDisplay.CodePointComparer))
        {
            var raw = row.Get("attributeType") is EvidenceNull ? Path.GetFileNameWithoutExtension(path) : PythonDisplay.String(row.Get("attributeType"));
            if (!BigInteger.TryParse(raw, CultureInfo.InvariantCulture, out var id)) continue;
            attributes[id] = Clean(CatalogValues.Or(row.Get("slug"), new EvidenceText("attribute_type_" + id)));
        }
    }

    public EvidenceValue Attack(string template, BigInteger level)
    {
        var value = Option((weapons.GetValueOrDefault(template) ?? Empty).Get("base_atk"), level - 1);
        return value is EvidenceInteger or EvidenceReal or EvidenceBoolean ? value : EvidenceNull.Value;
    }
    public (EvidenceValue First, EvidenceValue Last) AttackBounds(string template)
    {
        var values = Items((weapons.GetValueOrDefault(template) ?? Empty).Get("base_atk"));
        static EvidenceValue Number(EvidenceValue value) => value is EvidenceInteger or EvidenceReal or EvidenceBoolean ? value : EvidenceNull.Value;
        return values.Count == 0 ? (EvidenceNull.Value, EvidenceNull.Value) : (Number(values[0]), Number(values[^1]));
    }
    public IReadOnlyList<int> Slots(string template) => Items((equipment.GetValueOrDefault(template) ?? Empty).Get("valid_slots"))
        .OfType<EvidenceInteger>().Select(value => (int)value.Value).ToArray();
    public string EquipmentStats(string template, IReadOnlyDictionary<BigInteger, BigInteger> levels)
    {
        List<string> parts = [];
        foreach (var row in Items((equipment.GetValueOrDefault(template) ?? Empty).Get("affixes")).OfType<EvidenceObject>())
        {
            var desc = Clean(row.Get("desc"));
            if (desc.Length == 0) continue;
            var main = row.Get("kind") is EvidenceText { Value: "main" };
            var index = ((EvidenceInteger)row.Get("index")).Value + 1;
            BigInteger? level = !main && levels.TryGetValue(index, out var found) ? found : null;
            var value = main ? row.Get("value") : Option(row.Get("value"), level);
            parts.Add($"{(main ? "main" : "sub" + index)}:{desc}={(value is EvidenceNull ? "unknown" : ValueText(value))}{(level is null ? "" : "@" + level)}");
        }
        return string.Join(';', parts);
    }
    public string RefineStats(string template, BigInteger refine)
    {
        List<string> parts = [];
        foreach (var skill in Items((weapons.GetValueOrDefault(template) ?? Empty).Get("skilllist")).OfType<EvidenceObject>())
        foreach (var row in Items(skill.Get("blackboard")).OfType<EvidenceObject>())
        {
            var key = Clean(row.Get("key"));
            if (key.Length > 0) parts.Add($"{Clean(CatalogValues.Or(skill.Get("skillName"), new EvidenceText("weapon_skill")))}.{key}={ValueText(Option(row.Get("value"), refine))}@refine{refine}");
        }
        return string.Join(';', parts);
    }
    public string GemLabel(BigInteger id) => attributes.GetValueOrDefault(id) ?? "attr_" + id.ToString(CultureInfo.InvariantCulture);
}
