using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportLifecycleCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    private static BigInteger? Integer(EvidenceObject row, string key) => (row.Get(key) as EvidenceInteger)?.Value;
    private static string? Text(EvidenceObject row, string key) => (row.Get(key) as EvidenceText)?.Value;
    private static bool Flag(EvidenceObject row, string key) => row.Get(key) is EvidenceBoolean { Value: true };
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var row = (EvidenceObject)config.Get("timing");
            var hits = Rows(config.Get("hits")).Select(hit => new ReportHitInput(hit,
                new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
            var enemies = new Dictionary<string, BigInteger>(StringComparer.Ordinal);
            foreach (var hit in hits)
            {
                var enemy = ((EvidenceText)hit.Evidence.Get("target_enemy_key")).Value;
                enemies[enemy] = enemies.GetValueOrDefault(enemy) + 1;
            }
            var input = new ReportCalculationInput(new(new([], new Dictionary<string, EvidenceObject>()), hits,
                new Dictionary<string, HashSet<string>>()), Rows(config.Get("records")), [], []);
            var timer = new ReportTimingInput
            {
                GameStartMs = Integer(row, "game_timer_start_ms"), GameEndMs = Integer(row, "game_timer_end_ms"),
                GameElapsedMs = Integer(row, "game_timer_elapsed_ms"), GameWindowElapsedMs = Integer(row, "game_timer_window_elapsed_ms"),
                OfficialStartMs = Integer(row, "official_timer_start_ms"), OfficialEndMs = Integer(row, "official_timer_end_ms"),
                OfficialElapsedMs = Integer(row, "official_timer_elapsed_ms"), LiveElapsedMs = Integer(row, "live_timer_elapsed_ms"),
                PacketElapsedMs = Integer(row, "packet_timer_elapsed_ms"), FirstHitHintMs = Integer(row, "first_hit_hint_ms"),
                LastHitHintMs = Integer(row, "last_hit_hint_ms"), FirstPartyActionMs = Integer(row, "first_party_action_ms"),
                StartSeen = Flag(row, "timer_start_seen"), EndSeen = Flag(row, "timer_end_seen"), WindowValid = Flag(row, "timer_window_valid"),
                ChallengePassConfirmed = Flag(row, "challenge_pass_confirmed"), OfficialPassConfirmed = Flag(row, "official_pass_confirmed"),
                CompletionSource = Text(row, "completion_source") ?? "", DungeonId = Text(row, "dungeon_context_id"),
                Dungeon = row.Get("dungeon_context") is EvidenceArray pair ? new(((EvidenceText)pair.Items[0]).Value, ((EvidenceText)pair.Items[1]).Value) : null,
                ObservedTimes = config.Get("observed_times") is EvidenceObject times
                    ? times.Fields.ToDictionary(pair => int.Parse(pair.Key), pair => (long)((EvidenceInteger)pair.Value).Value) : new Dictionary<int, long>(),
                EnemyCounts = enemies.ToArray(),
            };
            ReportLifecycle lifecycle = new(id => new("mapped-" + id, "关卡 " + id));
            var selected = lifecycle.Select(input, timer, ((EvidenceText)config.Get("text")).Value,
                config.Get("line_count") is EvidenceInteger count ? (int)count.Value : null);
            var current = selected.Timing;
            var projected = new Dictionary<string, object?>
            {
                ["timing"] = new Dictionary<string, object?>
                {
                    ["game_timer_start_ms"] = current.GameStartMs, ["game_timer_end_ms"] = current.GameEndMs,
                    ["game_timer_elapsed_ms"] = current.GameElapsedMs, ["game_timer_window_elapsed_ms"] = current.GameWindowElapsedMs,
                    ["official_timer_start_ms"] = current.OfficialStartMs, ["official_timer_end_ms"] = current.OfficialEndMs,
                    ["official_timer_elapsed_ms"] = current.OfficialElapsedMs, ["live_timer_elapsed_ms"] = current.LiveElapsedMs,
                    ["packet_timer_elapsed_ms"] = current.PacketElapsedMs, ["first_hit_hint_ms"] = current.FirstHitHintMs,
                    ["last_hit_hint_ms"] = current.LastHitHintMs, ["first_party_action_ms"] = current.FirstPartyActionMs,
                    ["timer_start_seen"] = current.StartSeen, ["timer_end_seen"] = current.EndSeen,
                    ["timer_window_valid"] = current.WindowValid, ["challenge_pass_confirmed"] = current.ChallengePassConfirmed,
                    ["official_pass_confirmed"] = current.OfficialPassConfirmed, ["completion_source"] = current.CompletionSource,
                    ["dungeon_context_id"] = current.DungeonId,
                    ["dungeon_context"] = current.Dungeon is { } dungeon ? new[] { dungeon.Key, dungeon.Name } : null,
                },
                ["hits"] = selected.Input.Baseline.Hits.Select(hit => hit.Evidence).ToArray(), ["records"] = selected.Input.Records,
                ["official_evidence"] = selected.OfficialEvidence?.ToEvidence(), ["observed_elapsed"] = selected.ObservedOfficialElapsedMs,
                ["duration_ms"] = selected.DurationMs, ["timeline_scale"] = selected.TimelineScale,
                ["window"] = selected.Window is { } window ? new Dictionary<string, object?>
                {
                    ["start_ms"] = window.StartMs, ["end_ms"] = window.EndMs, ["time_source"] = window.TimeSource,
                    ["zero_source"] = window.ZeroSource, ["has_game_timer"] = window.HasGameTimer,
                } : null,
                ["offsets"] = selected.Window is null ? [] : ((EvidenceArray)config.Get("offsets")).Items
                    .Cast<EvidenceInteger>().Select(value => selected.OffsetMs(value.Value, clamp: false)).ToArray(),
                ["rebuild_totals"] = selected.RebuildTotals,
            };
            var actual = FieldCases.Canonical(projected);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report lifecycle differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
