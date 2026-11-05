using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

internal static class AttackDependenceCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var hit = (EvidenceObject)config.Get("hit");
            var fallback = ((EvidenceObject)config.Get("units")).Fields.ToDictionary(pair => BigInteger.Parse(pair.Key),
                pair => (IReadOnlyList<SkillDamageUnit>)((EvidenceArray)pair.Value).Items.Cast<EvidenceObject>()
                    .Select(unit => new SkillDamageUnit(unit.Get("index"), "", (unit.Get("damage_attribute_type") as EvidenceText)?.Value ?? "",
                        null, null, unit.Get("damage_calculation") as EvidenceObject)).ToArray());
            var calls = new List<string>();
            var classifier = new AttackDependenceClassifier(skill => { calls.Add(skill); return fallback; });
            object result;
            try
            {
                var value = classifier.Classify(hit);
                result = new Dictionary<string, object?> { ["kind"] = value.EvidenceKind,
                    ["calculation"] = value.Calculation, ["calls"] = calls.ToArray() };
            }
            catch (Exception error) when (error is InvalidDataException or InvalidCastException or OverflowException or FormatException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch {
                    InvalidDataException => "AttributeError", InvalidCastException => "TypeError",
                    OverflowException => "OverflowError", _ => "ValueError" }, ["calls"] = calls.ToArray() };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Attack dependence differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
