using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.History;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;

internal static class HistoryCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        HistoryCatalog catalog = new(TimeZoneInfo.CreateCustomTimeZone("reference", TimeSpan.FromHours(8), "reference", "reference"));
        foreach (var test in cases)
        {
            var data = JsonNode.Parse(test!["config_json"]!.GetValue<string>())!; JsonNode? actual;
            try
            {
                switch (test["kind"]!.GetValue<string>())
                {
                    case "split":
                        actual = JsonSerializer.SerializeToNode(TraceBattleSplitter.Split(data["text"]!.GetValue<string>()).Select(row => new
                        { row.BattleIndex, row.StartLineIndex, row.Content, row.FirstHitHint, row.LastHitHint, row.FirstHitLineIndex }), JsonContract.Options);
                        break;
                    case "trace":
                    case "events":
                        var trace = test["kind"]!.GetValue<string>() == "trace";
                        var path = Path.Combine(@"C:\history", data["file_name"]!.GetValue<string>());
                        HistoryFileSignature signature = new(data["signature"]![0]!.GetValue<long>(), data["signature"]![1]!.GetValue<long>());
                        var records = trace ? catalog.ParseTrace(path, Convert.FromHexString(data["data"]!.GetValue<string>()), signature)
                            : catalog.ParseEvents(path, data["text"]!.GetValue<string>(), signature);
                        actual = new JsonArray(records.Select(Project).ToArray());
                        break;
                    case "name": actual = JsonValue.Create(HistoryFiles.RenamedPath(data["path"]!.GetValue<string>(), data["label"]!.GetValue<string>())); break;
                    case "bindings":
                        var settings = new ApplicationSettings { Service = ServiceSettings.Default(new(@"C:\history", @"C:\history")), InputLogBindings = (EvidenceObject)EvidenceJson.Parse(data["bindings"]!.ToJsonString()) };
                        actual = JsonNode.Parse(PythonSortedJson.Serialize(HistoryFiles.Relocate(settings, data["old"]!.GetValue<string>(), data["new"]!.GetValue<string>()).InputLogBindings));
                        break;
                    default: throw new InvalidDataException("Unknown history case");
                }
            }
            catch (Exception error) when (error is InvalidDataException or ArgumentException or FormatException or OverflowException)
            { actual = new JsonObject { ["error"] = error.Message }; }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"History differential: {outcomes.Count} cases, {failures} differences"); return failures == 0 ? 0 : 1;
    }
    private static JsonNode Project(HistoryRecord row)
    {
        JsonObject result = new()
        {
            ["file_path"] = row.FilePath, ["record_index"] = row.RecordIndex, ["started_at_ms"] = row.StartedAtMs, ["label"] = row.Label,
            ["players"] = new JsonArray(row.Players.Select(player => JsonSerializer.SerializeToNode(new
            { battle_inst_id = player.BattleInstanceId, display_name = player.DisplayName, templateid = player.TemplateId, squad_index = player.SquadIndex,
                total_damage = player.TotalDamage, max_damage = player.MaxDamage, crit_count = player.CritCount, hit_count = player.HitCount }, JsonContract.Options)).ToArray()),
            ["total_damage"] = row.TotalDamage, ["duration_ms"] = row.DurationMs, ["source_start_line"] = row.SourceStartLine,
            ["source_end_line"] = row.SourceEndLine, ["analysis_loaded"] = row.AnalysisLoaded, ["key"] = row.Key,
        };
        if (row.IsTrace)
        {
            result["source_signature"] = new JsonArray(row.SourceSignature.ModifiedNanoseconds, row.SourceSignature.ByteSize);
            result["source_byte_start"] = row.SourceByteStart; result["source_byte_end"] = row.SourceByteEnd;
            result["last_hit_hint"] = row.LastHitHint; result["reference_date"] = row.ReferenceDate;
        }
        return result;
    }
}
