using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Native.Input;

internal static class InputBackendCases
{
    private static JsonNode Json(NativeInputReport report)
    { var fields = report.Fields.ToDictionary(); fields["type"] = report.Type; return JsonSerializer.SerializeToNode(fields)!; }
    public static int Run(string input, string output)
    {
        var cases = JsonNode.Parse(File.ReadAllText(input))!.AsArray(); JsonArray outcomes = [];
        foreach (var test in cases)
        {
            var kind = test!["kind"]!.GetValue<string>(); JsonArray actual = [], events = [];
            void Emit(NativeInputReport report) => events.Add(Json(report));
            if (kind == "raw")
            {
                RawInputDecoder decoder = new(Emit);
                foreach (var operation in test["operations"]!.AsArray())
                {
                    var device = operation!["device"]!.GetValue<string>();
                    if (operation["disconnect"]?.GetValue<bool>() == true) decoder.Disconnect(device);
                    else decoder.Decode(operation["type"]!.GetValue<uint>(), device, Convert.FromHexString(operation["payload"]!.GetValue<string>()));
                }
                actual = events;
            }
            else if (kind == "sdl")
            { if (SdlInputDecoder.Decode(Convert.FromHexString(test["payload"]!.GetValue<string>()), test["mapped"]!.GetValue<bool>()) is { } report) Emit(report); actual = events; }
            else
            {
                InputStateSampler sampler = new(Emit);
                foreach (var operation in test["operations"]!.AsArray())
                {
                    var op = operation!; var mono = op["mono_ns"]!.GetValue<long>();
                    if (op["op"]!.GetValue<string>() == "note")
                        sampler.Note(NativeInputReport.Create("input", ("mono_ns", mono), ("code", op["code"]!.GetValue<string>()), ("phase", op["phase"]!.GetValue<string>())));
                    else
                    {
                        var keys = op["keys"]!.AsArray().Select(v => v!.GetValue<int>()).ToHashSet();
                        sampler.Sample(mono, op["wall_ns"]!.GetValue<long>(), op["active"]!.GetValue<bool>(), keys.Contains);
                    }
                    actual.Add(new JsonObject { ["events"] = events.DeepClone(), ["samples"] = sampler.Samples, ["announced"] = JsonSerializer.SerializeToNode(sampler.Announced) });
                    events.Clear();
                }
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["passed"] = JsonNode.DeepEquals(actual, test["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Input backend differential: {outcomes.Count} cases, {failures} differences"); return failures == 0 ? 0 : 1;
    }
}
