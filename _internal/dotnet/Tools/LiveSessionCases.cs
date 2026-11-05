using System.Globalization;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Runtime.Realtime;

internal static class LiveSessionCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        using var resources = new ResourceFixture(new JsonObject());
        var ingestion = BattleIngestionResources.Load(resources.Files);
        Dictionary<int, BattleReportAnalysis> analyses = [];
        JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = JsonNode.Parse(test!["config_json"]!.GetValue<string>())!;
            var minutes = config["offset_minutes"]!.GetValue<int>();
            var zone = TimeZoneInfo.CreateCustomTimeZone("fixed-fixture", TimeSpan.FromMinutes(minutes), "fixed-fixture", "fixed-fixture");
            if (!analyses.TryGetValue(minutes, out var analysis)) analyses[minutes] = analysis = BattleReportAnalysis.Load(resources.Files, zone);
            var date = DateOnly.ParseExact(config["date"]!.GetValue<string>(), "yyyy-MM-dd", CultureInfo.InvariantCulture);
            var settings = config["options"]!;
            LiveSessionOptions options = new(settings["idle_split_ms"]?.GetValue<long>() ?? 30_000,
                settings["summary"]!.GetValue<bool>(), settings["align_to_data_watermark"]!.GetValue<bool>(),
                settings["min_reparse_interval_ms"]?.GetValue<double>() ?? 0);
            long wall = 0;
            double monotonic = 0;
            using LiveBattleSession session = new(() => new LiveBattleEngine(ingestion, analysis, date, zone).Snapshot,
                options, () => wall, () => monotonic);
            JsonArray actual = [];
            foreach (var operation in config["operations"]!.AsArray())
            {
                wall = operation!["wall_ms"]?.GetValue<long>() ?? wall;
                monotonic = operation["monotonic_ms"]?.GetValue<double>() ?? monotonic;
                if (operation["reset"]?.GetValue<bool>() == true) session.Reset();
                if (operation["live_clock"] is { } enabled) session.SetLiveClockEnabled(enabled.GetValue<bool>());
                if (operation["feed"] is JsonArray lines) session.FeedLines(lines.Select(row => row!.GetValue<string>()));
                var result = session.SnapshotAsync(operation["observer_ms"]?.GetValue<long>(),
                    operation["refresh"]?.GetValue<bool>() ?? true).GetAwaiter().GetResult();
                var state = session.State;
                actual.Add(new JsonObject { ["snapshot"] = FieldCases.Canonical(result), ["generation"] = state.Generation,
                    ["revision"] = state.Revision, ["source_revision"] = state.SourceRevision, ["line_count"] = state.LineCount,
                    ["hit_count"] = state.HitCount, ["dirty"] = state.Dirty, ["active"] = state.OfficialTimerActive,
                    ["closed"] = state.ClosedByTimerEnd, ["officially_closed"] = state.ClosedByOfficialTimerEnd });
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Live session differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
