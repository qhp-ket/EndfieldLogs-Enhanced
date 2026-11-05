using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class BattlePresentationCases
{
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>()); var before = PythonSortedJson.Serialize(config);
            EvidenceValue result;
            if (test["mode"]!.GetValue<string>() == "frame")
            {
                var events = ((EvidenceArray)config.Get("events")).Items.OfType<EvidenceObject>().ToArray();
                TimelineSkill skill = new("a", BattleEvidence.Number(config.Get("start"))!.Value, BattleEvidence.Number(config.Get("end"))!.Value, "技能", "战技", "skill", (EvidenceObject)config.Get("cast"), events);
                result = SkillFrameReference.For(skill, (EvidenceObject)config.Get("rules")) ?? (EvidenceValue)EvidenceNull.Value;
            }
            else result = new EvidenceArray(SkillComposition.Build((EvidenceObject)config.Get("snapshot"), ((EvidenceText)config.Get("character")).Value).Cast<EvidenceValue>().ToArray());
            var actual = FieldCases.Canonical(result);
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == PythonSortedJson.Serialize(config), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failed = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Battle presentation differential: {outcomes.Count} cases, {failed} differences"); return failed == 0 ? 0 : 1;
    }
}
