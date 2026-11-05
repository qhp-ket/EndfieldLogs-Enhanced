using System.Globalization;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveEngineCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        var cases = fixture is JsonArray list ? list : fixture["cases"]!.AsArray();
        JsonArray output = [];
        using var resources = new ResourceFixture(fixture is JsonObject ? fixture : new JsonObject());
        var ingestion = BattleIngestionResources.Load(resources.Files);
        Dictionary<int, BattleReportAnalysis> analyses = [];
        foreach (var test in cases)
        {
            var input = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var minutes = (int)((EvidenceInteger)input.Get("offset_minutes")).Value;
            if (!analyses.TryGetValue(minutes, out var analysis))
            {
                var zone = TimeZoneInfo.CreateCustomTimeZone("fixed-fixture", TimeSpan.FromMinutes(minutes), "fixed-fixture", "fixed-fixture");
                analyses[minutes] = analysis = BattleReportAnalysis.Load(resources.Files, zone);
            }
            LiveBattleEngine engine = new(ingestion, analysis, DateOnly.ParseExact(((EvidenceText)input.Get("date")).Value,
                "yyyy-MM-dd", CultureInfo.InvariantCulture));
            JsonArray actual = [];
            foreach (var step in ((EvidenceArray)input.Get("steps")).Items.Cast<EvidenceObject>())
            {
                if (step.Get("reset") is EvidenceBoolean { Value: true }) engine.Reset();
                var snapshot = engine.Snapshot(((EvidenceArray)step.Get("lines")).Items.Cast<EvidenceText>().Select(row => row.Value).ToArray(),
                    (step.Get("timer") as EvidenceText)?.Value, step.Get("summary") is EvidenceBoolean { Value: true });
                actual.Add(FieldCases.Canonical(snapshot));
            }
            output.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, output.ToJsonString());
        var failures = output.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Live engine differential: {output.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
