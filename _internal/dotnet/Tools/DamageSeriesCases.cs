using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class DamageSeriesCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var result = DamageSeries.Build((EvidenceObject)config.Get("snapshot"), ((EvidenceText)config.Get("metric")).Value, ((EvidenceText)config.Get("character")).Value);
            JsonObject actual = new()
            {
                ["metric"] = result.Metric, ["missing"] = result.Missing, ["hits"] = result.Hits, ["duration_ms"] = result.DurationMs,
                ["points"] = new JsonArray(result.Points.Select(point => (JsonNode)new JsonObject { ["time_ms"] = point.TimeMs,
                    ["values"] = new JsonObject(point.Values.Select(pair => KeyValuePair.Create<string, JsonNode?>(pair.Key, JsonValue.Create(pair.Value)))) }).ToArray()),
            };
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Damage curves differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
