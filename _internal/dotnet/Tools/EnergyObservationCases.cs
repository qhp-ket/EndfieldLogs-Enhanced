using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class EnergyObservationCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var snapshot = (EvidenceObject)config.Get("snapshot"); var before = PythonSortedJson.Serialize(snapshot);
            var series = EnergyObservations.Build(snapshot, (EvidenceObject)config.Get("rules"));
            Dictionary<string, object?> projected = new() { ["samples"] = series.Samples,
                ["segments"] = series.Segments.Select(row => new Dictionary<string, object?> { ["start_ms"] = row.Start, ["end_ms"] = row.End,
                    ["start_value"] = row.StartValue, ["end_value"] = row.EndValue, ["rate"] = row.Rate, ["capacity"] = row.Capacity, ["confidence"] = "estimated" }).ToArray(),
                ["notes"] = series.Notes };
            if (series.Samples.Count > 0) { projected["capacity"] = series.Capacity; projected["initial_value"] = series.InitialValue; }
            var actual = FieldCases.Canonical(new Dictionary<string, object?> { ["series"] = projected,
                ["control"] = EnergyObservations.Control(snapshot).Select(row => new Dictionary<string, object?> { ["start_ms"] = row.Start, ["end_ms"] = row.End, ["character_key"] = row.Character, ["name"] = row.Name, ["evidence"] = row.Evidence }).ToArray(),
                ["values"] = ((EvidenceArray)config.Get("stamps")).Items.Select(value => { var result = EnergyObservations.At(series, (double)((EvidenceInteger)value).Value); return new object?[] { result.Value, result.Evidence }; }).ToArray() });
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == PythonSortedJson.Serialize(snapshot), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Energy observations differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
