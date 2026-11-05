using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectStackCases
{
    private static EvidenceObject Empty => new(new Dictionary<string, EvidenceValue>());
    private static Dictionary<string, EvidenceObject> Objects(EvidenceValue value) => value is EvidenceObject obj
        ? obj.Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) : [];
    private static string Text(EvidenceValue value) => value is EvidenceText text ? text.Value : "";

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(config);
            var roots = Objects(config.Get("roots"));
            var semantics = Objects(config.Get("semantics"));
            var limits = config.Get("weapon_limits") is EvidenceObject exact
                ? exact.Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceInteger)pair.Value).Value) : new Dictionary<string, BigInteger>();
            EffectStackPolicy policy = new(roots, semantics, limits);
            var windows = config.Get("windows") is EvidenceArray rows ? rows.Items.Cast<EvidenceObject>().ToArray() : [];
            var kind = test["kind"]!.GetValue<string>();
            object? result;
            try
            {
                if (kind == "load")
                {
                    using ResourceFixture fixture = new(test);
                    policy = EffectStackPolicy.Load(fixture.Files, roots);
                    result = ((EvidenceArray)config.Get("queries")).Items.Cast<EvidenceObject>().Select(query => new Dictionary<string, object?>
                    {
                        ["key"] = query.Get("key"), ["limit"] = policy.Limit(Text(query.Get("key")), query.Get("bb_values") as EvidenceObject),
                        ["unique"] = policy.IsUnique(Text(query.Get("key"))),
                    }).ToArray();
                }
                else if (kind == "select")
                {
                    var hit = (EvidenceObject)config.Get("hit");
                    var position = new EffectHitPosition((long)((EvidenceInteger)hit.Get("ts_ms")).Value,
                        hit.Get("line_no") is EvidenceInteger line ? (int)line.Value : null,
                        (hit.Get("packet_seq_id") as EvidenceInteger)?.Value, (hit.Get("packet_session_id") as EvidenceText)?.Value);
                    var selected = config.Get("indices") is EvidenceArray indices ? indices.Items.Cast<EvidenceInteger>().Select(value => (int)value.Value).ToArray() : null;
                    var state = EffectStackSelection.Select(hit, windows, position, policy, selected, config.Get("debug") is EvidenceBoolean { Value: true });
                    result = new Dictionary<string, object?> { ["hit"] = state.Hit, ["windows"] = state.Windows,
                        ["effects"] = state.EffectsAtHit.ToDictionary(pair => pair.Key, pair => pair.Value),
                        ["zones"] = state.UnresolvedZones.Order(PythonDisplay.CodePointComparer).ToArray(), ["ignored"] = state.IgnoredEffects };
                }
                else result = kind switch
                {
                    "limit" => policy.Limit(Text(config.Get("key")), config.Get("bb_values") as EvidenceObject),
                    "unique" => policy.IsUnique(Text(config.Get("key"))),
                    "food" => EffectStackPolicy.IsFoodPotion(Text(config.Get("key"))),
                    "group" => policy.Group((EvidenceObject)config.Get("window")).Fields,
                    "ordered" => EffectWindowSet.Ordered(windows),
                    "dedupe" => EffectWindowSet.Deduplicate(windows),
                    "apply" => EffectWindowSet.ApplyLimits(windows, policy),
                    _ => throw new InvalidDataException("Unknown stack case"),
                };
            }
            catch (Exception error) when (error is FormatException or OverflowException or InvalidCastException or InvalidDataException)
            {
                result = new Dictionary<string, object?> { ["error"] = error is OverflowException ? "OverflowError" : error is FormatException ? "ValueError"
                    : error is InvalidDataException ? "AttributeError" : "TypeError" };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Effect stack differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
