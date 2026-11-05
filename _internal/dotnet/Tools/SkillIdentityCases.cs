using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;

internal static class SkillIdentityCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        static Dictionary<string, string> Map(JsonNode value) => value.AsObject()
            .ToDictionary(pair => pair.Key, pair => pair.Value!.GetValue<string>(), StringComparer.Ordinal);
        var profiles = fixture["profiles"]!.AsObject().ToDictionary(pair => pair.Key, pair =>
            new RuntimeBuffDamageProfile(pair.Value!["actions"]!.AsObject().ToDictionary(action => action.Key, action =>
                (IReadOnlyList<DamageUnitIdentity>)action.Value!.AsArray().Select(unit => new DamageUnitIdentity(
                    unit!["damageAttribute"]?.GetValue<string>(), unit["element"]?.GetValue<string>(),
                    unit["index"] is null ? null : BigInteger.Parse(unit["index"]!.ToJsonString(), CultureInfo.InvariantCulture))).ToArray())),
            StringComparer.Ordinal);
        SkillIdentityCatalog catalog = new(Map(fixture["skills"]!), Map(fixture["buffs"]!), profiles);
        JsonArray results = [];
        var cases = fixture["cases"]!.AsArray();
        foreach (var test in cases)
        {
            var skill = test!["skill"]?.GetValue<string>();
            var owner = test["owner"]?.GetValue<string>();
            var action = test["action"] is null ? (BigInteger?)null : BigInteger.Parse(test["action"]!.ToJsonString(), CultureInfo.InvariantCulture);
            var index = test["index"] is null ? (BigInteger?)null : BigInteger.Parse(test["index"]!.ToJsonString(), CultureInfo.InvariantCulture);
            object? actual;
            if (test["kind"]!.GetValue<string>() == "character_skills")
            {
                var levels = catalog.ParseCharacterSkills(test["line"]!.GetValue<string>());
                actual = levels is null ? null : new object[] { levels.Owner, levels.Levels };
            }
            else actual = new Dictionary<string, object?>
            {
                ["runtime_number"]=SkillIdentityCatalog.RuntimeNumber(skill),
                ["canonical_skill"]=catalog.CanonicalSkill(skill,owner),
                ["canonical_buff"]=catalog.CanonicalBuffNumber(SkillIdentityCatalog.RuntimeNumber(skill),owner),
                ["packet_skill"]=catalog.CanonicalPacketSkill(skill),
                ["hit_skill"]=catalog.CanonicalHitSkill(skill,owner),
                ["runtime_buff"]=catalog.CanonicalRuntimeBuff(skill,owner,action,index),
                ["hit_from_context"]=catalog.HitFromTemplate(skill,owner,test["template"]?.GetValue<string>(),action,index),
                ["family"]=catalog.FamilyKey(skill,test["family"]?.GetValue<string>()),
                ["owner_domain"]=SkillIdentityCatalog.OwnerDomainMatches(owner,skill),
                ["character_family"]=SkillIdentityCatalog.CharacterFamilyMatches(owner,skill),
            };
            var canonical = FieldCases.Canonical(actual);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(), ["actual"]=canonical,
                ["passed"]=JsonNode.DeepEquals(canonical,test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Skill identity differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
