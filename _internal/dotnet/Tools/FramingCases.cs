using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Capture.Framing;

internal static class FramingCases
{
    internal static object Head(SessionHead head) => head.ToPayload();

    private static object Login(SessionLogin login)
    {
        Dictionary<string, object?> values = [];
        void Add(string key, object? value) { if (value is not null) values[key] = value; }
        Add("uid", login.Uid); Add("login_token", login.LoginToken);
        Add("session_key_encrypted", login.EncryptedSessionKey is null ? null : Convert.ToHexStringLower(login.EncryptedSessionKey));
        Add("session_nonce", login.SessionNonce is null ? null : Convert.ToHexStringLower(login.SessionNonce));
        Add("server_time", login.ServerTime); Add("server_zone", login.ServerZone);
        return values;
    }

    private static object Frame(SessionFrame frame) =>
        new object[] { frame.HeadLength, Convert.ToHexStringLower(frame.Head), Convert.ToHexStringLower(frame.Body) };

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var kind = test!["kind"]!.GetValue<string>();
            var bytes = Convert.FromHexString(test["data"]?.GetValue<string>() ?? "");
            JsonNode? actual;
            try
            {
                object? result;
                switch (kind)
                {
                    case "varint":
                        var decoded = WireFields.DecodeVarint(bytes, test["offset"]?.GetValue<int>() ?? 0);
                        result = new object[] { decoded.Value, decoded.Offset }; break;
                    case "fields":
                        result = WireFields.Enumerate(bytes).Select(row => new object[] { row.Number, row.WireType,
                            row.Bytes is null ? (object)row.Integer!.Value : Convert.ToHexStringLower(row.Bytes) }).ToArray(); break;
                    case "head": result = Head(WireFields.ParseHead(bytes)); break;
                    case "login": result = Login(WireFields.ParseLogin(bytes)); break;
                    case "merged":
                        result = SessionFrameBuffer.Merged(bytes).Select(row =>
                            new object[] { row.Offset, row.Frame.HeadLength, Convert.ToHexStringLower(row.Frame.Head), Convert.ToHexStringLower(row.Frame.Body) }).ToArray(); break;
                    case "buffer":
                        SessionFrameBuffer buffer = new();
                        List<object> steps = [];
                        foreach (var chunk in test["chunks"]!.AsArray())
                        {
                            buffer.Append(Convert.FromHexString(chunk!.GetValue<string>()));
                            List<object> frames = [];
                            while (buffer.Pop() is { } frame) frames.Add(Frame(frame));
                            steps.Add(new Dictionary<string, object?> { ["frames"]=frames, ["pending"]=Convert.ToHexStringLower(buffer.Pending) });
                        }
                        result=steps; break;
                    case "lz4": result = Convert.ToHexStringLower(Lz4Block.Decompress(bytes)); break;
                    case "zlib": result = Convert.ToHexStringLower(SessionBodyCodec.Zlib(bytes)); break;
                    case "deflate": result = Convert.ToHexStringLower(SessionBodyCodec.RawDeflate(bytes)); break;
                    case "gzip": result = Convert.ToHexStringLower(SessionBodyCodec.Gzip(bytes)); break;
                    case "decompress":
                        result = Convert.ToHexStringLower(SessionBodyCodec.Decode(new(MessageId:123,
                            IsCompressed:test["compressed"]?.GetValue<bool>()), bytes)); break;
                    default: throw new InvalidOperationException("Unknown framing case: "+kind);
                }
                actual = new JsonObject { ["value"]=FieldCases.Canonical(result) };
            }
            catch (Exception error) when (error is InvalidDataException or IOException or IndexOutOfRangeException)
            {
                var type = kind is "zlib" or "deflate" or "gzip" ? "DecodeError" : error switch
                {
                    SessionBodyDecompressionException => "SessionBodyDecompressionError",
                    IndexOutOfRangeException => "IndexError",
                    _ => "ValueError",
                };
                actual = new JsonObject { ["error"]=type };
                if (kind is "lz4" or "varint" or "fields" or "login" or "decompress") actual["message"] = error.Message;
            }
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(actual, test["expected"]), ["actual"]=actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(item => !item!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Framing differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
