using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectConditionCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var effect = (EvidenceObject)EvidenceJson.Parse(test!["effect_json"]!.GetValue<string>());
            var hit = (EvidenceObject)EvidenceJson.Parse(test["hit_json"]!.GetValue<string>());
            var root = EvidenceJson.Parse(test["root_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(effect) + EvidenceJsonSignature.Sorted(hit) + EvidenceJsonSignature.Sorted(root);
            var kind = test["kind"]!.GetValue<string>();
            string? Optional(string name) => (effect.Get(name) as EvidenceText)?.Value;
            JsonNode? actual;
            try
            {
                object? result = kind switch
                {
                    "failure" => EffectConditions.Failure(effect, hit),
                    "elements" => EffectConditions.DamageTypeElements(effect.Get("condition")).Order(PythonDisplay.CodePointComparer).ToArray(),
                    "applies" => EffectConditions.AppliesToHit(effect, Optional("damage_element"), Optional("damage_school")),
                    "filter" => EffectConditions.ElementFilter(Optional("element"), Optional("damage_element"), Optional("damage_school")),
                    "attach" => EffectConditions.AttachBlackboardCondition(effect, Optional("bb_key")),
                    "normalize" => ModifierConditionCatalog.NormalizeDamageType(effect.Get("value")),
                    "decode" => ModifierConditionCatalog.Decode(root as EvidenceObject),
                    _ => throw new InvalidDataException("Unknown effect condition case"),
                };
                actual = FieldCases.Canonical(result);
            }
            catch (Exception error) when (error is InvalidCastException or ArgumentException)
            {
                actual = new JsonObject { ["error"] = "TypeError" };
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original ==
                    EvidenceJsonSignature.Sorted(effect) + EvidenceJsonSignature.Sorted(hit) + EvidenceJsonSignature.Sorted(root) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Effect condition differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
