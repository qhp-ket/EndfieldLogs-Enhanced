using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;

internal static class EvidenceJsonCases
{
    private static string Units(string value) => string.Concat(value.Select(unit => ((int)unit).ToString("x4",CultureInfo.InvariantCulture)));
    private static JsonArray Canonical(EvidenceValue value) => value switch
    {
        EvidenceNull => new("null"),
        EvidenceBoolean flag => new("bool",flag.Value),
        EvidenceInteger integer => new("int",integer.Value.ToString(CultureInfo.InvariantCulture)),
        EvidenceReal real => new("f64",BitConverter.DoubleToUInt64Bits(real.Value).ToString("x16",CultureInfo.InvariantCulture)),
        EvidenceText text => new("text",Units(text.Value)),
        EvidenceArray array => new("array",new JsonArray(array.Items.Select(item => (JsonNode)Canonical(item)).ToArray())),
        EvidenceObject obj => new("object",new JsonArray(obj.Fields.OrderBy(pair => Units(pair.Key),StringComparer.Ordinal)
            .Select(pair => (JsonNode)new JsonArray(Units(pair.Key),Canonical(pair.Value))).ToArray())),
        _ => throw new InvalidDataException("Unknown evidence value"),
    };

    public static int Run(string inputPath,string outputPath)
    {
        var fixtures = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        EvidenceJson.ReadOnlyContext shared = new();
        FrozenEvidence.Context snapshots = new();
        foreach (var fixture in fixtures)
        {
            JsonNode? Evaluate(Func<string, EvidenceValue> parse)
            {
                try
                {
                    var parsed = parse(fixture!["input"]!.GetValue<string>());
                    return fixture["diagnostic"]?.GetValue<bool>() == true ? null : fixture["display"] is JsonNode display
                        ? JsonValue.Create(Units(display.GetValue<string>() == "repr" ? PythonDisplay.Repr(parsed) : PythonDisplay.String(parsed)))
                        : fixture["other"] is null ? Canonical(parsed)
                        : JsonValue.Create(EvidenceJson.PythonEquals(parsed,parse(fixture["other"]!.GetValue<string>())));
                }
                catch (FormatException failure) { return fixture!["diagnostic"]?.GetValue<bool>() == true
                    ? JsonValue.Create(failure.Message) : new JsonObject { ["invalid"]=true }; }
            }
            var actual = Evaluate(EvidenceJson.Parse); var readOnly = Evaluate(EvidenceJson.ParseReadOnly);
            var sharedReadOnly = Evaluate(shared.Parse);
            var utf8Resource = Evaluate(text => EvidenceJson.ParseReadOnlyUtf8(new UTF8Encoding(false, true).GetBytes(text)));
            var compactSnapshot = Evaluate(text => snapshots.Capture(EvidenceJson.Parse(text)));
            results.Add(new JsonObject { ["name"]=fixture!["name"]!.GetValue<string>(), ["actual"]=actual,
                ["read_only_actual"]=readOnly, ["shared_read_only_actual"]=sharedReadOnly,
                ["utf8_resource_actual"]=utf8Resource,
                ["compact_snapshot_actual"]=compactSnapshot,
                ["passed"]=JsonNode.DeepEquals(actual,fixture["expected"]) && JsonNode.DeepEquals(readOnly,fixture["expected"])
                    && JsonNode.DeepEquals(sharedReadOnly,fixture["expected"]) && JsonNode.DeepEquals(compactSnapshot,fixture["expected"])
                    && JsonNode.DeepEquals(utf8Resource,fixture["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Evidence JSON differential: {fixtures.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
