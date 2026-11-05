using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Realtime;

internal static class DamageLedgerCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceNull ? [] : ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        var ownedComparisons = 0;
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            object? result;
            try
            {
                if (config.Get("operation") is EvidenceText { Value: "index" })
                {
                    var condition = new AllocationConditionIndex(Rows(config.Get("records")));
                    var windows = new AllocationWindowIndex(Rows(config.Get("windows")));
                    result = ((EvidenceArray)config.Get("queries")).Items.Cast<EvidenceArray>().Select(query => new Dictionary<string, object?>
                    {
                        ["conditions"] = condition.At(((EvidenceText)query.Items[0]).Value, ((EvidenceInteger)query.Items[1]).Value),
                        ["windows"] = windows.At(((EvidenceInteger)query.Items[1]).Value),
                    }).ToArray();
                }
                else
                {
                    var roots = (config.Get("roots") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) ?? [];
                    var baselines = (EvidenceArray)config.Get("numeric_baselines");
                    var hits = Rows(config.Get("hits")).Select((hit, index) => new ReportHitInput(hit,
                        ((EvidenceObject)baselines.Items[index]).Fields.ToDictionary(pair => BigInteger.Parse(pair.Key), pair => pair.Value),
                        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
                    var ledger = config.Get("resource_root") is EvidenceText root ? DamageShareLedger.Load(new ResourceFiles(root.Value))
                        : new DamageShareLedger(AllocationPhaseCases.CreateAllocator(config), roots);
                    var allocated = ledger.Compute(hits, Rows(config.Get("windows")),
                        config.Get("records") is EvidenceNull ? null : Rows(config.Get("records")), (config.Get("trace") as EvidenceText)?.Value);
                    result = new Dictionary<string, object?> { ["totals"] = allocated.Totals, ["windows"] = allocated.Windows, ["summary"] = allocated.InkSummary,
                        ["hits"] = allocated.Hits.Select(input => new EvidenceObject(input.Evidence.Fields.Where(pair => pair.Key != "baseline").ToDictionary())).ToArray() };
                    LiveAllocationCache cache = new();
                    LiveAllocationCache publicCache = new();
                    var immutable = hits.Select(hit => hit with { Evidence = (EvidenceObject)FrozenEvidence.Capture(hit.Evidence) }).ToArray();
                    for (var repeat = 0; repeat < 2; repeat++)
                    {
                        var reference = ledger.Compute(hits, Rows(config.Get("windows")), Rows(config.Get("records")),
                            (config.Get("trace") as EvidenceText)?.Value, publicCache);
                        // Cached hits bypass window evaluation in both paths; compare its original hot-window contract.
                        var expected = FieldCases.Canonical(new Dictionary<string, object?> { ["totals"] = reference.Totals,
                            ["windows"] = reference.Windows, ["summary"] = reference.InkSummary,
                            ["hits"] = reference.Hits.Select(input => new EvidenceObject(input.Evidence.Fields.Where(pair => pair.Key != "baseline").ToDictionary())).ToArray() });
                        var owned = ledger.ComputeOwned(immutable, Rows(config.Get("windows")), Rows(config.Get("records")),
                            (config.Get("trace") as EvidenceText)?.Value, cache, null, summary: true);
                        var actualOwned = FieldCases.Canonical(new Dictionary<string, object?> { ["totals"] = owned.Totals,
                            ["windows"] = owned.Windows, ["summary"] = owned.InkSummary,
                            ["hits"] = owned.Hits.Select(input => new EvidenceObject(input.Evidence.Fields.Where(pair => pair.Key != "baseline").ToDictionary())).ToArray() });
                        if (!JsonNode.DeepEquals(expected, actualOwned))
                        {
                            File.WriteAllText(outputPath + ".owned-failure.json", new JsonObject { ["name"] = test["name"]!.DeepClone(),
                                ["repeat"] = repeat, ["expected"] = expected?.DeepClone(), ["actual"] = actualOwned?.DeepClone() }.ToJsonString());
                            throw new InvalidOperationException("Immutable ledger changed fixed evidence: " + test["name"]);
                        }
                        ownedComparisons++;
                    }
                }
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch
                { InvalidCastException => "TypeError", InvalidDataException => "AttributeError", OverflowException => "OverflowError", KeyNotFoundException => "KeyError", _ => "ValueError" } };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Damage ledger differential: {results.Count} cases, {failed} differences; {ownedComparisons} immutable cold/hot comparisons");
        return failed == 0 ? 0 : 1;
    }
}
