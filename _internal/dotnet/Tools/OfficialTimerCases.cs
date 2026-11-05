using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Timing;

internal static class OfficialTimerCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            JsonNode? actual;
            if (test!["kind"]!.GetValue<string>() == "collect")
            {
                var observed = test["observed_times"] is JsonObject times ? times.ToDictionary(pair => int.Parse(pair.Key,System.Globalization.CultureInfo.InvariantCulture),pair => pair.Value!.GetValue<long>()) : null;
                var indexed = test["indexed_lines"]?.AsArray().Select(row => (row![0]!.GetValue<int>(),row[1]!.GetValue<string>()));
                actual = FieldCases.Canonical(TimerEvidenceCollector.Collect(test["text"]!.GetValue<string>(),observed,indexed)?.ToEvidence());
            }
            else
            {
                var evidence = EvidenceJson.Parse(test["evidence"]?.ToJsonString() ?? "null");
                var duration = EvidenceJson.Parse(test["duration"]?.ToJsonString() ?? "null");
                actual = FieldCases.Canonical(TimerEvidenceValidator.Validate(evidence,duration,test["game"]?.GetValue<string>()));
            }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(), ["actual"]=actual,
                ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Official timer evidence differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
