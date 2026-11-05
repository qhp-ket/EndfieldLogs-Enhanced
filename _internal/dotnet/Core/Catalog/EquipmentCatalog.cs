using System.Globalization;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Equipment and suit metadata; local typed attributes enrich matching upstream pieces.</summary>
public sealed class EquipmentCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> suits;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> pieces;
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static readonly EvidenceArray NoItems = new([]);
    private static EvidenceText Text(EvidenceValue value) => new(CatalogValues.Text(value));
    private static EvidenceValue Or(params EvidenceValue[] values) => CatalogValues.Or(values);

    public EquipmentCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        suits = new(LoadSuits);
        pieces = new(LoadPieces);
    }
    public IReadOnlyDictionary<string, EvidenceObject> Suits => suits.Value;
    public IReadOnlyDictionary<string, EvidenceObject> Pieces => pieces.Value;

    private IReadOnlyDictionary<string, EvidenceObject> LoadSuits()
    {
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        foreach (var (path, payload) in resources.JsonObjects("data/akedata/equip/items"))
        {
            var id = Text(Or(payload.Get("suitID"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
            result[id.Value] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
            {
                ["suit_id"] = id, ["suit_name"] = Text(Or(payload.Get("套组名称"), payload.Get("name"), id)),
                ["description"] = Text(Or(payload.Get("技能描述"), new EvidenceText(""))),
                ["value"] = payload.Get("value") is EvidenceObject value ? value : Empty,
            });
        }
        foreach (var (path, payload) in resources.JsonObjects("data/local_tables/equip/items"))
        {
            var id = Text(Or(payload.Get("suitID"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
            var fields = result.TryGetValue(id.Value, out var existing) ? new Dictionary<string, EvidenceValue>(existing.Fields, StringComparer.Ordinal)
                : new(StringComparer.Ordinal) { ["suit_id"] = id };
            var current = new EvidenceObject(fields);
            fields["suit_name"] = Text(Or(payload.Get("name"), payload.Get("displayName"), current.Get("suit_name"), id));
            fields["description"] = Text(Or(payload.Get("skillDescription"), current.Get("description"), new EvidenceText("")));
            fields["value"] = payload.Get("value") is EvidenceObject value ? value : current.Fields.GetValueOrDefault("value") ?? Empty;
            fields["required_piece_count"] = payload.Get("requiredPieceCount") is EvidenceInteger count ? count : EvidenceNull.Value;
            result[id.Value] = current;
        }
        return result;
    }

    private IReadOnlyDictionary<string, EvidenceObject> LoadPieces()
    {
        Dictionary<string, EvidenceObject> result = new(StringComparer.Ordinal);
        foreach (var (path, payload) in resources.JsonObjects("data/akedata/equip/items"))
        {
            var suit = Text(Or(payload.Get("suitID"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
            var suitName = Text(Or(payload.Get("套组名称"), suit));
            if (payload.Get("equip") is not EvidenceObject equipment) continue;
            foreach (var (itemId, value) in equipment.Fields)
            {
                if (value is not EvidenceObject item) continue;
                var id = Text(Or(item.Get("itemId"), new EvidenceText(itemId)));
                result[id.Value] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
                {
                    ["item_id"] = id, ["item_name"] = Text(Or(item.Get("name"), id)), ["suit_id"] = suit, ["suit_name"] = suitName,
                    ["part_name"] = Text(Or(item.Get("部位"), new EvidenceText(""))), ["rarity"] = item.Get("rarity"),
                    ["main_attr"] = item.Get("主词条") is EvidenceObject main ? main : EvidenceNull.Value,
                    ["sub_attrs"] = item.Get("副词条") is EvidenceObject sub ? sub : Empty,
                });
            }
        }
        Dictionary<string, EvidenceText> suitNames = new(StringComparer.Ordinal);
        foreach (var (path, payload) in resources.JsonObjects("data/local_tables/equip/items"))
        {
            var id = Text(Or(payload.Get("suitID"), new EvidenceText(Path.GetFileNameWithoutExtension(path))));
            suitNames[id.Value] = Text(Or(payload.Get("name"), payload.Get("displayName"), id));
        }
        var document = resources.ReadRelative("data/local_tables/equip/pieces.json") as EvidenceObject;
        foreach (var value in document is null ? [] : CatalogValues.Iterable(document.Fields.GetValueOrDefault("entries") ?? NoItems))
        {
            if (value is not EvidenceObject item) continue;
            var id = Text(Or(item.Get("itemId"), item.Get("id"), new EvidenceText("")));
            if (id.Value.Length == 0) continue;
            var attributes = item.Get("equipAttrModifiers");
            var proof = document!.Get("sourceTableSha256");
            if (result.TryGetValue(id.Value, out var existing))
            {
                result[id.Value] = new(new Dictionary<string, EvidenceValue>(existing.Fields, StringComparer.Ordinal)
                { ["attribute_modifiers"] = attributes, ["attribute_source_sha256"] = proof });
                continue;
            }
            EvidenceValue mainAttr = EvidenceNull.Value;
            if (item.Get("displayBaseAttrModifier") is EvidenceObject main)
                mainAttr = new EvidenceObject(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
                { ["desc"] = new EvidenceText("attribute_type_" + CatalogValues.Text(main.Get("attrType"))), ["value"] = main.Get("attrValue") });
            Dictionary<string, EvidenceValue> subAttributes = new(StringComparer.Ordinal);
            if (item.Get("displayAttrModifiers") is EvidenceArray subRows)
                for (var index = 0; index < subRows.Items.Count; index++)
                {
                    if (subRows.Items[index] is not EvidenceObject row) continue;
                    subAttributes["词条" + (index+1).ToString(CultureInfo.InvariantCulture)] = new EvidenceObject(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
                    {
                        ["desc"] = new EvidenceText("attribute_type_" + CatalogValues.Text(row.Get("attrType"))),
                        ["value"] = new EvidenceArray([row.Get("attrValue"), .. CatalogValues.Iterable(Or(row.Get("enhancedAttrValues"), NoItems))]),
                    });
                }
            var suit = Text(Or(item.Get("suitID"), new EvidenceText("suit_none")));
            result[id.Value] = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
            {
                ["item_id"] = id, ["item_name"] = Text(Or(item.Get("name"), id)), ["suit_id"] = suit,
                ["suit_name"] = suitNames.GetValueOrDefault(suit.Value) ?? suit,
                ["part_name"] = Text(Or(item.Get("partName"), new EvidenceText(""))), ["rarity"] = item.Get("rarity"),
                ["main_attr"] = mainAttr, ["sub_attrs"] = new EvidenceObject(subAttributes),
                ["attribute_modifiers"] = attributes, ["attribute_source_sha256"] = proof,
            });
        }
        return result;
    }
}
