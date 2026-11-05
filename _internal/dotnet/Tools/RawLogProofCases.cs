using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Integrity;

internal static class RawLogProofCases
{
    private static JsonNode Json(EvidenceValue value) => JsonNode.Parse(PythonSortedJson.Serialize(value, compact: true))!;
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            JsonNode actual;
            if (test["kind"]!.GetValue<string>() == "inspect")
            {
                var result = RawLogProofs.Inspect(((EvidenceText)config.Get("text")).Value, config.Get("sidecar") as EvidenceObject, "$sidecar");
                actual = new JsonObject
                {
                    ["verified"] = result.Verified, ["issues"] = JsonSerializer.SerializeToNode(result.Issues),
                    ["proof_path"] = result.ProofPath, ["proof_source"] = result.ProofSource,
                    ["proof"] = result.Proof is null ? null : Json(result.Proof), ["raw_content"] = result.RawContent,
                    ["computed"] = JsonSerializer.SerializeToNode(result.Computed, JsonContract.Options),
                };
            }
            else
            {
                var bytes = Convert.FromHexString(((EvidenceText)config.Get("data")).Value);
                actual = test["kind"]!.GetValue<string>() == "build"
                    ? Json(RawLogProofs.Build(bytes, ((EvidenceText)config.Get("file_name")).Value, ((EvidenceText)config.Get("exported_at")).Value, (EvidenceObject)config.Get("meta")))
                    : JsonSerializer.SerializeToNode(RawLogProofs.Verify(bytes, (EvidenceObject)config.Get("proof")), JsonContract.Options)!;
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!); File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Raw log integrity differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
