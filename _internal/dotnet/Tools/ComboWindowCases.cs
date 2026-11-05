using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class ComboWindowCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        var roots = (EvidenceObject)EvidenceJson.Parse(fixture["roots_json"]!.GetValue<string>());
        var registry = (EvidenceObject)EvidenceJson.Parse(fixture["registry_json"]!.GetValue<string>());
        var cases = fixture["cases"]!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(config);
            var actualRoots = (config.Get("roots") as EvidenceObject ?? roots).Fields.ToDictionary(row => row.Key, row => (EvidenceObject)row.Value);
            var numbers = (config.Get("numbers") as EvidenceObject)?.Fields.ToDictionary(row => row.Key, row => ((EvidenceText)row.Value).Value) ?? [];
            EffectApproval approval = new(config.Get("registry") as EvidenceObject ?? registry, actualRoots, numbers, new Dictionary<string, string>());
            SpecialComboWindowBuilder builder = new(actualRoots, numbers, approval);
            object result;
            try
            {
                var built = builder.Build(((EvidenceArray)config.Get("hits")).Items.Cast<EvidenceObject>().ToArray(),
                    ((EvidenceArray)config.Get("records")).Items.Cast<EvidenceObject>().ToArray());
                result = new Dictionary<string, object?> { ["hits"] = built.Hits, ["windows"] = built.Windows };
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
            {
                result = new Dictionary<string, object?> { ["error"] = error is OverflowException ? "OverflowError" : error is FormatException ? "ValueError" : error is InvalidDataException ? "AttributeError" : "TypeError" };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Combo window differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
