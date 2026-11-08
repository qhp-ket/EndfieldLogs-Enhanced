using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Contract definitions, table precedence and localized display evidence.</summary>
public sealed class ContractTagCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<BigInteger, EvidenceObject>> entries;
    public ContractTagCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        entries = new(Load);
    }

    public IReadOnlyDictionary<BigInteger, EvidenceObject> Entries => entries.Value;

    public EvidenceObject Payload(BigInteger id)
    {
        var item = Entries.GetValueOrDefault(id) ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
        var terms = item.Get("tagTerms") as EvidenceArray;
        Dictionary<string, EvidenceValue> result = new(StringComparer.Ordinal)
        {
            ["tag_id"] = new EvidenceInteger(id),
            ["score"] = new EvidenceInteger(Number(CatalogValues.Or(item.Get("score"), new EvidenceText("")))),
        };
        void Add(string target, EvidenceValue value, bool present=false)
        {
            if (present || CatalogValues.Truth(value)) result[target] = value;
        }
        Add("name", item.Get("name"));
        Add("description", item.Get("description"));
        Add("icon", CatalogValues.Or(item.Get("iconId"), item.Get("icon")));
        Add("icon_url", CatalogValues.Or(item.Get("iconUrl"), item.Get("icon_url")));
        Add("buff_id", item.Get("buffId"));
        Add("group_id", item.Get("groupId"), item.Get("groupId") is not EvidenceNull);
        Add("conflict_id", item.Get("conflictId"), item.Get("conflictId") is not EvidenceNull);
        if (terms is { Items.Count: > 0 })
        {
            result["terms"] = terms;
            Dictionary<string, EvidenceValue> values = new(StringComparer.Ordinal);
            foreach (var term in terms.Items.OfType<EvidenceObject>())
                if (term.Get("blackboard") is EvidenceArray rows)
                    foreach (var row in rows.Items.OfType<EvidenceObject>())
                        if (row.Get("key") is not EvidenceNull) values[CatalogValues.Text(row.Get("key"))] = row.Get("value");
            if (values.Count > 0) result["values"] = new EvidenceObject(values);
        }
        return new(result);
    }

    private static BigInteger Number(EvidenceValue value) => TraceFields.OptionalInteger(CatalogValues.Text(value)) ?? BigInteger.Zero;

    private IReadOnlyDictionary<BigInteger, EvidenceObject> Load()
    {
        Dictionary<BigInteger, EvidenceObject> catalog = [];
        var publicData = resources.ReadRelative("data/public/contract_tags.json");
        foreach (var item in Rows(publicData is EvidenceObject obj ? obj.Get("tags") : publicData))
        {
            var id = Number(CatalogValues.Or(item.Get("tagId"), item.Get("tag_id"), new EvidenceText("")));
            if (id > 0) catalog[id] = item;
        }
        foreach (var path in resources.TableCandidates("CcTagTable.json"))
        {
            var document = resources.Read(path);
            if (document is null) continue;
            foreach (var item in Rows(document))
            {
                var id = Number(CatalogValues.Or(item.Get("tagId"), item.Get("tag_id"), new EvidenceText("")));
                if (id <= 0) continue;
                var fields = catalog.GetValueOrDefault(id)?.Fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal)
                    ?? new Dictionary<string, EvidenceValue>(StringComparer.Ordinal);
                foreach (var (key, value) in item.Fields) fields[key] = value;
                catalog[id] = new(fields);
            }
            break;
        }
        var texts = LoadTexts();
        foreach (var (id, item) in catalog.ToArray())
        {
            var fields = item.Fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
            var name = Text(item.Get("name"), texts) ?? Text(item.Get("nameTextId"), texts);
            var description = Text(item.Fields.ContainsKey("desc") ? item.Get("desc") : item.Get("description"), texts)
                ?? Text(item.Get("descTextId"), texts);
            if (!string.IsNullOrEmpty(name)) fields["name"] = new EvidenceText(name + (item.Get("romanNumSuffix") as EvidenceText)?.Value);
            else if (item.Get("name") is not EvidenceText) fields["name"] = EvidenceNull.Value;
            if (!string.IsNullOrEmpty(description)) fields["description"] = new EvidenceText(description);
            if (CatalogValues.Truth(item.Get("formattedDescription")) && item.Get("descriptionTemplate") == fields.GetValueOrDefault("description"))
                fields["description"] = item.Get("formattedDescription");
            catalog[id] = new(fields);
        }
        return catalog;
    }

    private IReadOnlyDictionary<string, string> LoadTexts()
    {
        Dictionary<string, string> result = new(StringComparer.Ordinal);
        foreach (var path in resources.TableCandidates("I18nTextTable_CN.json"))
        {
            if (resources.Read(path) is not EvidenceObject document) continue;
            foreach (var (key, value) in document.Fields)
            {
                var text = value as EvidenceText;
                if (value is EvidenceObject obj) text = CatalogValues.Or(obj.Get("text"), obj.Get("value")) as EvidenceText;
                if (text is not null) result[key] = text.Value;
            }
            break;
        }
        if (resources.ReadRelative("data/public/server_texts.json") is EvidenceObject server
            && server.Get("source") is EvidenceText { Value: "SC_SYNC_MULTI_LANG_CONFIG" }
            && server.Get("language") is EvidenceText { Value: "CN" }
            && server.Get("texts") is EvidenceObject texts)
            foreach (var (key, value) in texts.Fields)
                if (value is EvidenceText text) result[key] = text.Value;
        return result;
    }

    private static string? Text(EvidenceValue value, IReadOnlyDictionary<string, string> texts)
    {
        if (value is EvidenceObject obj)
        {
            if (obj.Get("text") is EvidenceText { Value.Length: > 0 } text) return text.Value;
            value = obj.Get("id");
        }
        return value is EvidenceNull ? null : texts.GetValueOrDefault(CatalogValues.Text(value));
    }

    private static IEnumerable<EvidenceObject> Rows(EvidenceValue? value) => value switch
    {
        EvidenceArray array => array.Items.OfType<EvidenceObject>(),
        EvidenceObject obj => obj.Fields.Values.OfType<EvidenceObject>(),
        _ => [],
    };
}
