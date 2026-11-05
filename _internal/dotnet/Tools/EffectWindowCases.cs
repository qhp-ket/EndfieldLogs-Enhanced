using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectWindowCases
{
    private static readonly HashSet<string> StateKeys = ["_enable_state_unobserved_at_hit", "_effect_state_unresolved_at_hit", "_buff_enabled_at_hit",
        "rdps_snapshot_order_unresolved", "rdps_unresolved_enable_evidence", "rdps_invalid_dynamic_evaluation"];
    private static EvidenceObject Select(EvidenceObject window, bool state) => new(window.Fields.Where(pair => StateKeys.Contains(pair.Key) == state)
        .ToDictionary(pair => pair.Key, pair => pair.Value));

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var window = (EvidenceObject)EvidenceJson.Parse(test!["window_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(window);
            var immutable = EvidenceJsonSignature.Sorted(Select(window, false));
            var unchanged = true;
            var current = window;
            JsonArray steps = [];
            foreach (var position in test["positions"]!.AsArray())
            {
                var sequence = position!["packet_seq_id"] is { } value ? BigInteger.Parse(value.ToJsonString()) : (BigInteger?)null;
                var hit = new EffectHitPosition(position["hit_ts_ms"]!.GetValue<long>(), position["line_no"]?.GetValue<int>(),
                    sequence, position["packet_session_id"]?.GetValue<string>());
                var result = EffectWindowEvaluation.At(current, hit);
                current = result.Window;
                unchanged &= immutable == EvidenceJsonSignature.Sorted(Select(current, false));
                steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["effects"] = result.Effects, ["state"] = Select(current, true) }));
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = steps,
                ["passed"] = JsonNode.DeepEquals(steps, test["expected"]) && unchanged && original == EvidenceJsonSignature.Sorted(window) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Effect window differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
