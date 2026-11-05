using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using System.Globalization;

internal static class LiveProjectionCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray output = [];
        foreach (var test in cases)
        {
            var input = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(input);
            var kind = test["kind"]!.GetValue<string>();
            var maxima = (input.Get("maxima") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key,
                pair => EndfieldLogs.Core.Effects.EffectIdentity.Float(pair.Value), StringComparer.Ordinal);
            EvidenceObject? value;
            if (kind == "clock")
            {
                var state = (EvidenceObject)input.Get("state");
                var times = new[] { "hits", "buff_starts", "unresolved_hits", "unresolved_buff_actions", "skill_casts", "dynamic_bb_events" }
                    .SelectMany(key => (state.Get(key) as EvidenceArray)?.Items ?? []).Cast<EvidenceObject>().Select(row => row.Get("ts_ms"));
                var minutes = (int)((EvidenceInteger)input.Get("offset_minutes")).Value;
                var zone = TimeZoneInfo.CreateCustomTimeZone("fixture", TimeSpan.FromMinutes(minutes), "fixture", "fixture");
                value = LiveClockProjection.TryAdvance((EvidenceObject)input.Get("previous"),
                    (state.Get("official_timer_start_ms") as EvidenceInteger)?.Value, times,
                    DateOnly.ParseExact(((EvidenceText)state.Get("reference_date")).Value, "yyyy-MM-dd", CultureInfo.InvariantCulture),
                    (input.Get("timer") as EvidenceText)?.Value, zone);
            }
            else
            {
                var report = (EvidenceObject)input.Get("report");
                value = kind == "summary" ? LiveReportProjection.Summary(report, maxima) : LiveReportProjection.Overlay(report, maxima);
            }
            var actual = FieldCases.Canonical(value);
            output.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(input) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, output.ToJsonString());
        var failures = output.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Live projection differential: {output.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
