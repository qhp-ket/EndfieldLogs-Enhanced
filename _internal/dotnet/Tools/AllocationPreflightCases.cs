using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class AllocationPreflightCases
{
    private static EvidenceObject Object(EvidenceValue value) => value as EvidenceObject ?? new(new Dictionary<string, EvidenceValue>());
    private static Dictionary<string, EvidenceObject> Objects(EvidenceValue value) => Object(value).Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value);
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.Cast<EvidenceObject>().ToArray() : [];
    public static AllocationPreflight Create(EvidenceObject config)
    {
        var roots = Objects(config.Get("roots"));
        var numbers = Object(config.Get("numbers")).Fields.ToDictionary(pair => pair.Key, pair => CatalogValues.Text(pair.Value));
        EffectApproval approval = new(Object(config.Get("registry")), roots, numbers, new Dictionary<string, string>());
        EffectStructureCatalog structure = new(roots);
        EffectSpecificationCatalog specifications = new(approval, new(roots, Objects(config.Get("zones")), approval), structure);
        var mechanisms = Object(config.Get("mechanisms")).Fields.ToDictionary(pair => pair.Key, pair => Rows(pair.Value));
        return new(roots, approval, structure, specifications, new(approval, specifications, roots, new(Objects(config.Get("mappings")), mechanisms, numbers)));
    }
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        var cachedComparisons = 0;
        var compactComparisons = 0;
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            object? result;
            try
            {
                var gate = Create(config);
                var start = config.Get("start") is EvidenceInteger first ? first.Value : new BigInteger(1000);
                var end = config.Get("end") is EvidenceInteger last ? last.Value : new BigInteger(2000);
                if (config.Get("operation") is EvidenceText { Value: "classify" }) result = PacketBuffClassification.Classify(Object(config.Get("record")));
                else if (config.Get("operation") is EvidenceText { Value: "overlap" }) result = gate.Overlaps(Object(config.Get("record")), start, end);
                else
                {
                    var evaluated = gate.Build(Rows(config.Get("records")), Rows(config.Get("windows")), start, end,
                        Rows(config.Get("hits")), Rows(config.Get("unresolved_hits")), Rows(config.Get("unresolved_actions")));
                    result = new Dictionary<string, object?> { ["summary"] = evaluated.Summary, ["records"] = evaluated.Records };
                    var expected = FieldCases.Canonical(result);
                    foreach (var mode in new[] { 0, 1, 2 })
                    {
                        EffectRecordCache cache = new();
                        LiveHitAccountingCache hitCache = new();
                        var immutableHits = Rows(config.Get("hits")).Select(row => new ReportHitInput((EvidenceObject)FrozenEvidence.Capture(row),
                            new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
                        for (var repeat = 0; repeat < 2; repeat++)
                        {
                            hitCache.Update(immutableHits);
                            var records = Rows(config.Get("records")).Select(row => (EvidenceObject)EvidenceJson.Clone(row)).ToArray();
                            var reused = mode > 0 ? gate.BuildOwned(records, Rows(config.Get("windows")), start, end,
                                immutableHits.Select(hit => hit.Evidence).ToArray(), Rows(config.Get("unresolved_hits")), Rows(config.Get("unresolved_actions")), cache, hitCache.Blockers, readOnlyRecords: mode == 2)
                                : gate.Build(records, Rows(config.Get("windows")), start, end,
                                Rows(config.Get("hits")), Rows(config.Get("unresolved_hits")), Rows(config.Get("unresolved_actions")), cache);
                            var cachedActual = FieldCases.Canonical(new Dictionary<string, object?> { ["summary"] = reused.Summary, ["records"] = reused.Records });
                            if (!JsonNode.DeepEquals(expected, cachedActual)) throw new InvalidOperationException("Cached preflight changed fixed evidence: " + test["name"]);
                            var compact = gate.BuildSummaryOwned(records, Rows(config.Get("windows")), start, end,
                                Rows(config.Get("unresolved_hits")), Rows(config.Get("unresolved_actions")), cache, hitCache.BlockerCount);
                            foreach (var field in new[] { "ok", "checked_external_buff_count", "accepted_effect_buff_count", "accepted_non_rdps_buff_count", "blocker_count" })
                                if (!EvidenceJson.PythonEquals(evaluated.Summary.Get(field), compact.Summary.Get(field)))
                                    throw new InvalidOperationException("Compact preflight changed fixed count: " + test["name"] + "/" + field);
                            EvidenceObject Quality(EvidenceObject summary) => SnapshotQuality.Build(BuffEvidence.Object(("rdps_preflight", summary)), includeEvidence: false);
                            if (!JsonNode.DeepEquals(FieldCases.Canonical(evaluated.Records), FieldCases.Canonical(compact.Records))
                                || !JsonNode.DeepEquals(FieldCases.Canonical(Quality(evaluated.Summary)), FieldCases.Canonical(Quality(compact.Summary))))
                                throw new InvalidOperationException("Compact preflight changed record or quality evidence: " + test["name"]);
                            cachedComparisons++;
                            compactComparisons++;
                        }
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
        Console.WriteLine($"Allocation preflight differential: {results.Count} cases, {failed} differences; {cachedComparisons} public/owned cold/hot and {compactComparisons} compact comparisons");
        return failed == 0 ? 0 : 1;
    }
}
