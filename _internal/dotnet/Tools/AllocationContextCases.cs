using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class AllocationContextCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var hit = (EvidenceObject)config.Get("hit");
            var units = ((EvidenceObject)config.Get("units")).Fields.ToDictionary(pair => BigInteger.Parse(pair.Key),
                pair => (IReadOnlyList<SkillDamageUnit>)((EvidenceArray)pair.Value).Items.Cast<EvidenceObject>()
                    .Select(unit => new SkillDamageUnit(unit.Get("index"), "", (unit.Get("damage_attribute_type") as EvidenceText)?.Value ?? "",
                        null, null, unit.Get("damage_calculation") as EvidenceObject)).ToArray());
            IReadOnlyList<EvidenceObject>? Rows(EvidenceValue value) => value is EvidenceNull ? null : ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
            var byTarget = (config.Get("by_target") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => Rows(pair.Value)!, StringComparer.Ordinal);
            var input = new AllocationEvidenceInput(new ReportHitInput(hit, new Dictionary<BigInteger, EvidenceValue>(),
                    new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>()), Rows(config.Get("windows"))!,
                Rows(config.Get("records")), byTarget, WindowIndices: (config.Get("indices") as EvidenceArray)?.Items
                    .Select(value => (int)((EvidenceInteger)value).Value).ToArray(), IncludeDebug: config.Get("debug") is EvidenceBoolean { Value: true });
            AllocationContextBuilder builder = new(new AttackDependenceClassifier(_ => units));
            object result;
            try
            {
                var state = builder.Prepare(input);
                result = new Dictionary<string, object?>
                {
                    ["hit"] = state.Hit, ["buff_windows"] = state.Windows, ["attacker_key"] = state.Attacker,
                    ["target_enemy_key"] = state.Target, ["hit_value"] = state.HitValue, ["hit_ts_ms"] = state.TimestampMs,
                    ["damage_element"] = state.Element, ["damage_school"] = state.School, ["arts_strength_damage_hit"] = state.ArtsStrength.Observed,
                    ["attack_kind"] = state.Attack.EvidenceKind, ["calculation"] = state.Attack.Calculation,
                    ["packet_modifier_uids"] = state.PacketModifiers, ["packet_attr_details"] = state.PacketAttributes,
                    ["hit_line_no"] = state.LineNumber, ["resistance_attr_type"] = state.ResistanceAttribute,
                    ["resistance_rows"] = state.ResistanceRows, ["effective_resistance"] = state.EffectiveResistance,
                    ["resistance_numerator"] = state.ResistanceNumerator, ["resistance_source"] = state.ResistanceSource,
                    ["attacker_modifier_uids"] = state.AttackerModifierUids.Order(PythonDisplay.CodePointComparer).ToArray(),
                    ["defender_modifier_uids"] = state.DefenderModifierUids.Order(PythonDisplay.CodePointComparer).ToArray(),
                    ["defender_allowed_effects"] = state.DefenderAllowedEffects.OrderBy(pair => pair.Zone, StringComparer.Ordinal)
                        .ThenBy(pair => pair.Element, StringComparer.Ordinal).Select(pair => new[] { pair.Zone, pair.Element }).ToArray(),
                    ["window_indices"] = state.WindowIndices, ["matched_packet_defender_effect_signatures"] = state.MatchedDefenderSignatures.Select(signature => signature.Parts).ToArray(),
                    ["active_target_buff_ids"] = state.ActiveTargetBuffIds.Order(PythonDisplay.CodePointComparer).ToArray(),
                };
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch { InvalidCastException => "TypeError",
                    InvalidDataException => "AttributeError", OverflowException => "OverflowError", _ => "ValueError" } };
            }
            var actual = FieldCases.Canonical(result);
            var expected = test["expected"]!.DeepClone();
            static void Sort(JsonNode? node)
            {
                if (node is not JsonObject obj || obj["matched_packet_defender_effect_signatures"] is not JsonArray signatures) return;
                obj["matched_packet_defender_effect_signatures"] = new JsonArray(signatures.OrderBy(row => row!.ToJsonString(), StringComparer.Ordinal).Select(row => row!.DeepClone()).ToArray());
            }
            Sort(actual); Sort(expected);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, expected) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Allocation context differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
