using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;

internal static class TimerCases
{
    internal static object Project(TimerObservationState state) => new Dictionary<string, object?>
    {
        ["game_timer_start_ms"]=state.GameStartMs,
        ["game_timer_end_ms"]=state.GameEndMs,
        ["game_timer_elapsed_ms"]=state.GameElapsedMs,
        ["game_timer_window_elapsed_ms"]=state.GameWindowElapsedMs,
        ["official_timer_start_ms"]=state.OfficialStartMs,
        ["official_timer_end_ms"]=state.OfficialEndMs,
        ["official_timer_elapsed_ms"]=state.OfficialElapsedMs,
        ["live_timer_elapsed_ms"]=state.LiveElapsedMs,
        ["packet_timer_elapsed_ms"]=state.PacketElapsedMs,
        ["timer_start_seen"]=state.StartSeen,
        ["timer_end_seen"]=state.EndSeen,
        ["timer_window_valid"]=state.WindowValid,
        ["challenge_pass_confirmed"]=state.ChallengePassConfirmed,
        ["official_pass_confirmed"]=state.OfficialPassConfirmed,
        ["completion_source"]=state.CompletionSource,
        ["dungeon_context_id"]=state.DungeonId,
        ["dungeon_context"]=state.Dungeon is null ? null : new[] { state.Dungeon.Key, state.Dungeon.Name },
        ["contract_tag_ids"]=state.ContractTagIds,
        ["contract_tag_score"]=state.ContractTagScore,
    };

    public static int Run(string inputPath, string outputPath)
    {
        var fixtures = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var fixture in fixtures)
        {
            var contexts = fixture!["resolutions"]!.AsObject();
            TimerObservationState state = new(id => contexts[id] is JsonArray row
                ? new(row[0]!.GetValue<string>(), row[1]!.GetValue<string>()) : null);
            JsonArray steps = [];
            foreach (var operation in fixture["operations"]!.AsArray())
            {
                var line = operation!["line"]!.GetValue<string>();
                var handled = state.ObserveStage(line) || state.ObserveTimer(line, operation["time"]!.GetValue<long>());
                steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["handled"]=handled, ["state"]=Project(state) }));
            }
            results.Add(new JsonObject { ["name"]=fixture["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(steps,fixture["expected"]), ["actual"]=steps });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Timer differential: {fixtures.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
