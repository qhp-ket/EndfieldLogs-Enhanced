using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportTimelineCases
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
            var hits = Rows(config.Get("hits")).Select(hit => new ReportHitInput(hit, new Dictionary<BigInteger, EvidenceValue>(),
                new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>())).ToArray();
            SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            var families = (EvidenceObject)config.Get("families");
            ReportTimeline timeline = new(identities, key => "name-" + key, key => "skill-" + key,
                key => (families.Get(key) as EvidenceText)?.Value, ((EvidenceObject)config.Get("roots")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value));
            var input = new ReportCalculationInput(new(new([], new Dictionary<string, EvidenceObject>()), hits, new Dictionary<string, HashSet<string>>()), Rows(config.Get("records")), [], []);
            var lifecycle = new ReportLifecycleResult(input, new ReportTimingInput { GameElapsedMs = ((EvidenceInteger)config.Get("duration")).Value },
                new(((EvidenceInteger)config.Get("start")).Value, ((EvidenceInteger)config.Get("end")).Value, "test", "test", config.Get("timer") is EvidenceBoolean { Value: true }), null, null, false);
            var sources = new ReportSourceInput(Rows(config.Get("casts")), [], [], [], new Dictionary<string, long>(), Rows(config.Get("atb")));
            var result = timeline.Build(hits, sources, lifecycle, Rows(config.Get("participants")),
                ((EvidenceArray)config.Get("roster")).Items.Cast<EvidenceText>().Select(value => value.Value).ToArray(), Rows(config.Get("windows")), input.Records);
            var actual = FieldCases.Canonical(new Dictionary<string, object?> { ["hits"] = result.Hits.Select(hit => hit.Evidence).ToArray(),
                ["events"] = result.Events, ["skills"] = result.RoleSkillStats, ["casts"] = result.Casts, ["atb"] = result.AtbEvents });
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report timeline differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
