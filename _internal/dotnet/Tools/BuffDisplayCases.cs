using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class BuffDisplayCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>()); var before = PythonSortedJson.Serialize(config);
            var rows = ((EvidenceArray)config.Get("events")).Items.OfType<EvidenceObject>().ToArray();
            var names = ((EvidenceObject)config.Get("names")).Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value);
            var stamps = ((EvidenceArray)config.Get("stamps")).Items.Cast<EvidenceInteger>().Select(value => (double)value.Value).ToArray();
            var episodes = BuffDisplay.Build(rows);
            var actual = FieldCases.Canonical(new Dictionary<string, object?>
            {
                ["episodes"] = episodes.Select(episode => new Dictionary<string, object?>
                {
                    ["key"] = new[] { episode.Key.Event, episode.Key.SourceCharacter, episode.Key.SourceActor, episode.Key.TargetCharacter, episode.Key.TargetActor },
                    ["start"] = episode.Start, ["end"] = episode.End, ["evidence"] = episode.Evidence,
                    ["states"] = episode.States.Select(state => new Dictionary<string, object?> { ["start_ms"] = state.Start, ["end_ms"] = state.End, ["stacks"] = state.Stacks, ["expiry_ms"] = state.Expiry, ["boundary"] = state.Boundary }).ToArray(),
                    ["summary"] = BuffDisplay.StateText(episode.States), ["at"] = stamps.Select(stamp => BuffDisplay.StateText(episode.States, stamp)).ToArray(),
                }).ToArray(),
                ["names"] = rows.Select(row => BuffDisplay.Name(row, names)).ToArray(), ["sources"] = rows.Select(BuffDisplay.Source).ToArray(),
            });
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == PythonSortedJson.Serialize(config), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"BUFF display differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
