using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class StaticMultiplierCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(inputPath))!;
        var shared=(EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        JsonArray results=[];
        foreach(var test in fixture["cases"]!.AsArray())
        {
            var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original=EvidenceJsonSignature.Sorted(config)+EvidenceJsonSignature.Sorted(shared);
            EvidenceObject Resource(string key)=>(config.Fields.GetValueOrDefault(key) ?? shared.Get(key)) as EvidenceObject ?? (EvidenceObject)EvidenceJson.Parse("{}");
            Dictionary<string,EvidenceObject> Objects(string key)=>Resource(key).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
            var numbers=Resource("numbers").Fields.ToDictionary(pair=>pair.Key,pair=>((EvidenceText)pair.Value).Value);
            StaticMultiplierDeriver deriver=new(Objects("equipment"),Objects("weapons"),numbers,Resource("catalog"));
            object result;
            try
            {
                var derived=deriver.Derive((EvidenceObject)config.Get("row"));
                result=new Dictionary<string,object?> { ["row"]=derived.Loadout,["entries"]=derived.Entries };
            }
            catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
            {
                result=new Dictionary<string,object?> { ["error"]=error switch
                { KeyNotFoundException=>"KeyError",OverflowException=>"OverflowError",FormatException=>"ValueError",InvalidDataException=>"AttributeError",_=>"TypeError" } };
            }
            var actual=FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && original==EvidenceJsonSignature.Sorted(config)+EvidenceJsonSignature.Sorted(shared) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Static multiplier differential: {results.Count} cases, {failed} differences");
        return failed==0 ? 0 : 1;
    }
}
