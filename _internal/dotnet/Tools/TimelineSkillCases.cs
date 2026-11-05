using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class TimelineSkillCases
{
    public static int Run(string input, string output)
    {
        var data = JsonNode.Parse(File.ReadAllText(input))!; JsonArray outcomes = [];
        foreach (var test in data["cases"]!.AsArray())
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = PythonSortedJson.Serialize(config); var report = (EvidenceObject)config.Get("snapshot"); var saved = (EvidenceObject)config.Get("saved");
            var blocks = TimelineSkills.Build(report);
            var actual = FieldCases.Canonical(new Dictionary<string, object?>
            {
                ["blocks"] = blocks.Select(block => new Dictionary<string, object?> { ["owner"] = block.Owner, ["start"] = block.Start, ["end"] = block.End,
                    ["name"] = block.Name, ["category"] = block.Category, ["key"] = block.Key, ["cast"] = block.Cast, ["events"] = block.Events }).ToArray(),
                ["owners"] = ((EvidenceArray)report.Get("participants")).Items.OfType<EvidenceObject>().Select(row => ((EvidenceText)row.Get("character_key")).Value).ToDictionary(owner => owner, owner =>
                {
                    var options = TimelineSkills.Options(blocks, owner); var lanes = TimelineSkills.Resolve(options, owner, saved.Get(owner));
                    return new Dictionary<string, object?> { ["options"] = options.Select(option => new Dictionary<string, object?> { ["key"] = option.Key, ["name"] = option.Name, ["category"] = option.Category }).ToArray(),
                        ["lanes"] = TimelineSkills.Encode(lanes) };
                }),
            });
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == PythonSortedJson.Serialize(config), ["actual"] = actual });
        }
        foreach (var test in data["labels"]!.AsArray())
        {
            var label = TimelineSkills.Label(test!["key"]!.GetValue<string>(), "回退");
            outcomes.Add(new JsonObject { ["name"] = "label-" + test["key"]!.GetValue<string>(), ["passed"] = label.Name == test["name"]!.GetValue<string>() && label.Category == test["category"]!.GetValue<string>() && label.Group == test["group"]!.GetValue<string>() });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Timeline skills differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
