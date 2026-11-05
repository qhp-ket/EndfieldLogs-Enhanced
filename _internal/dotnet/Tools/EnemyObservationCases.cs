using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class EnemyObservationCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var snapshot = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>()); var before = PythonSortedJson.Serialize(snapshot);
            var result = EnemyObservations.Build(snapshot);
            var actual = FieldCases.Canonical(new Dictionary<string, object?>
            {
                ["tracks"] = result.Tracks.Select(track => new Dictionary<string, object?> { ["key"] = new[] { track.Key.Character, track.Key.Actor }, ["name"] = track.Name, ["peak"] = track.Peak,
                    ["samples"] = track.Samples.Select(point => new Dictionary<string, object?> { ["time_ms"] = point.Time, ["value"] = point.Value, ["change"] = point.Change, ["ambiguous"] = point.Ambiguous }).ToArray() }).ToArray(),
                ["snapshots"] = result.Snapshots,
                ["resistances"] = ((EvidenceArray)snapshot.Get("timeline_events")).Items.OfType<EvidenceObject>().Select(EnemyObservations.HitResistance).ToArray(),
            });
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == PythonSortedJson.Serialize(snapshot), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Enemy observations differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
