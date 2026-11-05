using System.Globalization;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Runtime.Realtime;

internal static class LivePublicationCases
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
            LiveSessionOptions options = new(Summary: config["summary"]!.GetValue<bool>());
            using LiveSnapshotPublisher publisher = new(new(() => new LiveBattleEngine(ingestion, analysis, date, zone).Snapshot, options), TimeSpan.Zero);
            Dictionary<string, string> streams = [];
            JsonNode? Normalized(LiveSnapshotFrame? frame)
            {
                if (frame is null) return null;
                if (!streams.TryGetValue(frame.StreamId, out var id)) streams[frame.StreamId] = id = "stream-" + streams.Count;
                return FieldCases.Canonical((frame with { StreamId = id }).ToEvidence());
            }
            JsonArray actual = [];
            foreach (var operation in config["operations"]!.AsArray())
            {
                if (operation!["reset"]?.GetValue<bool>() == true) publisher.Reset(operation["new_stream"]?.GetValue<bool>() ?? false);
                if (operation["feed"] is JsonArray lines) foreach (var line in lines) publisher.FeedLine(line!.GetValue<string>());
                if (operation["request"]?.GetValue<bool>() == true) publisher.RequestCurrent();
                var frame = operation["publish"]?.GetValue<bool>() == false ? null : publisher.PublishPendingAsync().GetAwaiter().GetResult();
                actual.Add(new JsonObject { ["frame"] = Normalized(frame), ["current"] = Normalized(publisher.Current) });
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Live publication differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
