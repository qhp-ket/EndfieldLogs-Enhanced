using System.Globalization;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class ActionIndexCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var root = EvidenceJson.Parse(test!["root"]?.ToJsonString() ?? "null");
            var cache = new BuffActionIndices();
            var index = cache.For(root);
            static object Node(TypedActionNode node) => new object[] { node.Definition, node.Enabled };
            var actual = FieldCases.Canonical(new Dictionary<string, object?>
            {
                ["actions"] = index.Actions.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture),
                    pair => pair.Value.Select(Node).ToArray()),
                ["creations"] = index.Creations.Select(Node).ToArray(),
                ["same_cached"] = ReferenceEquals(index, cache.For(root)),
                ["distinct_container"] = root is not (EvidenceObject or EvidenceArray)
                    || !ReferenceEquals(index, cache.For(EvidenceJson.Parse(test["root"]!.ToJsonString()))),
            });
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Buff action index differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
