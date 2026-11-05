using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class ReportBaselineCases
{
    private static object Project(StaticBaselineResult baseline)
    {
        // Python's empty sum is integer zero; nonempty sums are floating point even at zero.
        var arts=baseline.StaticArtsStrength.ToDictionary(pair=>pair.Key,pair=>
            ((EvidenceArray)baseline.Loadouts[pair.Key].Get("static_arts_strength_entries")).Items.Count==0
                ? (EvidenceValue)new EvidenceInteger(0) : new EvidenceReal(pair.Value));
        return new Dictionary<string,object?> { ["loadouts"]=baseline.Loadouts,["stale"]=baseline.LoadoutStale,
            ["arts_strength"]=arts,["hits"]=baseline.Hits.Select(hit=>hit.Evidence).ToArray(),
            ["active_suits"]=baseline.ActiveSuits.ToDictionary(pair=>pair.Key,pair=>pair.Value.Order(PythonDisplay.CodePointComparer).ToArray()),
            ["active_weapons"]=baseline.ActiveWeapons };
    }

    public static int Run(string inputPath,string outputPath)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(inputPath))!;
        var resources=(EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        var temporary=Path.Combine(Path.GetTempPath(),"endfield-report-baseline-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);JsonArray results=[];var ownedComparisons=0;
        try
        {
            var builders=new Dictionary<string,StaticBaselineBuilder>(StringComparer.Ordinal);
            foreach(var (name,input) in resources.Fields)
            {
                var shared=(EvidenceObject)input;var root=Path.Combine(temporary,name);Directory.CreateDirectory(root);
                foreach(var (relative,value) in ((EvidenceObject)shared.Get("files")).Fields)
                {
                    var path=Path.GetFullPath(Path.Combine(root,relative));
                    if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Fixture path outside temporary root");
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllText(path,((EvidenceText)value).Value);
                }
                Dictionary<string,EvidenceObject> Objects(string key)=>((EvidenceObject)shared.Get(key)).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
                var numbers=((EvidenceObject)shared.Get("numbers")).Fields.ToDictionary(pair=>pair.Key,pair=>((EvidenceText)pair.Value).Value);
                builders[name]=new(new(numbers),new(Objects("equipment"),Objects("weapons"),numbers,(EvidenceObject)shared.Get("catalog")),
                    new((EvidenceObject)shared.Get("arts_catalog"),Objects("weapons"),numbers),new(new(root)));
            }
            foreach(var test in fixture["cases"]!.AsArray())
            {
                var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
                var signature=EvidenceJsonSignature.Sorted(config)+EvidenceJsonSignature.Sorted(resources);
                object result;
                try
                {
                    var groups=((EvidenceArray)config.Get("groups")).Items.Cast<EvidenceObject>().ToArray();
                    var fallback=((EvidenceObject)config.Get("fallback")).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
                    var suits=((EvidenceObject)config.Get("active_suits")).Fields.ToDictionary(pair=>pair.Key,
                        pair=>((EvidenceArray)pair.Value).Items.Cast<EvidenceText>().Select(value=>value.Value).ToHashSet(StringComparer.Ordinal));
                    var hits=((EvidenceArray)config.Get("hits")).Items.Cast<EvidenceObject>().Select(wrapper=>
                    {
                        var fields=new Dictionary<string,EvidenceValue>(((EvidenceObject)wrapper.Get("evidence")).Fields,StringComparer.Ordinal);
                        var numeric=wrapper.Get("numeric") as EvidenceObject ?? new(new Dictionary<string,EvidenceValue>());
                        foreach(var (key,value) in numeric.Fields)
                        {
                            // Canonical JSON displays both original key types as text; calculation still uses the typed maps below.
                            var visible=fields.GetValueOrDefault(key) as EvidenceObject;
                            var merged=new Dictionary<string,EvidenceValue>(visible?.Fields ?? new Dictionary<string,EvidenceValue>(),StringComparer.Ordinal);
                            foreach(var (attribute,amount) in ((EvidenceObject)value).Fields) merged[attribute]=amount;
                            fields[key]=new EvidenceObject(merged);
                        }
                        IReadOnlyDictionary<BigInteger,EvidenceValue> Attributes(string key)=>numeric.Get(key) is EvidenceObject values
                            ? values.Fields.ToDictionary(pair=>BigInteger.Parse(pair.Key),pair=>pair.Value) : new Dictionary<BigInteger,EvidenceValue>();
                        return new ReportHitInput(new(fields),Attributes("baseline"),Attributes("attacker_stats_basic_attrs"),Attributes("attacker_stats_attrs"));
                    }).ToArray();
                    var builder=builders[((EvidenceText)config.Get("resource_id")).Value];
                    var firstHit=((EvidenceInteger)config.Get("first_hit_ms")).Value;
                    result=Project(builder.Prepare(new(new(groups,fallback),hits,suits),firstHit));
                    var frozen=hits.Select(hit=>hit with
                    {
                        Evidence=(EvidenceObject)FrozenEvidence.Capture(hit.Evidence),
                        Baseline=FrozenEvidence.CaptureNumbers(hit.Baseline),
                        BasicAttributes=FrozenEvidence.CaptureNumbers(hit.BasicAttributes),
                        Attributes=FrozenEvidence.CaptureNumbers(hit.Attributes),
                    }).ToArray();
                    LiveHitPreparationCache cache=new();
                    for(var pass=0;pass<2;pass++)
                    {
                        var owned=builder.PrepareOwned(new(new(groups,fallback),frozen,suits),firstHit,cache);
                        if(!JsonNode.DeepEquals(FieldCases.Canonical(Project(owned)),FieldCases.Canonical(result)))
                            throw new InvalidOperationException($"Cached baseline differs: {test["name"]}, pass {pass}");
                        ownedComparisons++;
                    }
                }
                catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException)
                {
                    result=new Dictionary<string,object?> { ["error"]=error switch
                    { KeyNotFoundException=>"KeyError",OverflowException=>"OverflowError",FormatException=>"ValueError",InvalidDataException=>"AttributeError",_=>"TypeError" } };
                }
                var actual=FieldCases.Canonical(result);
                results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                    ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && signature==EvidenceJsonSignature.Sorted(config)+EvidenceJsonSignature.Sorted(resources) });
            }
        }
        finally { Directory.Delete(temporary,recursive:true); }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report baseline differential: {results.Count} cases, {failed} differences; {ownedComparisons} immutable cold/hot comparisons");return failed==0 ? 0 : 1;
    }
}
