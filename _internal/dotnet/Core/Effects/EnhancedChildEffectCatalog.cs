using System.Collections.Concurrent;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Display hints from the decoded parent actions that explicitly name a child BUFF.</summary>
public sealed class EnhancedChildEffectCatalog(
    IReadOnlyDictionary<string, EvidenceObject> semantics, Func<string, EvidenceValue?> readParent)
{
    private readonly ConcurrentDictionary<string, IReadOnlyList<EvidenceObject>> cache = new(StringComparer.Ordinal);

    public static EnhancedChildEffectCatalog Load(ResourceFiles files)
    {
        var entries = (files.ReadOnlyRelative("data/local_semantics/buff/details.json") as EvidenceObject)?.Get("entries") as EvidenceObject;
        var semantics = entries?.Fields.Where(row => row.Value is EvidenceObject)
            .ToDictionary(row => row.Key, row => (EvidenceObject)row.Value, StringComparer.Ordinal) ?? [];
        return new(semantics, key =>
        {
            var source = semantics.GetValueOrDefault(key)?.Get("source") as EvidenceObject;
            var relative = Text(source?.Get("decodedDetailPath") ?? EvidenceNull.Value);
            if (relative.Length > 0 && File.Exists(files.PathFor(relative))) return files.ReadRelative(relative);
            return files.ReadRelative($"data/akedata/buff/items/{key}.json");
        });
    }

    public IReadOnlyList<EvidenceObject> For(string child) => child.Length == 0 ? []
        : cache.GetOrAdd(child, Collect).Select(row => (EvidenceObject)BuffEvidence.Clone(row)).ToArray();

    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));

    private IReadOnlyList<EvidenceObject> Collect(string child)
    {
        List<EvidenceObject> result = [];
        HashSet<(string, string)> seen = [];
        foreach (var (parent, entry) in semantics.OrderBy(row => row.Key, PythonDisplay.CodePointComparer))
        {
            var references = CatalogValues.Iterable(CatalogValues.Or(entry.Get("referencedBuffIds"), new EvidenceArray([])));
            if (!references.Any(value => CatalogValues.Truth(value) && CatalogValues.Text(value) == child)) continue;
            var root = readParent(parent);
            if (root is not null) Walk(root);
        }
        return result;

        void Walk(EvidenceValue node)
        {
            if (node is EvidenceObject obj)
            {
                var subtype = Text(obj.Get("subType")).ToLowerInvariant();
                var element = subtype == "crystal" ? "cryst" : subtype;
                if (Text(obj.Get("$type")).Contains("EnhancedAction+Data", StringComparison.Ordinal)
                    && CatalogValues.Truth(obj.Get("asChildBuff"))
                    && obj.Get("childBuffId") is EvidenceObject id && Text(id.Get("value")) == child
                    && element is "cryst" or "natural" or "fire" or "pulse" or "physical" or "spell" or "all")
                {
                    var key = Text((obj.Get("rate") as EvidenceObject)?.Get("blackboardKey") ?? EvidenceNull.Value);
                    if (seen.Add((element, key))) result.Add(BuffEvidence.Object(
                        ("zone", new EvidenceText("amp")), ("element", new EvidenceText(element)),
                        ("bb_key", new EvidenceText(key)), ("prefer_runtime_rate_key", new EvidenceText("rate"))));
                }
                foreach (var value in obj.Fields.Values) Walk(value);
            }
            else if (node is EvidenceArray array) foreach (var value in array.Items) Walk(value);
        }
    }
}
