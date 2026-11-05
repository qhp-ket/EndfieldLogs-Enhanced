using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class BuffClassificationCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(inputPath))!;
        var shared=(EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        var cases=fixture["cases"]!.AsArray();
        JsonArray results=[];
        foreach(var test in cases)
        {
            var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original=EvidenceJsonSignature.Sorted(config);
            var record=(EvidenceObject)config.Get("record");
            EvidenceObject Resource(string key)=>(config.Get(key) as EvidenceObject ?? shared.Get(key) as EvidenceObject)!;
            Dictionary<string,EvidenceObject> Objects(string key)=>Resource(key).Fields.Where(row=>row.Value is EvidenceObject)
                .ToDictionary(row=>row.Key,row=>(EvidenceObject)row.Value);
            var mechanisms=Resource("mechanisms").Fields.ToDictionary(row=>row.Key,
                row=>(IReadOnlyList<EvidenceObject>)((EvidenceArray)row.Value).Items.Cast<EvidenceObject>().ToArray());
            var numbers=Resource("numbers").Fields.ToDictionary(row=>row.Key,row=>((EvidenceText)row.Value).Value);
            PacketBuffCatalog packets=new(Objects("mappings"),mechanisms,numbers);
            BuffDisplayClassification classification=new(packets,Objects("semantics"),Objects("classifier"));
            var allowed=BuffLoadoutFilter.BuildSuitBuffs(Objects("skills"),Objects("semantics"),Objects("suits").OrderBy(row=>row.Key,PythonDisplay.CodePointComparer).Select(row=>row.Value));
            BuffLoadoutFilter filter=new(packets,allowed);
            var key=PythonDisplay.String(record.Get("event_key")) is var raw && record.Get("event_key") is not EvidenceNull ? raw : "";
            var source=(record.Get("source_character_key") as EvidenceText)?.Value;
            var activeSuits=(config.Get("active_suits") as EvidenceObject)?.Fields.ToDictionary(row=>row.Key,
                row=>((EvidenceArray)row.Value).Items.Cast<EvidenceText>().Select(item=>item.Value).ToHashSet(StringComparer.Ordinal));
            var weapons=(config.Get("active_weapons") as EvidenceObject)?.Fields.ToDictionary(row=>row.Key,row=>((EvidenceText)row.Value).Value);
            object? Evaluate(Func<object?> action)
            {
                try{return action();}
                catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
                {
                    return new Dictionary<string,object?> { ["error"]=error is OverflowException ? "OverflowError" : error is FormatException ? "ValueError" : error is InvalidDataException ? "AttributeError" : "TypeError" };
                }
            }
            var actual=FieldCases.Canonical(new Dictionary<string,object?>
            {
                ["noise"]=Evaluate(()=>BuffDisplayClassification.IsNoise(key)), ["ignore_rate"]=Evaluate(()=>BuffDisplayClassification.IgnoresRate(key)),
                ["ignore_record"]=Evaluate(()=>BuffDisplayClassification.IgnoresRecordRate(record)), ["packet_wrapper"]=Evaluate(()=>classification.IsPacketWrapper(record)),
                ["internal"]=Evaluate(()=>BuffDisplayClassification.IsInternalTrigger(record)), ["wrapper"]=Evaluate(()=>classification.IsEffectlessWrapper(record)),
                ["suit"]=Evaluate(()=>filter.MatchesSuit(key,source,activeSuits)), ["weapon"]=Evaluate(()=>filter.MatchesWeapon(key,source,weapons)),
                ["allowed"]=allowed.ToDictionary(row=>row.Key,row=>row.Value.Order(PythonDisplay.CodePointComparer).ToArray()),
            });
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(), ["actual"]=actual,
                ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && original==EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"BUFF classification differential: {cases.Count} cases, {failed} differences");
        return failed==0 ? 0 : 1;
    }
}
