using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

internal static class ReportBuffEventCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    public static int Run(string inputPath, string outputPath)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        var shared = (EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        JsonArray results = [];
        foreach (var test in fixture["cases"]!.AsArray())
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(config);
            object result;
            try
            {
                var kind = test["kind"]!.GetValue<string>();
                if (kind == "summaries") result = ReportBuffEvents.Summaries(Rows(config.Get("effects")));
                else if (kind == "segments") result = ReportBuffEvents.Segments(((EvidenceInteger)config.Get("start")).Value,
                    ((EvidenceInteger)config.Get("end")).Value, Rows(config.Get("static")), Rows(config.Get("dynamic")));
                else
                {
                    EvidenceObject Resource(string key) => (config.Get(key) as EvidenceObject ?? shared.Get(key) as EvidenceObject)!;
                    Dictionary<string, EvidenceObject> Objects(string key) => Resource(key).Fields.Where(row => row.Value is EvidenceObject)
                        .ToDictionary(row => row.Key, row => (EvidenceObject)row.Value);
                    Dictionary<string, string> Strings(string key) => Resource(key).Fields.ToDictionary(row => row.Key, row => ((EvidenceText)row.Value).Value);
                    var roots = Objects("roots");
                    var numbers = Strings("numbers");
                    var mechanisms = Resource("mechanisms").Fields.ToDictionary(row => row.Key,
                        row => (IReadOnlyList<EvidenceObject>)((EvidenceArray)row.Value).Items.Cast<EvidenceObject>().ToArray());
                    PacketBuffCatalog packets = new(Objects("mappings"), mechanisms, numbers);
                    EffectApproval approval = new(Resource("registry"), roots, numbers, Strings("skills"));
                    SemanticEffectCatalog semantic = new(roots, Objects("zones"), approval);
                    EffectSpecificationCatalog specifications = new(approval, semantic, new(roots));
                    var details = Objects("details");
                    var entries = Objects("semantics");
                    PacketEffectDisplayCatalog display = new(packets, new(entries, key => details.GetValueOrDefault(key)));
                    BuffLabelCatalog labels = new(semantic, new(packets, entries, Objects("classifier")), display);
                    ReportBuffEvents builder = new(roots, labels, specifications, new(approval, specifications, roots, packets));
                    var built = builder.Build(Rows(config.Get("records")), Rows(config.Get("windows")),
                        ((EvidenceInteger)config.Get("start")).Value, ((EvidenceInteger)config.Get("end")).Value);
                    result = new Dictionary<string, object?> { ["records"] = built.Records, ["events"] = built.Events };
                }
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch
                {
                    KeyNotFoundException => "KeyError", OverflowException => "OverflowError", FormatException => "ValueError",
                    InvalidDataException => "AttributeError", _ => "TypeError",
                } };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report BUFF detail differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
