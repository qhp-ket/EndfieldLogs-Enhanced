using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Input;

internal static class InputInterpretationCases
{
    private static JsonNode Json(EvidenceValue value) => JsonNode.Parse(PythonSortedJson.Serialize(value))!;
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var machine = new InputInterpreter(config.Get("settings")); JsonArray steps = [];
            foreach (var e in ((EvidenceArray)config.Get("events")).Items.Cast<EvidenceObject>())
            { machine.Feed(e); steps.Add(new JsonArray(machine.Actions.Select(action => Json(action.ToEvidence())).ToArray())); }
            var actions = machine.Close();
            static double Number(EvidenceValue value) => value is EvidenceReal real ? real.Value : (double)((EvidenceInteger)value).Value;
            var projected = InputInterpreter.Project(actions, Number(config.Get("start_wall_ms")), Number(config.Get("duration_ms")),
                new Dictionary<int, string> { [0] = "chr_0001_test", [2] = "chr_0003_test" }, Number(config.Get("offset_ms")));
            JsonObject actual = new()
            {
                ["settings"] = Json(InputInterpretationSettings.Normalize(config.Get("settings")).ToEvidence()), ["steps"] = steps,
                ["actions"] = new JsonArray(actions.Select(action => Json(action.ToEvidence())).ToArray()),
                ["projected"] = new JsonArray(projected.Select(action => Json(action.ToEvidence())).ToArray()),
                ["tooltips"] = new JsonArray(projected.Select(action => JsonValue.Create(action.Tooltip)).ToArray()),
            };
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Input interpretation differential: {outcomes.Count} cases, {failures} differences"); return failures == 0 ? 0 : 1;
    }
}
