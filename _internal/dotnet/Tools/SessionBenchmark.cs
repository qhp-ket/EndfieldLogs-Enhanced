using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Runtime.CompilerServices;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.History;

/// <summary>Development measurements through the production engine and history entry points.</summary>
internal static class SessionBenchmark
{
    internal static TraceEvent[] LoadEvents(string path)
    {
        using var reader = new TraceJsonlReader();
        using var file = File.OpenRead(path);
        List<TraceEvent> loaded = [];
        var buffer = new byte[65536];
        int length;
        while ((length = file.Read(buffer)) > 0) loaded.AddRange(reader.Feed(buffer.AsSpan(0, length)).OfType<TraceEvent>());
        if (reader.PendingBytes != 0) throw new InvalidDataException("Incomplete trace event");
        return loaded.ToArray();
    }

    public static int Run(string root, string input, string output)
    {
        var config = JsonNode.Parse(File.ReadAllText(input))!;
        using var process = Process.GetCurrentProcess();
        var files = new ResourceFiles(Path.Combine(root, "_internal"));
        var zone = TimeZoneInfo.CreateCustomTimeZone("benchmark", TimeSpan.FromHours(8), "benchmark", "benchmark");
        JsonObject result = new() { ["implementation"] = "csharp", ["runtime"] = Environment.Version.ToString() };
        static double Measure(Action action)
        {
            var timer = Stopwatch.StartNew(); action(); return timer.Elapsed.TotalMilliseconds;
        }
        static void Phase(string name) { Console.WriteLine("PHASE " + name); Console.Out.Flush(); }
        if (config["mode"]!.GetValue<string>() == "history")
        {
            HistoryAnalyzer analyzer = new(files, zone);
            if (config["warmup_history"] is JsonValue warmupPath)
            {
                JsonObject WarmHistory()
                {
                    HistoryIndex warmIndex = new(config["cache"]!.GetValue<string>() + "-warmup", new(zone));
                    IReadOnlyList<HistoryRecord> warmRecords = [];
                    Phase("warmup_index");
                    var indexMs = Measure(() => warmRecords = warmIndex.Records(warmupPath.GetValue<string>(), trace: true));
                    Phase("warmup_analyze");
                    EvidenceObject? snapshot = null;
                    var cpu = process.TotalProcessorTime;
                    var analysisMs = Measure(() => snapshot = analyzer.Analyze(warmRecords[0]));
                    return new JsonObject { ["record_count"] = warmRecords.Count, ["index_ms"] = indexMs,
                        ["analysis_ms"] = analysisMs, ["cpu_ms"] = (process.TotalProcessorTime - cpu).TotalMilliseconds,
                        ["summary"] = Summary(snapshot) };
                }
                result["warmup"] = WarmHistory();
            }
            var path = config["history"]!.GetValue<string>();
            HistoryIndex index = new(config["cache"]!.GetValue<string>(), new(zone));
            IReadOnlyList<HistoryRecord> records = [];
            Phase("index_cold");
            result["index_cold_ms"] = Measure(() => records = index.Records(path, trace: true));
            result["record_count"] = records.Count;
            result["ranges"] = new JsonArray(records.Select(row => (JsonNode)new JsonArray(row.SourceStartLine,
                row.SourceEndLine, row.SourceByteStart, row.SourceByteEnd, row.LastHitHint)).ToArray());
            Phase("index_cached");
            result["index_cached_ms"] = Measure(() => records = index.Records(path, trace: true));
            JsonArray selections = [];
            var repeats = config["history_repeats"]?.GetValue<int>() ?? 1;
            if (repeats < 1) throw new ArgumentOutOfRangeException(nameof(repeats));
            for (var repeat = 0; repeat < repeats; repeat++)
            {
                if (repeat > 0)
                {
                    Phase("index_repeat"); records = index.Records(path, trace: true);
                }
                foreach (var position in new[] { 0, records.Count / 2, records.Count - 1 }.Distinct())
                {
                    Phase("analyze_" + position); EvidenceObject? snapshot = null;
                    var allocated = GC.GetTotalAllocatedBytes();
                    var cpu = process.TotalProcessorTime;
                    var elapsed = Measure(() => snapshot = analyzer.Analyze(records[position]));
                    JsonObject selection = new() { ["position"] = position, ["elapsed_ms"] = elapsed,
                        ["cpu_ms"] = (process.TotalProcessorTime - cpu).TotalMilliseconds,
                        ["allocated_bytes"] = GC.GetTotalAllocatedBytes() - allocated,
                        ["summary"] = Summary(snapshot) };
                    if (repeats > 1) selection["repeat"] = repeat;
                    selections.Add(selection);
                    // Optional full evidence comparison is separate from performance runs:
                    // canonical JSON preserves integer types and every floating-point bit.
                    if (config["report_directory"] is JsonValue directory)
                    {
                        Phase("export_" + position);
                        var reportDirectory = Path.GetFullPath(directory.GetValue<string>());
                        Directory.CreateDirectory(reportDirectory);
                        var suffix = repeats > 1 ? $"-repeat-{repeat}" : "";
                        File.WriteAllText(Path.Combine(reportDirectory, $"report-{position}{suffix}.json"),
                            FieldCases.Canonical(snapshot)!.ToJsonString());
                    }
                }
            }
            result["selections"] = selections;
        }
        else
        {
            TraceEvent[]? events = null;
            if (config["format"]?.GetValue<string>() == "jsonl")
                events = LoadEvents(config["live"]!.GetValue<string>());
            // A controlled synthetic complexity probe can keep a shorter stable
            // prefix while feeding exactly the same typed event suffix.
            if (config["append_from"] is JsonValue appendFrom)
            {
                var prefix = config["warmup_items"]!.GetValue<int>(); var start = appendFrom.GetValue<int>();
                if (events is null || prefix < 1 || start < prefix || start >= events.Length)
                    throw new ArgumentOutOfRangeException("append_from");
                events = events.Take(prefix).Concat(events.Skip(start)).ToArray();
            }
            var lines = events is null ? File.ReadAllText(config["live"]!.GetValue<string>()).Split('\n')
                .Where(line => line.Length > 0).Select(line => line + "\n").ToArray() : [];
            var batch = config["batch"]!.GetValue<int>();
            LiveBattleEngine? engine = null;
            Phase("initialize");
            result["initialize_ms"] = Measure(() => engine = LiveBattleEngine.Load(files,
                DateOnly.ParseExact(config["date"]!.GetValue<string>(), "yyyy-MM-dd", CultureInfo.InvariantCulture), zone));
            List<string> cumulative = []; JsonArray updates = [];
            var count = events?.Length ?? lines.Length;
            var warmup = config["warmup_items"]?.GetValue<int>() ?? 0;
            if (warmup < 0 || warmup >= count) throw new ArgumentOutOfRangeException("warmup_items");
            if (warmup > 0)
            {
                if (events is null) throw new ArgumentException("Stable-history append measurements require structured events");
                Phase("warmup");
                result["warmup_ms"] = Measure(() => _ = engine!.SnapshotEvents(new(1, warmup, 0, events.Take(warmup).ToArray()), summary: true));
                result["warmup_items"] = warmup;
            }
            Phase("updates");
            for (var offset = warmup; offset < count; offset += batch)
            {
                cumulative.AddRange(events is null ? lines.Skip(offset).Take(batch) : []); EvidenceObject? snapshot = null;
                var suffix = events?.Skip(offset).Take(batch).ToArray();
                var consumed = Math.Min(offset + batch, count);
                var allocated = GC.GetTotalAllocatedBytes();
                var cpu = process.TotalProcessorTime;
                var elapsed = Measure(() => snapshot = events is null ? engine!.Snapshot(cumulative, summary: true)
                    : AppendSnapshot(engine!, consumed, offset, suffix!));
                updates.Add(new JsonObject { ["lines"] = events is null ? cumulative.Count : consumed, ["elapsed_ms"] = elapsed,
                    ["cpu_ms"] = (process.TotalProcessorTime - cpu).TotalMilliseconds,
                    ["allocated_bytes"] = GC.GetTotalAllocatedBytes() - allocated,
                    ["summary"] = Summary(snapshot) });
            }
            Phase("cached");
            result["cached_ms"] = Measure(() => _ = events is null ? engine!.Snapshot(cumulative, summary: true)
                : engine!.SnapshotEvents(new(1, count, count, []), summary: true));
            result["format"] = events is null ? "legacy" : "jsonl";
            result["updates"] = updates;
            result["diagnostics"] = JsonSerializer.SerializeToNode(engine!.Diagnostics, JsonContract.Options);
        }
        result["managed_allocated_bytes"] = GC.GetTotalAllocatedBytes();
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, result.ToJsonString(new() { WriteIndented = true }));
        return 0;
    }

    // Keep the measured append region identifiable in an optional sampled-stack trace;
    // warmup, input parsing and result serialization are outside this call.
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static EvidenceObject? AppendSnapshot(LiveBattleEngine engine, int revision, int offset, TraceEvent[] suffix)
        => engine.SnapshotEvents(new(1, revision, offset, suffix), summary: true);

    internal static JsonNode? Summary(EvidenceObject? snapshot)
    {
        if (snapshot is null) return null;
        // Sanity comparison only; fixed full differential suites remain authoritative.
        JsonObject result = new();
        if (snapshot.Get("battle") is EvidenceObject battle)
            foreach (var key in new[] { "total_damage", "duration_ms", "time_source" })
                result[key] = FieldCases.Canonical(battle.Get(key));
        result["participants"] = snapshot.Get("participants") is EvidenceArray rows
            ? new JsonArray(rows.Items.Cast<EvidenceObject>().Select(row => (JsonNode)new JsonObject(
                new[] { "character_key", "total_damage", "total_rd", "hit_count" }
                    .Select(key => KeyValuePair.Create(key, FieldCases.Canonical(row.Get(key)))))).ToArray()) : new JsonArray();
        return result;
    }
}
