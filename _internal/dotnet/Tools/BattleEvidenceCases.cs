using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class BattleEvidenceCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var rows = (EvidenceArray)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>()); var before = PythonSortedJson.Serialize(rows);
            var summary = BattleEvidence.Summary(rows.Items.OfType<EvidenceObject>());
            var actual = FieldCases.Canonical(new Dictionary<string, object?>
            {
                ["damage"] = summary.Damage, ["basis"] = summary.Basis, ["covered"] = summary.Covered, ["hits"] = summary.Hits, ["allocated"] = summary.Allocated,
                ["contributions"] = summary.Contributions.Select(share => new Dictionary<string, object?> { ["key"] = share.Key, ["name"] = share.Name, ["value"] = share.Value, ["percent"] = summary.Allocated == 0 ? (object)0 : share.Percent }).ToArray(),
            });
            // Python sum([]) is int zero; these are numeric display aggregates.
            var expected = test["expected"]!.DeepClone();
            foreach (var key in new[] { "damage", "basis", "allocated" })
                if (expected[key] is JsonObject integer && integer["int"]?.GetValue<string>() == "0") expected[key] = FieldCases.Canonical(0d);
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, expected) && before == PythonSortedJson.Serialize(rows), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Battle evidence differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
