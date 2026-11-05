using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class ReportLoadoutCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(inputPath))!;
        var numbers=fixture["numbers"]!.AsObject().ToDictionary(pair=>pair.Key,pair=>pair.Value!.GetValue<string>());
        BattleLoadoutResolver resolver=new(numbers);
        JsonArray results=[];
        foreach(var test in fixture["cases"]!.AsArray())
        {
            var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before=EvidenceJsonSignature.Sorted(config);
            object result;
            try
            {
                if(config.Get("operation") is EvidenceText { Value:"sanitize" })
                    result=resolver.WithoutMismatchedWeaponSkills((EvidenceObject)config.Get("row"));
                else
                {
                    var groups=((EvidenceArray)config.Get("groups")).Items.Cast<EvidenceObject>().ToArray();
                    IReadOnlyDictionary<string,EvidenceObject> fallback=((EvidenceObject)config.Get("fallback")).Fields
                        .ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
                    if(config.Get("operation") is EvidenceText { Value:"resolve" })
                    {
                        var repaired=resolver.Repair(groups,fallback);
                        groups=repaired.Groups.ToArray();fallback=repaired.Fallback;
                    }
                    BigInteger? Integer(string key)=>config.Get(key) is EvidenceInteger integer ? integer.Value : null;
                    result=new Dictionary<string,object?> { ["groups"]=groups,["fallback"]=fallback,
                        ["selected"]=resolver.Select(groups,fallback,Integer("anchor_ms"),Integer("anchor_line_no")) };
                }
            }
            catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
            {
                result=new Dictionary<string,object?> { ["error"]=error switch
                { KeyNotFoundException=>"KeyError",OverflowException=>"OverflowError",FormatException=>"ValueError",InvalidDataException=>"AttributeError",_=>"TypeError" } };
            }
            var actual=FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && before==EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report loadout differential: {results.Count} cases, {failed} differences");
        return failed==0 ? 0 : 1;
    }
}
