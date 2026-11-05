using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class PacketEffectDisplayCases
{
    public static int Run(string inputPath, string outputPath,bool labels=false)
    {
        var fixture = JsonNode.Parse(File.ReadAllText(inputPath))!;
        var shared = (EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        var cases = fixture["cases"]!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(config);
            var record = (EvidenceObject)config.Get("record");
            EvidenceObject Resource(string key) => (config.Get(key) as EvidenceObject ?? shared.Get(key) as EvidenceObject)!;
            Dictionary<string, EvidenceObject> Objects(string key) => Resource(key).Fields.Where(row => row.Value is EvidenceObject)
                .ToDictionary(row => row.Key, row => (EvidenceObject)row.Value);
            var mechanisms = Resource("mechanisms").Fields.ToDictionary(row => row.Key,
                row => (IReadOnlyList<EvidenceObject>)((EvidenceArray)row.Value).Items.Cast<EvidenceObject>().ToArray());
            var numbers = Resource("numbers").Fields.ToDictionary(row => row.Key,row => ((EvidenceText)row.Value).Value);
            var details = Objects("details");
            PacketBuffCatalog packets=new(Objects("mappings"),mechanisms,numbers);
            PacketEffectDisplayCatalog catalog = new(packets,new(Objects("semantics"), key => details.GetValueOrDefault(key)));
            object? Evaluate(Func<object?> action)
            {
                try { return action(); }
                catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
                {
                    return new Dictionary<string, object?> { ["error"] = error is OverflowException ? "OverflowError" : error is FormatException ? "ValueError" : error is InvalidDataException ? "AttributeError" : "TypeError" };
                }
            }
            object? result;
            if(labels)
            {
                var roots=Objects("roots");
                EffectApproval approval=new(Resource("registry"),roots,numbers,new Dictionary<string,string>());
                BuffLabelCatalog labelCatalog=new(new(roots,Objects("zones"),approval),new(packets,Objects("semantics"),Objects("classifier")),catalog);
                result=Evaluate(()=>
                {
                    var projection=labelCatalog.Collect(record);
                    return new Dictionary<string,object?> { ["record"]=projection.Record,["labels"]=projection.Labels };
                });
            }
            else result=new Dictionary<string,object?>
            {
                ["static"] = Evaluate(() => catalog.Static(record)), ["dynamic"] = Evaluate(() => catalog.Dynamic(record)),
                ["stack"] = Evaluate(() => catalog.StackLimit(record)),
            };
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual,test["expected"]) && original == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"{(labels ? "BUFF labels" : "Packet display")} differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
