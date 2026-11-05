using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

public sealed class BuffRootCatalog
{
    private readonly ResourceFiles resources;
    private readonly Lazy<IReadOnlyDictionary<string, EvidenceObject>> roots;
    private readonly Lazy<IReadOnlyDictionary<string, IReadOnlySet<string>>> actionTypes;

    public BuffRootCatalog(ResourceFiles resources)
    {
        this.resources = resources;
        roots = new(Load);
        actionTypes = new(() => Roots.ToDictionary(pair => pair.Key, pair => Types(pair.Value), StringComparer.Ordinal));
    }

    public IReadOnlyDictionary<string, EvidenceObject> Roots => roots.Value;
    public IReadOnlyDictionary<string, IReadOnlySet<string>> ActionTypes => actionTypes.Value;

    private IReadOnlyDictionary<string, EvidenceObject> Load()
    {
        Dictionary<string, EvidenceObject> verified = new(StringComparer.Ordinal);
        if (resources.ReadGzipRelative("data/local_static/buff/typed_roots.json.gz") is not EvidenceObject document
            || resources.ReadOnlyRelative("data/local_static/skill/damage_element_catalog.json") is not EvidenceObject damage
            || !EvidenceJson.PythonEquals(document.Get("schemaVersion"), new EvidenceInteger(1))
            || document.Get("source") is not EvidenceText { Value: "official_local_buffdata_memorypack" }
            || document.Get("decoder") is not EvidenceObject decoder
            || decoder.Get("kind") is not EvidenceText { Value: "typed_root_deserialization" }
            || !TypedResourceBinding.Matches(decoder) || !EvidenceJson.PythonEquals(decoder, damage.Get("decoder"))
            || !EvidenceJson.PythonEquals(damage.Get("schemaVersion"), new EvidenceInteger(2))
            || damage.Get("source") is not EvidenceText { Value: "official_local_skilldata_memorypack" }
            || document.Get("summary") is not EvidenceObject summary
            || document.Get("entries") is not EvidenceObject entries
            || !EvidenceJson.PythonEquals(summary.Get("completeRootCount"), new EvidenceInteger(entries.Fields.Count))
            || !EvidenceJson.PythonEquals(summary.Get("inputResourceCount"), new EvidenceInteger(entries.Fields.Count))) return verified;
        foreach (var (key, value) in entries.Fields)
        {
            if (value is not EvidenceObject entry || entry.Get("root") is not EvidenceObject root
                || root.Get("id") is not EvidenceText id || id.Value != key
                || root.Get("$type") is not EvidenceText { Value: "Beyond.Gameplay.Core.BuffData" }
                || !EvidenceJson.PythonEquals(root.Get("$offset"), new EvidenceInteger(0))
                || entry.Get("proof") is not EvidenceObject proof
                || proof.Get("sourceBytes") is not EvidenceInteger size || size.Value <= 0
                || !EvidenceJson.PythonEquals(proof.Get("consumedBytes"), size)
                || !EvidenceJson.PythonEquals(root.Get("$end"), size)) continue;
            verified[key] = root;
        }
        return verified;
    }

    private static IReadOnlySet<string> Types(EvidenceValue root)
    {
        HashSet<string> types = new(StringComparer.Ordinal);
        Stack<EvidenceValue> pending = new([root]);
        while (pending.TryPop(out var node))
        {
            if (node is EvidenceObject obj)
            {
                var name = CatalogValues.Text(CatalogValues.Or(obj.Get("$type"), new EvidenceText("")));
                if (name.Length > 0) types.Add(name.Replace('+', '.'));
                foreach (var value in obj.Fields.Values) pending.Push(value);
            }
            else if (node is EvidenceArray array)
                foreach (var value in array.Items) pending.Push(value);
        }
        return types;
    }
}
