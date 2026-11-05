using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class PacketEvidenceCases
{
    internal static EvidenceObject Hit(HitPacketEvidence hit)=>HitReportEvidence.Packet(hit);

    internal static object Project(PacketObservationState state) => new Dictionary<string,object?>
    {
        ["hits_by_seq"]=state.HitsBySequence.ToDictionary(pair => pair.Key,pair => Hit(pair.Value)),
        ["baseline_by_character"]=state.BaselinesByCharacter,
        ["packet_modifier_last_seen_by_uid"]=state.ModifierLastSeenByUid,
        ["poise_damage_events"]=state.PoiseDamage.Select(row => new Dictionary<string,object?>
        {
            ["line_no"]=row.LineNumber, ["ts_ms"]=row.TimestampMs, ["type"]="PoiseDamage", ["value"]=row.Value,
            ["current_value"]=row.CurrentValue, ["source"]=row.Source, ["source_int"]=row.SourceInteger,
            ["orig_source"]=row.OriginalSource, ["orig_source_int"]=row.OriginalSourceInteger,
        }).ToArray(),
    };

    public static int Run(string inputPath,string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            PacketObservationState state = new();
            JsonArray steps = [];
            foreach (var operation in test!["operations"]!.AsArray())
            {
                bool? handled = null;
                if (operation!["hit"] is JsonNode hit)
                {
                    var seq = BigInteger.Parse(hit["sequence"]!.ToJsonString(),System.Globalization.CultureInfo.InvariantCulture);
                    state.HitsBySequence[seq] = new(hit["character"]?.GetValue<string>(),
                        hit["packet_sequence"] is null ? null : BigInteger.Parse(hit["packet_sequence"]!.ToJsonString(),System.Globalization.CultureInfo.InvariantCulture),
                        hit["packet_session"]?.GetValue<string>());
                }
                else handled = state.Observe(operation["line"]!.GetValue<string>(),operation["number"]!.GetValue<int>(),operation["time"]!.GetValue<long>());
                steps.Add(FieldCases.Canonical(new Dictionary<string,object?> { ["handled"]=handled, ["state"]=Project(state) }));
            }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(), ["actual"]=steps,
                ["passed"]=JsonNode.DeepEquals(steps,test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Packet evidence differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
