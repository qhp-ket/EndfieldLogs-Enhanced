using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectApprovalCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var record = (EvidenceObject)EvidenceJson.Parse(test["record_json"]!.GetValue<string>());
            EvidenceObject Section(string key) => config.Get(key) as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            Dictionary<string, string> Numbers(string key) => Section(key).Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal);
            EffectApproval approval = new(Section("registry"), Section("roots").Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value), Numbers("numbers"), Numbers("skills"));
            var originalConfig = EvidenceJsonSignature.Sorted(config);
            var originalRecord = EvidenceJsonSignature.Sorted(record);
            object? result = test["kind"]!.GetValue<string>() switch
            {
                "guard" => EffectApproval.MatchesGuard(Section("entry"), record),
                "allowed" => EffectApproval.BlackboardAllowed(Section("entry"), record),
                "keys" => EffectApproval.EffectBlackboardKeys(Section("entry")).Order(StringComparer.Ordinal).ToArray(),
                "registry" => EffectApprovalCatalog.Project(config.Get("registry"), config.Get("keyword")),
                _ => approval.Match(record, test["guard"]!.GetValue<bool>()),
            };
            var actual = FieldCases.Canonical(result);
            var repeated = true;
            if (test["kind"]!.GetValue<string>() == "match")
            {
                _ = approval.Match(record, !test["guard"]!.GetValue<bool>());
                repeated = JsonNode.DeepEquals(actual, FieldCases.Canonical(approval.Match(record, test["guard"]!.GetValue<bool>())));
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && repeated
                    && originalConfig == EvidenceJsonSignature.Sorted(config) && originalRecord == EvidenceJsonSignature.Sorted(record) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Effect approval differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
