using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class LoadoutSnapshotCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var context = EvidenceJson.Parse(test["context_json"]!.GetValue<string>()) as EvidenceObject;
            Dictionary<string, EvidenceObject> Objects(string key) => config.Get(key) is EvidenceObject obj
                ? obj.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) : [];
            Dictionary<string, string> Strings(string key) => config.Get(key) is EvidenceObject obj
                ? obj.Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value) : [];
            var names = Strings("names");
            var skills = new SkillIdentityCatalog(Strings("skills"), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            var parser = new LoadoutSnapshotParser(Objects("weapons"), Objects("equipment"), Objects("suits"), new(Objects("refinement")), skills, key => names.GetValueOrDefault(key));
            var squad = test["squad"] is JsonObject bindings ? bindings.ToDictionary(pair => pair.Key, pair => pair.Value!.GetValue<string>()) : null;
            var original = EvidenceJsonSignature.Sorted(config) + (context is null ? "null" : EvidenceJsonSignature.Sorted(context));
            JsonNode? result;
            try
            {
                var text = test["text"]!.GetValue<string>();
                var value = test["kind"]!.GetValue<string>() switch
                {
                    "slot" => parser.Slot(text),
                    "stats" => parser.Stats(text, context, squad, test["allow"]!.GetValue<bool>()),
                    "source" => (EvidenceValue)LoadoutSnapshotParser.SourceSkills(text),
                    "equips" => parser.InlineEquipment(text),
                    "suits" => parser.SuitCounts(text),
                    _ => throw new InvalidDataException("Unknown snapshot case"),
                };
                result = new JsonObject { ["value"] = FieldCases.Canonical(value), ["error"] = null };
            }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException)
            {
                result = new JsonObject { ["value"] = null, ["error"] = error is FormatException ? "ValueError" : error is OverflowException ? "OverflowError" : "TypeError" };
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = result,
                ["passed"] = JsonNode.DeepEquals(result, test["expected"])
                    && original == EvidenceJsonSignature.Sorted(config) + (context is null ? "null" : EvidenceJsonSignature.Sorted(context)) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Loadout snapshot differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
