using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class ReportEffectWindowCases
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
            EvidenceObject Resource(string key)=>(config.Get(key) as EvidenceObject ?? shared.Get(key) as EvidenceObject)!;
            Dictionary<string,EvidenceObject> Objects(string key)=>Resource(key).Fields.Where(row=>row.Value is EvidenceObject)
                .ToDictionary(row=>row.Key,row=>(EvidenceObject)row.Value);
            Dictionary<string,string> Strings(string key)=>Resource(key).Fields.ToDictionary(row=>row.Key,row=>((EvidenceText)row.Value).Value);
            var roots=Objects("roots");
            var numbers=Strings("numbers");
            var mechanisms=Resource("mechanisms").Fields.ToDictionary(row=>row.Key,
                row=>(IReadOnlyList<EvidenceObject>)((EvidenceArray)row.Value).Items.Cast<EvidenceObject>().ToArray());
            PacketBuffCatalog packets=new(Objects("mappings"),mechanisms,numbers);
            EffectApproval approval=new(Resource("registry"),roots,numbers,Strings("skills"));
            SemanticEffectCatalog semantics=new(roots,Objects("zones"),approval);
            EffectSpecificationCatalog specifications=new(approval,semantics,new(roots));
            var details=Objects("details");
            var semanticEntries=Objects("semantics");
            PacketEffectDisplayCatalog display=new(packets,new(semanticEntries,key=>details.GetValueOrDefault(key)));
            BuffLabelCatalog labels=new(semantics,new(packets,semanticEntries,Objects("classifier")),display);
            var suitBuffs=Resource("suit_buffs").Fields.ToDictionary(row=>row.Key,
                row=>(IReadOnlySet<string>)((EvidenceArray)row.Value).Items.Cast<EvidenceText>().Select(item=>item.Value).ToHashSet());
            var limits=Resource("weapon_limits").Fields.ToDictionary(row=>row.Key,row=>((EvidenceInteger)row.Value).Value);
            EffectWindowBuilder builder=new(roots,labels,specifications,new(approval,specifications,roots,packets),display,
                new(packets,suitBuffs),new(roots,semanticEntries,limits),approval,new(roots,numbers,approval));
            var suits=((EvidenceObject)config.Get("active_suits")).Fields.ToDictionary(row=>row.Key,
                row=>((EvidenceArray)row.Value).Items.Cast<EvidenceText>().Select(item=>item.Value).ToHashSet());
            var weapons=((EvidenceObject)config.Get("active_weapons")).Fields.ToDictionary(row=>row.Key,row=>((EvidenceText)row.Value).Value);
            var arts=((EvidenceObject)config.Get("arts")).Fields.ToDictionary(row=>row.Key,
                row=>row.Value is EvidenceInteger integer ? (double)integer.Value : ((EvidenceReal)row.Value).Value);
            object result;
            var ownedEqual = true;
            try
            {
                var built=builder.Build(((EvidenceArray)config.Get("records")).Items.Cast<EvidenceObject>().ToArray(),
                    ((EvidenceArray)config.Get("hits")).Items.Cast<EvidenceObject>().ToArray(),
                    ((EvidenceInteger)config.Get("last_hit_ms")).Value,arts,suits,weapons);
                result=new Dictionary<string,object?> { ["records"]=built.Records,["hits"]=built.Hits,["windows"]=built.Windows };
                foreach (var frozen in new[] { false, true })
                {
                    EffectRecordCache cache = new();
                    for (var repeat = 0; repeat < 2; repeat++)
                    {
                        EvidenceObject[] CopyRows(string key) => ((EvidenceArray)config.Get(key)).Items
                            .Select(row => (EvidenceObject)EvidenceJson.Clone(row)).ToArray();
                        var owned = builder.BuildOwned(CopyRows("records"), CopyRows("hits"),
                            ((EvidenceInteger)config.Get("last_hit_ms")).Value, arts, suits, weapons, cache, readOnlyRecords: frozen);
                        var ownedResult = new Dictionary<string,object?> { ["records"]=owned.Records,["hits"]=owned.Hits,["windows"]=owned.Windows };
                        ownedEqual &= JsonNode.DeepEquals(FieldCases.Canonical(result), FieldCases.Canonical(ownedResult));
                    }
                }
            }
            catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
            {
                result=new Dictionary<string,object?> { ["error"]=error switch
                {
                    KeyNotFoundException=>"KeyError",OverflowException=>"OverflowError",FormatException=>"ValueError",
                    InvalidDataException=>"AttributeError",_=>"TypeError",
                }};
            }
            var actual=FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                ["passed"]=ownedEqual && JsonNode.DeepEquals(actual,test["expected"]) && original==EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report window differential: {cases.Count} cases, {failed} differences");
        return failed==0 ? 0 : 1;
    }
}
