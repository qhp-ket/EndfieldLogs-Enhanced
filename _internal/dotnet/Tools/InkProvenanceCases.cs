using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;

internal static class InkProvenanceCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    private static object Project(InkProvenanceResult result) => new Dictionary<string, object?> { ["hits"] = result.Hits, ["summary"] = result.Summary };
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
                var roots = ((EvidenceObject)config.Get("roots")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value);
                result = ((EvidenceText)config.Get("operation")).Value switch
                {
                    "profile" => InkProvenanceStream.VerifyProfile(config.Get("root") as EvidenceObject),
                    "weights" => InkProvenanceStream.RecordWeights((EvidenceObject)config.Get("source"), EndfieldLogs.Core.Effects.EffectIdentity.Float(config.Get("increment"))),
                    "apply" => Project(InkProvenanceStream.Apply(((EvidenceText)config.Get("text")).Value, Rows(config.Get("hits")), Rows(config.Get("records")), roots)),
                    "stream" => Stream(config, roots),
                    _ => throw new ArgumentException("Unknown ink fixture operation"),
                };
            }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException or InvalidDataException or KeyNotFoundException or DivideByZeroException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch
                { InvalidCastException => "TypeError", OverflowException => "OverflowError", InvalidDataException => "AttributeError", KeyNotFoundException => "KeyError", DivideByZeroException => "ZeroDivisionError", _ => "ValueError" } };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Ink provenance differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }

    private static object Stream(EvidenceObject config, IReadOnlyDictionary<string, EvidenceObject> roots)
    {
        var stream = new InkProvenanceStream(roots);
        List<object> results = [];
        foreach (var step in Rows(config.Get("steps")))
        {
            if (step.Get("reset") is EvidenceBoolean { Value: true }) stream.Reset();
            var lines = ((EvidenceArray)step.Get("lines")).Items.Cast<EvidenceArray>().Select(row =>
                new InkTraceLine(((EvidenceInteger)row.Items[0]).Value, ((EvidenceText)row.Items[1]).Value));
            results.Add(Project(stream.Advance(lines, Rows(step.Get("hits")), Rows(step.Get("records")))));
        }
        return results;
    }
}
