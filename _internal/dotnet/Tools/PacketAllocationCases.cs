using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class PacketAllocationCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var kind = test["kind"]!.GetValue<string>();
            EvidenceObject Object(string key) => (EvidenceObject)config.Get(key);
            HashSet<string> Uids() => new(((EvidenceArray)config.Get("uids")).Items.Select(PythonDisplay.String), StringComparer.Ordinal);
            object? result;
            try
            {
                switch (kind)
                {
                    case "allowed": result = PacketAllocationEvidence.AllowedAttributes((config.Get("tokens") as EvidenceArray)?.Items)
                        .OrderBy(pair => pair.Zone, StringComparer.Ordinal).ThenBy(pair => pair.Element, StringComparer.Ordinal)
                        .Select(pair => new[] { pair.Zone, pair.Element }).ToArray(); break;
                    case "bucket": result = PacketAllocationEvidence.Bucket(PythonDisplay.String(config.Get("zone")), config.Get("raw") as EvidenceObject); break;
                    case "uids": result = new Dictionary<string, object?> {
                        ["aliases"] = EffectIdentity.WindowUids(Object("window")).Order(PythonDisplay.CodePointComparer).ToArray(),
                        ["matches"] = PacketAllocationEvidence.MatchesUids(Object("window"), Uids()) }; break;
                    case "row": result = EffectIdentity.Row(Object("effect")).Parts; break;
                    case "guard": result = EffectIdentity.PacketGuard(Object("effect")).Parts; break;
                    case "condition": result = EffectIdentity.Condition(Object("effect")); break;
                    case "round": result = PythonDecimalRounding.Round(((EvidenceReal)config.Get("value")).Value, (int)((EvidenceInteger)config.Get("places")).Value); break;
                    case "active": result = PacketAllocationEvidence.ActiveTargetBuffs(Object("hit"), ((EvidenceArray)config.Get("records")).Items.Cast<EvidenceObject>(),
                        PythonDisplay.String(config.Get("side"))).Order(PythonDisplay.CodePointComparer).ToArray(); break;
                    default:
                        var match = PacketAllocationEvidence.MatchDefender(Object("hit"), ((EvidenceArray)config.Get("windows")).Items.Cast<EvidenceObject>().ToArray(), Uids());
                        result = new Dictionary<string, object?> { ["signatures"] = match.Signatures.Select(signature => signature.Parts).ToArray(), ["windows"] = match.Windows };
                        break;
                }
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch {
                    InvalidCastException => "TypeError", InvalidDataException => "AttributeError",
                    OverflowException => "OverflowError", _ => "ValueError" } };
            }
            var actual = FieldCases.Canonical(result);
            var expected = test["expected"]?.DeepClone();
            static void SortSignatures(JsonNode? node)
            {
                if (node is not JsonObject obj || obj["signatures"] is not JsonArray signatures) return;
                obj["signatures"] = new JsonArray(signatures.OrderBy(row => row!.ToJsonString(), StringComparer.Ordinal).Select(row => row!.DeepClone()).ToArray());
            }
            SortSignatures(actual); SortSignatures(expected);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, expected) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Packet allocation differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
