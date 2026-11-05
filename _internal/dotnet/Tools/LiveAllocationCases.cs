using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveAllocationCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.Cast<EvidenceObject>().ToArray() : [];
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var basis = (EvidenceObject)config.Get("base");
            var roots = (basis.Get("roots") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) ?? [];
            DamageShareLedger ledger = new(AllocationPhaseCases.CreateAllocator(basis), roots);
            LiveAllocationCache cache = new();
            List<object> snapshots = [];
            foreach (var step in Rows(config.Get("steps")))
            {
                var baselines = ((EvidenceArray)step.Get("numeric_baselines")).Items.Cast<EvidenceObject>().ToArray();
                var hits = Rows(step.Get("hits")).Select((hit, index) => new ReportHitInput(hit,
                    baselines[index].Fields.ToDictionary(pair => BigInteger.Parse(pair.Key), pair => pair.Value),
                    new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
                var result = ledger.Compute(hits, Rows(step.Get("windows")), Rows(step.Get("records")), (step.Get("trace") as EvidenceText)?.Value, cache);
                var d = cache.Diagnostics;
                snapshots.Add(new Dictionary<string, object?> { ["hits"] = result.Hits.Select(input => new EvidenceObject(input.Evidence.Fields
                    .Where(pair => pair.Key != "baseline").ToDictionary())).ToArray(), ["windows"] = result.Windows, ["totals"] = result.Totals,
                    ["summary"] = result.InkSummary, ["maxima"] = cache.Maxima, ["diagnostics"] = new Dictionary<string, object?>
                    {
                        ["allocated_hits"] = d.AllocatedHits, ["reused_hits"] = d.ReusedHits, ["total_allocated_hits"] = d.TotalAllocatedHits,
                        ["total_reused_hits"] = d.TotalReusedHits, ["finalized_hits"] = d.FinalizedHits, ["pending_start_line"] = d.PendingStartLine,
                        ["replays"] = d.Replays, ["last_replay_reason"] = d.LastReplayReason, ["ink_replays"] = d.InkReplays, ["last_ink_replay_reason"] = d.LastInkReplayReason,
                    } });
            }
            var actual = FieldCases.Canonical(snapshots);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failures = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Live allocation differential: {results.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
