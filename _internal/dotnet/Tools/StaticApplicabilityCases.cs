using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

internal static class StaticApplicabilityCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var cases=JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();JsonArray results=[];
        foreach(var test in cases)
        {
            var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original=EvidenceJsonSignature.Sorted(config);var hit=(EvidenceObject)config.Get("hit");
            object result;
            try
            {
                if(config.Get("attribute") is EvidenceObject attribute)
                    result=new Dictionary<string,object?> { ["applies"]=DamageAttributeApplicability.Evaluate(attribute.Get("attr_type"),
                        hit.Get("damage_decorate_mask"),hit.Get("static_damage_decorate_mask"),hit.Get("static_damage_decorate_mask_source")) };
                else
                {
                    var numeric=((EvidenceObject)config.Get("numeric_baseline")).Fields.ToDictionary(pair=>BigInteger.Parse(pair.Key),pair=>pair.Value);
                    var evaluation=StaticEntryApplicability.Evaluate((EvidenceObject)config.Get("entry"),hit,numeric);
                    result=new Dictionary<string,object?> { ["applies"]=evaluation.Applies,
                        ["quality_present"]=evaluation.UnresolvedCondition || hit.Fields.ContainsKey("rdps_unresolved_effect_conditions"),
                        ["quality"]=evaluation.UnresolvedCondition ? new EvidenceBoolean(true) : hit.Get("rdps_unresolved_effect_conditions") };
                }
            }
            catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
            {
                result=new Dictionary<string,object?> { ["error"]=error switch
                { OverflowException=>"OverflowError",FormatException=>"ValueError",InvalidDataException=>"AttributeError",_=>"TypeError" } };
            }
            var actual=FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && original==EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Static applicability differential: {results.Count} cases, {failed} differences");return failed==0 ? 0 : 1;
    }
}
