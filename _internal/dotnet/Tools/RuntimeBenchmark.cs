using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Realtime;

/// <summary>Real-time producer/consumer measurement through the production Runtime publishers.</summary>
internal static class RuntimeBenchmark
{
    internal static async Task<int> RunAsync(string root, string input, string output)
    {
        var config = JsonNode.Parse(File.ReadAllText(input))!;
        using var process = Process.GetCurrentProcess();
        var path = config["live"]!.GetValue<string>();
        var events = config["format"]?.GetValue<string>() == "jsonl" ? SessionBenchmark.LoadEvents(path) : null;
        var lines = events is null ? File.ReadAllLines(path) : [];
        var count = events?.Length ?? lines.Length;
        var warmupCount = config["warmup_items"]?.GetValue<int>() ?? 0;
        if (warmupCount < 0 || warmupCount >= count) throw new ArgumentOutOfRangeException("warmup_items");
        var timestamps = config["timestamp_pacing"]?.GetValue<bool>() ?? false;
        if (timestamps && events is null) throw new ArgumentException("Timestamp pacing requires JSONL events");
        var durationMs = timestamps ? events![^1].CapturedAtMs - events[warmupCount].CapturedAtMs
            : config["feed_duration_ms"]?.GetValue<double>() ?? 0;
        var batch = config["feed_batch"]?.GetValue<int>() ?? 28;
        if (count == 0 || durationMs <= 0 || batch < 1) throw new ArgumentException("Nonempty input and positive duration/batch required");
        var zone = TimeZoneInfo.CreateCustomTimeZone("benchmark", TimeSpan.FromHours(8), "benchmark", "benchmark");
        var date = DateOnly.ParseExact(config["date"]!.GetValue<string>(), "yyyy-MM-dd", CultureInfo.InvariantCulture);
        using var streams = LiveAnalysisStreams.Create(new ResourceFiles(Path.Combine(root, "_internal")), date, zone);
        using var subscription = streams.Subscribe();
        using CancellationTokenSource lifetime = new();
        var run = streams.RunAsync(lifetime.Token);
        var clock = Stopwatch.StartNew();
        double[] fedAt = new double[count];
        List<double> feedCosts = [], producerLateness = [];
        List<object> frames = [];
        TaskCompletionSource<LiveSnapshotFrame> caughtUp = new(TaskCreationOptions.RunContinuationsAsynchronously);
        TaskCompletionSource<LiveSnapshotFrame> warmedUp = new(TaskCreationOptions.RunContinuationsAsynchronously);
        async Task Observe()
        {
            while (await subscription.ReadAsync(lifetime.Token).ConfigureAwait(false) is { } frame)
            {
                var now = clock.Elapsed.TotalMilliseconds;
                var current = streams.State();
                frames.Add(new { elapsed_ms = now, frame.Sequence, frame.SourceRevision,
                    phase = frame.SourceRevision <= warmupCount ? "warmup" : "updates",
                    pending_lines = Math.Max(0, current.Revision - frame.SourceRevision),
                    pending_items = Math.Max(0, current.Revision - frame.SourceRevision),
                    source_age_ms = frame.SourceRevision > 0 && frame.SourceRevision <= fedAt.Length
                        ? now - Volatile.Read(ref fedAt[frame.SourceRevision - 1]) : (double?)null });
                if (frame.SourceRevision >= warmupCount && frame.Snapshot is not null) warmedUp.TrySetResult(frame);
                if (frame.SourceRevision >= count && frame.Snapshot is not null) caughtUp.TrySetResult(frame);
            }
        }
        var observer = Observe();
        LiveSnapshotFrame final;
        double feedEnded, feedStarted = 0, warmupMs = 0, warmupCpuMs = 0;
        var feedCpu = process.TotalProcessorTime;
        void Feed(int index)
        {
            Volatile.Write(ref fedAt[index], clock.Elapsed.TotalMilliseconds);
            if (events is null) streams.FeedLine(lines[index]); else streams.FeedEvent(events[index]);
        }
        try
        {
            if (warmupCount > 0)
            {
                Console.WriteLine("PHASE runtime_warmup"); Console.Out.Flush();
                for (var index = 0; index < warmupCount; index++) Feed(index);
                await warmedUp.Task.WaitAsync(TimeSpan.FromSeconds(90));
                warmupMs = clock.Elapsed.TotalMilliseconds;
                warmupCpuMs = (process.TotalProcessorTime - feedCpu).TotalMilliseconds;
            }
            feedCpu = process.TotalProcessorTime;
            feedStarted = clock.Elapsed.TotalMilliseconds;
            Console.WriteLine("PHASE runtime_feed"); Console.Out.Flush();
            for (var offset = warmupCount; offset < count; offset += batch)
            {
                var due = feedStarted + (timestamps
                    ? Math.Max(0, events![offset].CapturedAtMs - events[warmupCount].CapturedAtMs)
                    : (offset - warmupCount) / (double)(count - warmupCount) * durationMs);
                var remaining = due - clock.Elapsed.TotalMilliseconds;
                if (remaining > 0) await Task.Delay(TimeSpan.FromMilliseconds(remaining));
                producerLateness.Add(Math.Max(0, clock.Elapsed.TotalMilliseconds - due));
                for (var index = offset; index < Math.Min(offset + batch, count); index++)
                {
                    var start = Stopwatch.GetTimestamp(); Feed(index);
                    feedCosts.Add(Stopwatch.GetElapsedTime(start).TotalMilliseconds);
                }
            }
            feedEnded = clock.Elapsed.TotalMilliseconds;
            Console.WriteLine("PHASE runtime_drain"); Console.Out.Flush();
            final = await caughtUp.Task.WaitAsync(TimeSpan.FromSeconds(90));
        }
        finally
        {
            lifetime.Cancel();
            try { await Task.WhenAll(run, observer); }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        }
        var finished = clock.Elapsed.TotalMilliseconds;
        var state = streams.State();
        static double Percentile(List<double> values, double quantile)
        {
            values.Sort(); return values[(int)Math.Clamp(Math.Ceiling(values.Count * quantile) - 1, 0, values.Count - 1)];
        }
        var result = new
        {
            boundary = "preloaded synthetic input -> production LiveAnalysisStreams -> detached summary subscription; optional prehistory warmup reported separately; no UI, capture or actual game",
            source_format = events is null ? "legacy" : "jsonl", input_lines = lines.Length, input_events = events?.Length ?? 0,
            warmup_items = warmupCount, warmup_ms = warmupMs, timestamp_pacing = timestamps,
            warmup_cpu_ms = warmupCpuMs, feed_and_drain_cpu_ms = (process.TotalProcessorTime - feedCpu).TotalMilliseconds,
            expected_feed_ms = durationMs, feed_started_ms = feedStarted, feed_ended_ms = feedEnded,
            measured_feed_ms = feedEnded - feedStarted,
            drain_ms = Math.Max(0, finished - feedEnded),
            feed_p50_ms = Percentile(feedCosts, .5), feed_p95_ms = Percentile(feedCosts, .95), feed_max_ms = feedCosts.Max(),
            producer_lateness_p95_ms = Percentile(producerLateness, .95),
            summary = SessionBenchmark.Summary(final.Snapshot), frames, state,
            unused_full_state = streams.State(false), managed_allocated_bytes = GC.GetTotalAllocatedBytes(),
            caught_up = state.SourceRevision == state.Revision && !state.Dirty && state.LastError is null
        };
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
        return result.caught_up ? 0 : 1;
    }
}
