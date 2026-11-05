using System.Text.Json.Nodes;
using EndfieldLogs.Capture;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

internal static class PacketCases
{
    private static object? Packet(CapturedPacket? packet) => packet is null ? null : new Dictionary<string, object?>
    {
        ["timestamp_ms"]=packet.TimestampMs, ["src"]=new object[] { packet.Src.Ip, packet.Src.Port },
        ["dst"]=new object[] { packet.Dst.Ip, packet.Dst.Port }, ["seq"]=packet.Seq,
        ["payload"]=Convert.ToHexStringLower(packet.Payload), ["device_name"]=packet.DeviceName,
    };

    public static int Run(string inputPath, string outputPath)
    {
        var input = JsonNode.Parse(File.ReadAllText(inputPath))!.AsObject();
        var devices = input["devices"]!.AsArray().Select(row => new DeviceInfo(row!["name"]!.GetValue<string>(),
            row["description"]?.GetValue<string>(), row["addresses"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray(),
            row["flags"]!.GetValue<uint>())).ToArray();
        var cases = input["cases"]!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var kind = test!["kind"]!.GetValue<string>();
            JsonNode? actual;
            try
            {
                object? value;
                if (kind == "packet") value = Packet(PacketDecoder.Decode(123456,
                    Convert.FromHexString(test["data"]!.GetValue<string>()), "synthetic"));
                else if (kind == "devices") value = DeviceSelection.Select(devices, test["request"]?.GetValue<string>()).Select(row => row.Name).ToArray();
                else if (kind == "preference")
                {
                    var observed = test["observed"]!.AsArray().Select(row => row!.GetValue<string>()).ToHashSet();
                    value = devices.Select(row => { var score = DeviceSelection.Preference(row, observed); return new object[] { score.Score, score.AddressCount, score.Name }; }).ToArray();
                }
                else if (kind == "flow")
                {
                    var flow = new FlowKey(new(test["client"]!.GetValue<string>(), 30001), new("203.0.113.10", 30000));
                    var observed = test["observed"]!.AsArray().Select(row => row!.GetValue<string>()).ToHashSet();
                    value = new Dictionary<string, object?> { ["filter"]=DeviceSelection.FlowFilter(flow),
                        ["device"]=DeviceSelection.ChooseForFlow(devices, flow, observed)?.Name };
                }
                else throw new InvalidDataException("Unknown packet case: "+kind);
                actual = new JsonObject { ["value"]=FieldCases.Canonical(value) };
            }
            catch (Exception error) when (error is FormatException or IndexOutOfRangeException)
            { actual = new JsonObject { ["error"]=error is FormatException ? "ValueError" : "IndexError" }; }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(actual, test["expected"]), ["actual"]=actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(item => !item!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Packet differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
