using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Threading;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Services;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    // Integrated synthetic replay, not a native packet/crypto/recording or physical presentation test.
    internal static int RunLiveBenchmark(string input, string output)
    {
        var config = JsonNode.Parse(File.ReadAllText(input))!;
        var root = ProductApplication.ResolveRoot();
        using var reader = new TraceJsonlReader();
        List<TraceEvent> loaded = [];
        using (var file = File.OpenRead(config["live"]!.GetValue<string>()))
        {
            byte[] buffer = new byte[65536]; int length;
            while ((length = file.Read(buffer)) > 0) loaded.AddRange(reader.Feed(buffer.AsSpan(0, length)).OfType<TraceEvent>());
        }
        if (reader.PendingBytes != 0 || loaded.Count == 0) throw new InvalidDataException("回放输入不完整");
        var events = loaded.ToArray(); loaded.Clear();
        var warmup = config["warmup_items"]?.GetValue<int>() ?? 0;
        if (warmup < 1 || warmup >= events.Length) throw new ArgumentOutOfRangeException("warmup_items");
        var repeats = config["replay_cycles"]?.GetValue<int>() ?? 1;
        if (repeats is < 1 or > 3) throw new ArgumentOutOfRangeException("replay_cycles");
        var temporary = Directory.CreateTempSubdirectory("endfield-live-window-benchmark-");
        var codec = new SettingsCodec(new(root));
        var entries = new[]
        {
            new OverlaySettings { Id = "damage", Theme = "dark", Geometry = new(20, 20, 800, 380) },
            new OverlaySettings { Id = "combo", Theme = "dark", SourceValue = "combo_skill", Geometry = new(20, 440, 540, 180) },
            new OverlaySettings { Id = "uid", SourceValue = "uid_mask", Geometry = new(20, 650, 220, 32) },
        };
        var store = new SettingsStore(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")) with
        {
            CheckUpdatesOnStart = false, StartCaptureOnLaunch = false, StartInputRecordingOnLaunch = false,
            ThemeMode = "dark", Overlays = entries,
        }, codec, Path.Combine(temporary.FullName, "settings.json"));
        var resources = new ResourceFiles(Path.Combine(root, "_internal"));
        var zone = TimeZoneInfo.CreateCustomTimeZone("benchmark", TimeSpan.FromHours(8), "benchmark", "benchmark");
        var date = DateOnly.ParseExact(config["date"]!.GetValue<string>(), "yyyy-MM-dd", CultureInfo.InvariantCulture);
        using var streams = LiveAnalysisStreams.Create(resources, date, zone);
        using var subscription = streams.Subscribe();
        using CancellationTokenSource lifetime = new();
        var run = streams.RunAsync(lifetime.Token);
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        MainWindow window = new(store, resources, independentFactory: (settings, required, diagnostic) =>
            new IndependentServiceController(new Recorder(), new(() => new Capture(), "missing-game.exe"), required, settings, temporary.FullName, diagnostic));
        using var process = Process.GetCurrentProcess();
        Dictionary<string, object?> result = [];
        List<object> phases = [], frames = [], draws = [];
        List<Dictionary<string, object?>> cycles = [];
        var fedAt = new double[events.Length]; var clock = Stopwatch.StartNew();
        var cycle = 0;
        long displayedRevision = 0, revisionBase = 0; int comboSequence = 0;
        var caughtUp = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var warmedUp = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        DispatcherTimer poll = new(TimeSpan.FromMilliseconds(100), DispatcherPriority.Background, (_, _) =>
        {
            while (subscription.TryRead(out var frame))
            {
                window.Overlays.Receive(frame!.ToEvidence()); window.Summary.SetSnapshot(frame.Snapshot);
                if (frame.Snapshot is null) continue;
                displayedRevision = frame.SourceRevision;
                frames.Add(new { cycle, frame.Sequence, frame.SourceRevision, elapsed_ms = clock.Elapsed.TotalMilliseconds,
                    phase = frame.SourceRevision <= warmup ? "warmup" : "updates",
                    source_age_ms = clock.Elapsed.TotalMilliseconds - Volatile.Read(ref fedAt[frame.SourceRevision - 1]),
                    pending_items = Math.Max(0, streams.State().Revision - revisionBase - frame.SourceRevision) });
                if (frame.SourceRevision >= warmup) warmedUp.TrySetResult();
                if (frame.SourceRevision == events.Length) caughtUp.TrySetResult();
            }
        }, app.Dispatcher);
        void Memory(string phase)
        {
            process.Refresh();
            phases.Add(new { cycle, phase, elapsed_ms = clock.Elapsed.TotalMilliseconds, rss_bytes = process.WorkingSet64,
                private_bytes = process.PrivateMemorySize64, managed_estimate_bytes = GC.GetTotalMemory(false),
                handles = process.HandleCount, gdi = GetGuiResources(process.Handle, 0), user = GetGuiResources(process.Handle, 1) });
        }
        DispatcherTimer sample = new(TimeSpan.FromSeconds(1), DispatcherPriority.Background, (_, _) => Memory("running"), app.Dispatcher);
        // Synthetic visual snapshots exercise the second product module without claiming WGC/recognition coverage.
        DispatcherTimer combo = new(TimeSpan.FromMilliseconds(100), DispatcherPriority.Background, (_, _) =>
        {
            var snapshot = OverlayProductProbe.Combo("integrated", ++comboSequence);
            var data = (EvidenceObject)snapshot.Get("snapshot");
            var slots = ((EvidenceArray)data.Get("slots")).Items.ToArray();
            var slot = (EvidenceObject)slots[1];
            slots[1] = new EvidenceObject(new Dictionary<string, EvidenceValue>(slot.Fields)
            {
                ["progress"] = new EvidenceReal(comboSequence % 100 / 100d),
                ["estimated_remaining_ms"] = new EvidenceInteger((100 - comboSequence % 100) * 100),
            });
            snapshot = new(new Dictionary<string, EvidenceValue>(snapshot.Fields)
            { ["snapshot"] = new EvidenceObject(new Dictionary<string, EvidenceValue>(data.Fields) { ["slots"] = new EvidenceArray(slots) }) });
            window.Overlays.Receive(snapshot);
        }, app.Dispatcher);
        var exit = 1;
        window.Loaded += async (_, _) =>
        {
            try
            {
                window.Overlays.Sync();
                if (window.Overlays.Windows.Count != 3) throw new InvalidOperationException("缺少产品浮窗");
                foreach (var (id, overlay) in window.Overlays.Windows)
                    overlay.RenderMeasured = cost => draws.Add(new { cycle, id, source_revision = displayedRevision,
                        elapsed_ms = clock.Elapsed.TotalMilliseconds,
                        source_age_ms = displayedRevision > warmup ? clock.Elapsed.TotalMilliseconds - Volatile.Read(ref fedAt[displayedRevision - 1]) : (double?)null,
                        cost.LayoutMs, cost.DrawSubmitMs, cost.PresentMs, cost.AllocatedBytes });
                void Feed(int index)
                {
                    Volatile.Write(ref fedAt[index], clock.Elapsed.TotalMilliseconds);
                    streams.FeedEvent(events[index]);
                }
                for (cycle = 1; cycle <= repeats; cycle++)
                {
                    if (cycle > 1)
                    {
                        displayedRevision = 0;
                        warmedUp = new(TaskCreationOptions.RunContinuationsAsynchronously);
                        caughtUp = new(TaskCreationOptions.RunContinuationsAsynchronously);
                        streams.Reset(newStream: true);
                        revisionBase = streams.State().Revision;
                    }
                    await Task.Run(() => { for (var index = 0; index < warmup; index++) Feed(index); });
                    await warmedUp.Task.WaitAsync(TimeSpan.FromSeconds(90));
                    await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                    Memory("warmup_complete");
                    var cpu = process.TotalProcessorTime; var start = clock.Elapsed.TotalMilliseconds;
                    var producer = Task.Run(async () =>
                    {
                        for (var index = warmup; index < events.Length; index++)
                        {
                            var due = start + Math.Max(0, events[index].CapturedAtMs - events[warmup].CapturedAtMs);
                            var delay = due - clock.Elapsed.TotalMilliseconds;
                            if (delay > 0) await Task.Delay(TimeSpan.FromMilliseconds(delay));
                            Feed(index);
                        }
                    });
                    await producer; var feedEnd = clock.Elapsed.TotalMilliseconds;
                    await caughtUp.Task.WaitAsync(TimeSpan.FromSeconds(90));
                    await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                    Dictionary<string, object?> completed = new()
                    {
                        ["cycle"] = cycle,
                        ["source_revision_base"] = revisionBase,
                        ["feed_and_drain_cpu_ms"] = (process.TotalProcessorTime - cpu).TotalMilliseconds,
                        ["measured_feed_ms"] = feedEnd - start,
                        ["drain_ms"] = Math.Max(0, clock.Elapsed.TotalMilliseconds - feedEnd),
                        ["state"] = streams.State(), ["unused_full_state"] = streams.State(false),
                        ["summary_json"] = PythonSortedJson.Serialize(window.Summary.Snapshot!),
                        ["passed"] = displayedRevision == events.Length && !streams.State().Dirty
                            && streams.State().LastError is null && streams.State(false).Calculations == 0,
                    };
                    cycles.Add(completed);
                    foreach (var (key, value) in completed) result[key] = value;
                    Memory("caught_up");
                }
                cycle = repeats;
                result["cycles"] = cycles;
                result["hardware"] = window.Overlays.Windows.ToDictionary(pair => pair.Key, pair => pair.Value.HardwareRendering);
                result["passed"] = cycles.All(item => (bool)item["passed"]!);
                sample.Stop(); combo.Stop(); poll.Stop();
                var idleCpu = process.TotalProcessorTime; var idle = Stopwatch.StartNew();
                await Task.Delay(5000);
                result["idle_cpu_ms"] = (process.TotalProcessorTime - idleCpu).TotalMilliseconds;
                result["idle_elapsed_ms"] = idle.Elapsed.TotalMilliseconds; Memory("idle");
                exit = (bool)result["passed"]! ? 0 : 1;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally
            {
                sample.Stop(); combo.Stop(); poll.Stop(); lifetime.Cancel();
                try { await run; } catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
                window.Close();
                var close = Stopwatch.StartNew();
                while (!window.ServicesDisposed && close.Elapsed.TotalSeconds < 15) await Task.Delay(20);
                result["services_disposed"] = window.ServicesDisposed;
                result["frames"] = frames; result["draws"] = draws; result["memory_phases"] = phases;
                result["input_events"] = events.Length; result["warmup_items"] = warmup;
                InterfaceBenchmark.AddAssemblyIdentity(result);
                result["boundary"] = "Synthetic timestamp-paced JSONL -> production LiveAnalysisStreams/subscription -> actual MainWindow summary and three product Direct2D HWNDs, dark mode. UI polls at 100 ms. Combo snapshots synthetic. Repeated cycles retain first-use results separately from later warmed observations. No native packets, decryption, recording, WGC, OBS or physical presentation. No forced GC. Draw endpoint is CPU submission only; not a Qt comparison.";
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
                File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                app.Shutdown(exit);
            }
        };
        app.Run(window);
        try { temporary.Delete(true); } catch (IOException) { }
        return exit;
    }
}
