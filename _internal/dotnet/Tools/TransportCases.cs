using System.Text.Json.Nodes;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Models;
using Google.Protobuf;

internal static class TransportCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var input = JsonNode.Parse(File.ReadAllText(inputPath))!.AsObject();
        MessageRegistry registry = new(input["client_map"]!.ToJsonString(),input["server_map"]!.ToJsonString());
        var cases = input["cases"]!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            List<object> messages = [], warnings = [], debug = [];
            RuntimeMetrics metrics = new();
            var flow = new FlowKey(new("192.0.2.1",30001),new("203.0.113.10",30000));
            SessionTransport transport = new(flow,"synthetic",registry, bytes => bytes,
                _ => Enumerable.Range(0,32).Select(i => (byte)i).ToArray(),
                (message,time) => messages.Add(new Dictionary<string, object?>
                { ["direction"]=message.Direction, ["class_name"]=message.ClassName, ["msg_id"]=message.MessageId,
                    ["head"]=message.Head.ToPayload(), ["message"]=JsonNode.Parse(JsonFormatter.Default.Format(message.Message)),
                    ["raw_body"]=Convert.ToHexStringLower(message.RawBody), ["time"]=time }),
                warning => warnings.Add(warning.ToPayload()), metrics,
                test!["debug"]!.GetValue<bool>() ? record => debug.Add(record) : null);
            JsonArray steps = [];
            foreach (var operation in test["operations"]!.AsArray())
            {
                if (operation!["flush"]?.GetValue<bool>() == true) transport.FlushDebugState();
                else
                {
                    var client = operation["direction"]!.GetValue<string>() == "cs";
                    transport.Process(new(operation["time"]!.GetValue<long>(), client ? flow.Client : flow.Server,
                        client ? flow.Server : flow.Client,operation["seq"]!.GetValue<long>(),
                        Convert.FromHexString(operation["data"]!.GetValue<string>()),"synthetic"));
                }
                // Protobuf JSON already uses its external value contract, not the integer-bit adapter.
                var projectedMessages = new JsonArray();
                foreach (Dictionary<string, object?> message in messages)
                {
                    var protobuf = (JsonNode?)message["message"];
                    var copy = new Dictionary<string, object?>(message); copy.Remove("message");
                    var row = FieldCases.Canonical(copy)!.AsObject(); row["message"]=protobuf?.DeepClone(); projectedMessages.Add(row);
                }
                steps.Add(new JsonObject
                {
                    ["status"]=FieldCases.Canonical(transport.Status()), ["live"]=transport.IsLive,
                    ["messages"]=projectedMessages, ["warnings"]=FieldCases.Canonical(warnings), ["debug"]=FieldCases.Canonical(debug),
                    ["metrics"]=FieldCases.Canonical(new Dictionary<string, object?>
                    { ["frames_decoded"]=metrics.FramesDecoded, ["messages_decoded"]=metrics.MessagesDecoded,
                        ["decompression_errors"]=metrics.DecompressionErrors, ["protobuf_decode_errors"]=metrics.ProtobufDecodeErrors,
                        ["outbound_events_emitted"]=metrics.OutboundEventsEmitted }),
                });
            }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(steps,test["expected"]), ["actual"]=steps });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Transport differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
