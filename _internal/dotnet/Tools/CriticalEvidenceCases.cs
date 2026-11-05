using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class CriticalEvidenceCases
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
            object projected;
            if (config.Get("operation") is EvidenceText { Value: "profile" })
            {
                var profile = CriticalEvidence.Profile(config.Get("root"));
                projected = new Dictionary<string, object?> { ["missing"] = profile.Missing, ["attributes"] = profile.Attributes, ["processors"] = profile.Processors };
            }
            else
            {
                var roots = ((EvidenceObject)config.Get("roots")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value);
                if (config.Get("operation") is EvidenceText { Value: "build" })
                    projected = CriticalEvidence.Build((EvidenceObject)config.Get("hit"), config.Get("observation") as EvidenceObject,
                        roots.ToDictionary(pair => pair.Key, pair => CriticalEvidence.Profile(pair.Value)), Rows(config.Get("windows")));
                else
                {
                    ReportCriticalEvidence report = new(roots, ((EvidenceObject)config.Get("numbers")).Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value));
                    var hits = Rows(config.Get("hits")).Select(hit => new ReportHitInput(hit, new Dictionary<BigInteger, EvidenceValue>(),
                        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
                    var result = report.Attach(hits, Rows(config.Get("records")), Rows(config.Get("windows")));
                    projected = new Dictionary<string, object?> { ["hits"] = result.Hits.Select(hit => hit.Evidence).ToArray(), ["windows"] = result.Windows };
                }
            }
            var actual = FieldCases.Canonical(projected);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Critical evidence differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
