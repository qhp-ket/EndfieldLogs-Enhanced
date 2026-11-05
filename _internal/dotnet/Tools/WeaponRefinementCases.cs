using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class WeaponRefinementCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var entry = (EvidenceObject)EvidenceJson.Parse(test!["entry_json"]!.GetValue<string>());
            var skills = EvidenceJson.Parse(test["skills_json"]!.GetValue<string>());
            var gem = EvidenceJson.Parse(test["gem_json"]!.GetValue<string>());
            var weapon = test["weapon"]!.GetValue<string>();
            WeaponRefinementRules rules = new(new Dictionary<string, EvidenceObject> { [weapon] = entry });
            var signature = EvidenceJsonSignature.Sorted(new EvidenceArray([entry, skills, gem]));
            JsonNode? result;
            try { result = new JsonObject { ["value"] = FieldCases.Canonical(rules.Infer(weapon, skills, gem)), ["error"] = null }; }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException)
            {
                result = new JsonObject { ["value"] = null, ["error"] = error is FormatException ? "ValueError" : error is OverflowException ? "OverflowError" : "TypeError" };
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = result,
                ["passed"] = JsonNode.DeepEquals(result, test["expected"]) && signature == EvidenceJsonSignature.Sorted(new EvidenceArray([entry, skills, gem])) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Weapon refinement differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
