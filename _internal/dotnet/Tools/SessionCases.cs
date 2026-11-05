using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Capture.Framing;
using Google.Protobuf;

internal static class SessionCases
{
    private static BigInteger? Integer(JsonObject input, string key) => input[key] is { } value
        ? BigInteger.Parse(value.ToJsonString(), CultureInfo.InvariantCulture) : null;
    private static SessionHead Head(JsonObject value) => new(Integer(value,"msgid"), Integer(value,"up_seqid"),
        Integer(value,"down_seqid"), Integer(value,"total_pack_count"), Integer(value,"current_pack_index"),
        value["is_compress"]?.GetValue<bool>(), Integer(value,"checksum"), value["parse_error"]?.GetValue<string>());

    public static int Run(string inputPath, string outputPath)
    {
        var input = JsonNode.Parse(File.ReadAllText(inputPath))!.AsObject();
        MessageRegistry registry = new(input["client_map"]!.ToJsonString(), input["server_map"]!.ToJsonString());
        var cases = input["cases"]!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var kind = test!["kind"]!.GetValue<string>();
            JsonNode? actual;
            if (kind == "registry")
            {
                var direction = test["direction"]!.GetValue<string>();
                var id = BigInteger.Parse(test["id"]!.ToJsonString(), CultureInfo.InvariantCulture);
                actual = new JsonObject { ["class_name"]=registry.ResolveClassName(direction, id), ["should_decode"]=registry.ShouldDecode(direction,id) };
            }
            else if (kind == "decode")
            {
                try
                {
                    JsonArray decoded = [];
                    foreach (var message in registry.Decode(test["direction"]!.GetValue<string>(), Head(test["head"]!.AsObject()),
                                 Convert.FromHexString(test["body"]!.GetValue<string>())))
                        decoded.Add(new JsonObject { ["direction"]=message.Direction, ["class_name"]=message.ClassName,
                            ["msg_id"]=message.MessageId.ToString(CultureInfo.InvariantCulture),
                            ["head"]=FieldCases.Canonical(FramingCases.Head(message.Head)),
                            ["message"]=JsonNode.Parse(JsonFormatter.Default.Format(message.Message)),
                            ["raw_body"]=Convert.ToHexStringLower(message.RawBody) });
                    actual = new JsonObject { ["value"]=decoded };
                }
                catch (Exception error) when (error is MessageDecodeFailure or SessionBodyDecompressionException)
                {
                    actual = new JsonObject { ["error"]=error is MessageDecodeFailure ? "MessageDecodeFailure" : "SessionBodyDecompressionError", ["message"]=error.Message };
                }
            }
            else if (kind == "multipack")
            {
                List<object> progress = [];
                MultiPackAssembler assembler = new(row => progress.Add(new Dictionary<string, object?>
                {
                    ["direction"]=row.Key.Direction, ["msg_id"]=row.Key.MessageId, ["seqid"]=row.SequenceId,
                    ["base_seqid"]=row.Key.BaseSequenceId, ["total_pack_count"]=row.TotalPackCount,
                    ["current_pack_index"]=row.CurrentPackIndex, ["received_indexes"]=row.ReceivedIndexes,
                    ["timestamp_ms"]=row.TimestampMs,
                }));
                JsonArray steps = [];
                foreach (var operation in test["operations"]!.AsArray())
                {
                    progress.Clear();
                    object? output;
                    string? error = null;
                    try
                    {
                        if (operation!["reset"]?.GetValue<bool>() == true) { assembler.Reset(); output=null; }
                        else
                        {
                            var assembled = assembler.Assemble(operation["direction"]!.GetValue<string>(), Head(operation["head"]!.AsObject()),
                                Convert.FromHexString(operation["body"]!.GetValue<string>()), operation["time"]!.GetValue<long>());
                            output = assembled is null ? null : new object[] { FramingCases.Head(assembled.Head),
                                Convert.ToHexStringLower(assembled.Body), assembled.AlreadyDecompressed };
                        }
                    }
                    catch (SessionBodyDecompressionException failure) { output=null; error=failure.Message; }
                    var pending = assembler.Pending.Select(pair => new Dictionary<string, object?>
                    {
                        ["key"]=new object[] { pair.Key.Direction, pair.Key.MessageId, pair.Key.BaseSequenceId },
                        ["total_pack_count"]=pair.Value.TotalPackCount, ["head"]=FramingCases.Head(pair.Value.Head),
                        ["parts"]=pair.Value.Parts.ToDictionary(item => item.Key.ToString(CultureInfo.InvariantCulture), item => Convert.ToHexStringLower(item.Value)),
                        ["first_timestamp_ms"]=pair.Value.FirstTimestampMs, ["last_timestamp_ms"]=pair.Value.LastTimestampMs,
                    }).ToArray();
                    steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["output"]=output, ["error"]=error, ["pending"]=pending, ["progress"]=progress }));
                }
                actual=steps;
            }
            else throw new InvalidDataException("Unknown session case: "+kind);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(actual, test["expected"]), ["actual"]=actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(item => !item!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Session differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
