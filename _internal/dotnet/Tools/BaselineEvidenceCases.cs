using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class BaselineEvidenceCases
{
    public static int Run(string inputPath,string outputPath)
    {
        var cases=JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results=[];
        var temporary=Path.Combine(Path.GetTempPath(),"endfield-baseline-evidence-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            foreach(var test in cases)
            {
                var config=(EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
                var before=EvidenceJsonSignature.Sorted(config);
                object? result;
                try
                {
                    switch(((EvidenceText)config.Get("operation")).Value)
                    {
                        case "hp": result=EnemyHpEvidence.Annotate(((EvidenceArray)config.Get("hits")).Items.Cast<EvidenceObject>().ToArray());break;
                        case "ratio": result=PythonIntegerDivision.Divide(((EvidenceInteger)config.Get("numerator")).Value,((EvidenceInteger)config.Get("denominator")).Value);break;
                        default:
                        {
                            var root=Path.Combine(temporary,results.Count.ToString(System.Globalization.CultureInfo.InvariantCulture));
                            Directory.CreateDirectory(root);
                            foreach(var (name,value) in ((EvidenceObject)config.Get("files")).Fields)
                            {
                                var path=Path.GetFullPath(Path.Combine(root,name));
                                if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Fixture path outside its temporary directory");
                                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                                File.WriteAllText(path,((EvidenceText)value).Value);
                            }
                            CharacterBaseStatCatalog catalog=new(new(root));
                            var lookups=((EvidenceArray)config.Get("queries")).Items.Cast<EvidenceObject>().Select(query=>
                                catalog.Get((query.Get("character") as EvidenceText)?.Value,query.Get("level") is EvidenceInteger level ? level.Value : null)).ToArray();
                            result=new Dictionary<string,object?> { ["catalog"]=catalog.Entries,["lookups"]=lookups };
                            break;
                        }
                    }
                }
                catch(Exception error) when(error is InvalidCastException or InvalidDataException or FormatException or OverflowException or KeyNotFoundException or DivideByZeroException)
                {
                    result=new Dictionary<string,object?> { ["error"]=error switch
                    {
                        KeyNotFoundException=>"KeyError",OverflowException=>"OverflowError",FormatException=>"ValueError",
                        InvalidDataException=>"AttributeError",DivideByZeroException=>"ZeroDivisionError",_=>"TypeError",
                    }};
                }
                var actual=FieldCases.Canonical(result);
                results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),["actual"]=actual,
                    ["passed"]=JsonNode.DeepEquals(actual,test["expected"]) && before==EvidenceJsonSignature.Sorted(config) });
            }
        }
        finally { Directory.Delete(temporary,recursive:true); }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed=results.Count(row=>!row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Baseline evidence differential: {results.Count} cases, {failed} differences");
        return failed==0 ? 0 : 1;
    }
}
