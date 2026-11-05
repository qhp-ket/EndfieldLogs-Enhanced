using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Input;

internal static class InputEvidenceCases
{
    private static JsonNode Json(EvidenceValue value) => JsonNode.Parse(PythonSortedJson.Serialize(value))!;
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        var root = Directory.CreateTempSubdirectory("endfield-input-reference-");
        try
        {
            var path = Path.Combine(root.FullName, "trace_20261028.input.jsonl"); var trace = Path.Combine(root.FullName, "trace_20261028.log");
            foreach (var test in cases)
            {
                var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
                File.WriteAllBytes(path, Convert.FromHexString(((EvidenceText)config.Get("data")).Value)); File.WriteAllText(trace, ((EvidenceText)config.Get("source")).Value, new UTF8Encoding(false));
                JsonNode actual;
                try
                {
                    if (test["kind"]!.GetValue<string>() == "archive")
                    {
                        InputArchive archive = new(path, config.Get("settings")); Dictionary<string, int> counts = [];
                        var raw = archive.RawRange(BigInteger.Parse("1793116800000000000"), BigInteger.Parse("1793116801000000000"), InputInterpretationSettings.Normalize(config.Get("settings")), counts);
                        actual = new JsonObject
                        {
                            ["header"] = Json(archive.Header), ["warnings"] = JsonSerializer.SerializeToNode(archive.Warnings), ["devices"] = Json(archive.Devices),
                            ["input_counts"] = JsonSerializer.SerializeToNode(archive.InputCounts), ["digest"] = archive.Digest is { } digest ? Json(digest) : null,
                            ["actions"] = new JsonArray(archive.Actions.Select(action => Json(action.ToEvidence())).ToArray()), ["wall_ordered"] = archive.WallOrdered,
                            ["raw"] = new JsonArray(raw.Select(Json).ToArray()), ["selected_counts"] = JsonSerializer.SerializeToNode(counts), ["verify"] = archive.VerifyTrace(trace),
                        };
                    }
                    else
                    {
                        InputEvidenceLoader loader = new(TimeZoneInfo.CreateCustomTimeZone("reference", TimeSpan.FromHours(8), "reference", "reference"));
                        var slots = ((EvidenceObject)config.Get("manual_slots")).Fields.ToDictionary(pair => int.Parse(pair.Key), pair => ((EvidenceText)pair.Value).Value);
                        var settings = config.Get("settings") as EvidenceObject ?? (EvidenceObject)EvidenceJson.Parse("{}");
                        var result = loader.Load(new([path], trace, (EvidenceObject)config.Get("battle"), settings,
                            config.Get("offset_ms") is EvidenceReal real ? real.Value : (double)((EvidenceInteger)config.Get("offset_ms")).Value,
                            slots, Verify: ((EvidenceBoolean)config.Get("verify")).Value));
                        actual = Json(result); actual["paths"] = new JsonArray("$input");
                    }
                }
                catch (Exception error) when (error is InvalidDataException or ArgumentException or FormatException or OverflowException)
                { actual = new JsonObject { ["error"] = error.Message }; }
                outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
            }
        }
        finally { root.Delete(recursive: true); }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Input evidence differential: {outcomes.Count} cases, {failures} differences"); return failures == 0 ? 0 : 1;
    }
}
