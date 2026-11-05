using System.Text.Json.Nodes;
using EndfieldLogs.Protocol;
using Google.Protobuf;
using Google.Protobuf.Reflection;

internal static class ProtocolCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var fixtures = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var fixture in fixtures)
        {
            var message = ProtocolCatalog.Parse(fixture!["message"]!.GetValue<string>(),
                Convert.FromHexString(fixture["bytes"]!.GetValue<string>()));
            var serialized = message.ToByteArray();
            var bytes = Convert.ToHexStringLower(serialized);
            var json = JsonFormatter.Default.Format(message);
            if (!fixture.AsObject().ContainsKey("expected_json") || fixture["expected_unknown"] is null)
                throw new InvalidDataException("Missing fixed protocol JSON/unknown-field expectation");
            // Map ordering and explicit default map values differ between official runtimes.
            // Compare known fields/presence via the fixed Python JSON and retain exact unknown wire data.
            var unknown = RootUnknownFields(message.Descriptor, serialized);
            var reparsed = message.Descriptor.Parser.ParseFrom(serialized);
            results.Add(new JsonObject { ["name"]=fixture["name"]!.GetValue<string>(), ["bytes"]=bytes, ["json"]=json,
                ["bytes_equal"]=bytes == fixture["bytes"]!.GetValue<string>(),
                ["passed"]=message.Equals(reparsed)
                    && unknown == fixture["expected_unknown"]!.GetValue<string>()
                    && JsonNode.DeepEquals(JsonNode.Parse(json),fixture["expected_json"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath,results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Protocol differential: {fixtures.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }

    private static string RootUnknownFields(MessageDescriptor descriptor, byte[] serialized)
    {
        using var input = new CodedInputStream(serialized);
        using var unknown = new MemoryStream();
        while (!input.IsAtEnd)
        {
            var start = checked((int)input.Position);
            var tag = input.ReadTag();
            if (tag == 0) break;
            input.SkipLastField();
            if (descriptor.FindFieldByNumber(WireFormat.GetTagFieldNumber(tag)) is null)
                unknown.Write(serialized.AsSpan(start, checked((int)input.Position) - start));
        }
        return Convert.ToHexStringLower(unknown.ToArray());
    }
}
