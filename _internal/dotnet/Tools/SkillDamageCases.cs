using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class SkillDamageCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            object result;
            if (test!["kind"]!.GetValue<string>() == "arts")
            {
                var input = (EvidenceObject)EvidenceJson.Parse(test["input"]!.ToJsonString());
                var classification = HitDamageClassification.ArtsStrength(input.Get("runtime"),
                    (input.Get("static") as EvidenceInteger)?.Value, (input.Get("source") as EvidenceText)?.Value,
                    input.Get("previous") is EvidenceBoolean { Value: true }, (input.Get("previous_source") as EvidenceText)?.Value);
                result = new Dictionary<string, object?>
                {
                    ["arts_strength_damage_observed"] = classification.Observed,
                    ["arts_strength_damage_kind"] = classification.Kind,
                    ["arts_strength_damage_source"] = classification.Source,
                    ["arts_strength_damage_factor_count"] = classification.FactorCount,
                };
            }
            else
            {
                var definition = EvidenceJson.Parse(test["profile_json"]!.GetValue<string>()) as EvidenceObject;
                var canonical = test["canonical"]!.GetValue<string>();
                var actions = definition?.Get("actions") is EvidenceObject entries ? entries.Fields.ToDictionary(pair => pair.Key,
                    pair => (IReadOnlyList<EvidenceObject>)((EvidenceArray)pair.Value).Items.Cast<EvidenceObject>().ToArray(), StringComparer.Ordinal) : [];
                var profile = definition is null ? null : new OfficialDamageProfile(canonical, definition, actions);
                var units = SkillDamageUnits.Project(canonical, profile, EvidenceJson.Parse(test["root_json"]!.GetValue<string>()) as EvidenceObject);
                static object Unit(SkillDamageUnit unit) => new Dictionary<string, object?>
                {
                    ["index"] = unit.Index, ["element"] = unit.Element, ["damage_type"] = unit.Element,
                    ["damage_attribute_type"] = unit.Attribute, ["damage_decorate_mask"] = unit.StaticMask,
                    ["damage_decorate_mask_source"] = unit.StaticMaskSource, ["damage_calculation"] = unit.Calculation,
                };
                var classifications = test["queries"]!.AsArray().Select(query =>
                {
                    var element = HitDamageClassification.Element(units, TraceFields.OptionalInteger(query![0]?.GetValue<string>()),
                        TraceFields.OptionalInteger(query[1]?.GetValue<string>()));
                    return new Dictionary<string, object?> { ["element"] = element, ["school"] = HitDamageClassification.School(element) };
                }).ToArray();
                result = new Dictionary<string, object?>
                {
                    ["units"] = units.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value.Select(Unit).ToArray()),
                    ["classifications"] = classifications,
                };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Skill damage differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
