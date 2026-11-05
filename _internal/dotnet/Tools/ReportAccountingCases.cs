using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class ReportAccountingCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            object? result;
            try
            {
                if (config.Get("operation") is EvidenceText { Value: "basis" })
                    result = DamageBasis.Build(Rows(config.Get("hits")), ((EvidenceObject)config.Get("totals")).Fields, ((EvidenceInteger)config.Get("total_damage")).Value);
                else
                {
                    var baselines = (EvidenceArray)config.Get("numeric_baselines");
                    var hits = Rows(config.Get("hits")).Select((hit, index) => new ReportHitInput(hit,
                        ((EvidenceObject)baselines.Items[index]).Fields.ToDictionary(pair => BigInteger.Parse(pair.Key), pair => pair.Value),
                        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
                    var detailed = new DebugHitDetails(AllocationPhaseCases.CreateAllocator(config)).Build(hits, Rows(config.Get("windows")), Rows(config.Get("records")));
                    result = new Dictionary<string, object?> { ["windows"] = detailed.Windows,
                        ["hits"] = detailed.Hits.Select(hit => new EvidenceObject(hit.Fields.Where(pair => pair.Key != "baseline").ToDictionary())).ToArray() };
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
        Console.WriteLine($"Report accounting differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
