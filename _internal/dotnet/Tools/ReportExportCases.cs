using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Realtime;

internal static class ReportExportCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        var cases = fixture is JsonArray list ? list : fixture["cases"]!.AsArray();
        JsonArray results = [];
        using (var materialized = new ResourceFixture(fixture is JsonObject ? fixture : new JsonObject()))
        {
            var files = materialized.Files;
            var resources = BattleIngestionResources.Load(files);
            Dictionary<int, BattleReportAnalysis> analyses = [];
            foreach (var test in cases)
            {
                var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
                var original = EvidenceJsonSignature.Sorted(config);
                object? result;
                var historyParity = true;
                try
                {
                    var kind = test["kind"]!.GetValue<string>();
                    if (kind == "quality") result = SnapshotQuality.Build((EvidenceObject)config.Get("report"),
                        config.Get("include_evidence") is EvidenceBoolean { Value: true });
                    else if (kind == "integrity") result = new Dictionary<string, object?>
                    {
                        ["json"] = ReportIntegrity.CanonicalJson(config.Get("payload")), ["sha256"] = ReportIntegrity.Sha256(config.Get("payload")),
                    };
                    else
                    {
                        var minutes = (int)((EvidenceInteger)config.Get("offset_minutes")).Value;
                        if (!analyses.TryGetValue(minutes, out var analysis))
                        {
                            var zone = TimeZoneInfo.CreateCustomTimeZone("fixed-fixture", TimeSpan.FromMinutes(minutes), "fixed-fixture", "fixed-fixture");
                            analyses[minutes] = analysis = BattleReportAnalysis.Load(files, zone);
                        }
                        var overrides = (config.Get("loadouts") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value);
                        BattleIngestionStream stream = new(resources, overrides);
                        var lines = ((EvidenceArray)config.Get("lines")).Items.Cast<EvidenceText>().Select(row => row.Value).ToArray();
                        stream.Accept(lines.Select((line, index) => (index + 1, line)));
                        var captured = BattleReportInput.Capture(stream, DateOnly.ParseExact(((EvidenceText)config.Get("date")).Value, "yyyy-MM-dd", CultureInfo.InvariantCulture));
                        result = analysis.BuildReport(captured, string.Join('\n', lines), (config.Get("file_name") as EvidenceText)?.Value,
                            config.Get("debug") is EvidenceBoolean { Value: true }, config.Get("allow_empty") is EvidenceBoolean { Value: true });
                        if (result is EvidenceObject report)
                        {
                            var text = string.Join('\n', lines);
                            var fileName = (config.Get("file_name") as EvidenceText)?.Value;
                            var standard = config.Get("debug") is EvidenceBoolean { Value: true }
                                ? analysis.BuildReport(captured, text, fileName)! : report;
                            var owned = analysis.BuildHistorySnapshot(stream, DateOnly.ParseExact(((EvidenceText)config.Get("date")).Value,
                                "yyyy-MM-dd", CultureInfo.InvariantCulture), text, fileName);
                            historyParity = owned is not null && EvidenceJsonSignature.Sorted(owned)
                                == EvidenceJsonSignature.Sorted(SnapshotQuality.JsonEvidence(LiveReportProjection.Overlay(standard)));
                        }
                    }
                }
                catch (Exception error) when (error is InvalidOperationException or InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
                {
                    result = new Dictionary<string, object?> { ["error"] = error switch
                    {
                        KeyNotFoundException => "KeyError", OverflowException => "OverflowError", InvalidOperationException or FormatException => "ValueError",
                        InvalidDataException => "AttributeError", _ => "TypeError",
                    } };
                }
                var actual = FieldCases.Canonical(result);
                results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                    ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original == EvidenceJsonSignature.Sorted(config) && historyParity });
            }
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Complete report differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
