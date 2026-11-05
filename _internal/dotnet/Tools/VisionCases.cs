using System.IO.Compression;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Vision;

internal static class VisionCases
{
    private static JsonNode Json(EvidenceValue value) => JsonNode.Parse(PythonSortedJson.Serialize(value))!;
    public static int Run(string input, string output)
    {
        var root = JsonNode.Parse(File.ReadAllText(input))!.AsObject(); var frameTable = root["frames"]!.AsObject();
        // Compressed fixtures are decoded only for the selected case; avoid retaining all full frames.
        VisionPixels Frame(string key)
        {
            var row = frameTable[key]!; using MemoryStream compressed = new(Convert.FromBase64String(row["zlib"]!.GetValue<string>()));
            using ZLibStream inflater = new(compressed, CompressionMode.Decompress); using MemoryStream raw = new(); inflater.CopyTo(raw);
            var width = row["width"]!.GetValue<int>(); var channels = row["channels"]!.GetValue<int>();
            return new(raw.ToArray(), width, row["height"]!.GetValue<int>(), width * channels, channels);
        }
        static VisionObservation Observation(JsonNode row) => new(row["readable"]!.GetValue<bool>(), row["progress"]?.GetValue<double>(),
            row["ready"]!.GetValue<bool>(), row["consumed"]!.GetValue<bool>(), row["dead"]!.GetValue<bool>(), row["empty"]!.GetValue<bool>(),
            row["confidence"]!.GetValue<double>(), row["partial"]!.GetValue<bool>(), row["reason"]!.GetValue<string>());
        static PixelArea Area(JsonNode value) { var row = value.AsArray().Select(v => v!.GetValue<int>()).ToArray(); return new(row[0], row[1], row[2], row[3]); }
        JsonArray results = [];
        foreach (var test in root["cases"]!.AsArray())
        {
            var row = test!; var kind = row["kind"]!.GetValue<string>(); JsonNode actual;
            if (kind == "config") actual = Json(VisionConfiguration.Normalize(EvidenceJson.Parse(row["config"]?.ToJsonString() ?? "null")).ToEvidence());
            else if (kind == "layout")
            {
                actual = new JsonArray(VisionLayout.Fitted(Area(row["area"]!)).Select(candidate => (JsonNode)new JsonObject
                { ["name"] = candidate.Name, ["identity"] = candidate.Identity, ["regions"] = new JsonArray(candidate.Regions.Select(r => Json(r.ToEvidence())).ToArray()) }).ToArray());
            }
            else if (kind == "pixels") actual = Json(VisionPixelObserver.Observe(Frame(row["energy"]!.GetValue<string>()), Frame(row["hp"]!.GetValue<string>()), Frame(row["portrait"]!.GetValue<string>())).ToEvidence());
            else if (kind == "tracker")
            {
                VisionSlotTracker tracker = new(); JsonArray steps = [];
                foreach (var op in row["operations"]!.AsArray())
                {
                    var now = op!["now"]!.GetValue<double>();
                    if (op["op"]!.GetValue<string>() == "invalid") { tracker.Invalid(now); steps.Add(Json(tracker.Payload(now))); }
                    else steps.Add(Json(tracker.Feed(Observation(op["observation"]!), now, op["frame_id"]!.GetValue<long>())));
                }
                actual = steps;
            }
            else
            {
                VisionEngine engine = new(VisionConfiguration.Normalize(EvidenceJson.Parse(row["config"]!.ToJsonString()))); JsonArray steps = [];
                foreach (var op in row["operations"]!.AsArray())
                {
                    var now = op!["now"]!.GetValue<double>();
                    steps.Add(Json(op["invalid"]?.GetValue<bool>() == true ? engine.Invalid(now, op["reason"]!.GetValue<string>())
                        : engine.Analyze(Frame(op["frame"]!.GetValue<string>()), Area(op["client"]!), now, op["frame_id"]!.GetValue<long>())));
                }
                actual = steps;
            }
            results.Add(new JsonObject { ["name"] = kind, ["passed"] = JsonNode.DeepEquals(actual, row["expected"]), ["actual"] = actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, results.ToJsonString());
        var failures = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Vision differential: {results.Count} cases, {failures} differences"); return failures == 0 ? 0 : 1;
    }
}
