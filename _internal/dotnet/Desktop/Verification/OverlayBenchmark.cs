using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Matches benchmark_native_overlays.py: three product windows and 20 Hz synthetic summaries.</summary>
internal static class OverlayBenchmark
{
    // CPU-only diagnostic of the existing module layout path; not a display/presentation benchmark.
    internal static int ProfileLayouts(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        AvatarCache avatars = new(ProductApplication.ResolveRoot());
        var messages = Enumerable.Range(0, 1101).Select(Message).ToArray();
        var combos = Enumerable.Range(0, messages.Length).Select(index =>
        {
            var message = OverlayProductProbe.Combo("layout", index + 2);
            var snapshot = (EvidenceObject)message.Get("snapshot");
            var slots = ((EvidenceArray)snapshot.Get("slots")).Items.ToArray();
            var changing = ((EvidenceObject)slots[1]).Fields.ToDictionary(pair => pair.Key, pair => pair.Value);
            changing["progress"] = new EvidenceReal(index % 100 / 100d); slots[1] = new EvidenceObject(changing);
            return new EvidenceObject(new Dictionary<string, EvidenceValue>(message.Fields)
                { ["snapshot"] = new EvidenceObject(new Dictionary<string, EvidenceValue>(snapshot.Fields) { ["slots"] = new EvidenceArray(slots) }) });
        }).ToArray();
        var combined = EndfieldLogs.Runtime.Overlays.NativeSkins.Parse(EvidenceJson.Parse("""
            {"schema_version":2,"name":"布局验证","modules":[{"type":"damage"},{"type":"combo_skill"},{"type":"uid_mask"}],"layout":{"direction":"vertical"}}
            """));
        var bars = new OverlaySettings { SourceValue = "combo_skill", TemplateSettings = new(new Dictionary<string, EvidenceValue>
            { ["display_style"] = new EvidenceText("bars") }) };
        List<object> samples = [];
        foreach (var scenario in new[] { "damage", "combined", "bars-resize" })
        for (var round = 0; round < 3; round++)
        {
            var entry = scenario == "bars-resize" ? bars : new OverlaySettings();
            var skin = scenario == "combined" ? combined : EndfieldLogs.Runtime.Overlays.NativeSkins.Builtin(entry.SourceValue);
            var canvas = new OverlayCanvas(avatars).Apply(entry, skin);
            canvas.SetDpi(1.75); canvas.Receive(OverlayProductProbe.Combo("layout", 1)); canvas.ArrangeSurface(new(800, 380));
            for (var index = 0; index <= 100; index++) Update(index);
            var allocated = GC.GetAllocatedBytesForCurrentThread(); var watch = Stopwatch.StartNew();
            for (var index = 101; index < messages.Length; index++) Update(index);
            var milliseconds = watch.Elapsed.TotalMilliseconds;
            var bytes = GC.GetAllocatedBytesForCurrentThread() - allocated;
            samples.Add(new { scenario, round = round + 1, updates = messages.Length - 101, milliseconds, allocated_bytes = bytes,
                natural_width = canvas.NaturalSize.Width, natural_height = canvas.NaturalSize.Height,
                layout = canvas.Arranged.Select(item => new { type = item.Module.Type, x = item.Area.X, y = item.Area.Y,
                    width = item.Area.Width, height = item.Area.Height, tips = item.Layout.Hits.Select(hit => hit.Text).ToArray() }).ToArray() });
            void Update(int index)
            {
                if (scenario == "bars-resize")
                {
                    canvas.Receive(combos[index]);
                    canvas.ArrangeSurface(new(800 + index % 10 * 10, 380));
                }
                else canvas.Receive(messages[index]);
            }
        }
        File.WriteAllText(output, JsonSerializer.Serialize(new { samples,
            boundary = "Synchronous module Receive/Measure/Arrange only, no painting, GPU, presentation, forced GC or file I/O inside measurement; 100 changing warmup updates, then 1000 measured updates" }, new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }
    // Diagnostic only: separate first-use native resources from the steady-state workload.
    internal static int ProfileResources(string output, bool hardware)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        Dictionary<string, object> stages = [];
        var actualHardware = false;
        void Record(string phase)
        {
            using var process = Process.GetCurrentProcess();
            stages[phase] = new { rss_bytes = process.WorkingSet64, private_bytes = process.PrivateMemorySize64,
                managed_bytes = GC.GetTotalMemory(false), gc_committed_bytes = GC.GetGCMemoryInfo().TotalCommittedBytes,
                handles = process.HandleCount,
                modules = process.Modules.Cast<ProcessModule>().Select(module => module.ModuleName).ToArray() };
        }
        Record("entry");
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Record("application");
        using (OverlayGraphicsDevice device = new())
        {
            Record("factories");
            using var host = new EndfieldLogs.Native.Windows.OverlayHost("Endfield Logs · 资源诊断");
            Record("native_window");
            using var graphics = new OverlayGraphics(host.Handle, device, preferHardware: hardware);
            var dpi = EndfieldLogs.Native.Windows.WindowInterop.GetDpiForWindow(host.Handle) / 96d;
            graphics.Render(new DrawingGroup(), (int)(800 * dpi), (int)(380 * dpi), dpi);
            actualHardware = graphics.Hardware;
            Record("empty_target");
            var palette = new OverlayPalette(new(new Dictionary<string, EvidenceValue>()), new(new Dictionary<string, EvidenceValue>()));
            OverlayDrawing.Measure("角色 · rDMG 条 9,999,999.25", palette, dpi);
            Record("text_measurement");
            AvatarCache avatars = new(ProductApplication.ResolveRoot());
            foreach (var key in Characters) avatars.Get(key);
            Record("avatar_decoding");
            var canvas = new OverlayCanvas(avatars).Apply(new OverlaySettings(), EndfieldLogs.Runtime.Overlays.NativeSkins.Builtin("damage"));
            canvas.SetDpi(dpi); canvas.Receive(Message(1));
            canvas.ArrangeSurface(new(800, 380));
            Record("measured_content");
            graphics.Render(canvas, (int)(800 * dpi), (int)(380 * dpi), dpi);
            Record("painted_content");
        }
        Record("disposed");
        File.WriteAllText(output, JsonSerializer.Serialize(new { requested_hardware = hardware, actual_hardware = actualHardware, stages,
            boundary = "first-use resource diagnosis, no forced GC; not a steady-state performance comparison" }, new JsonSerializerOptions { WriteIndented = true }));
        app.Shutdown(); return 0;
    }
    private static readonly string[] Characters = ["chr_0004_pelica", "chr_0005_chen", "chr_0003_endminf", "chr_0006_wolfgd"];
    private static EvidenceObject Message(int sequence) => (EvidenceObject)EvidenceJson.Parse(JsonSerializer.Serialize(new
    {
        type = "analysis_summary", schema_version = 1, stream_id = "benchmark", sequence,
        snapshot = new
        {
            battle = new { total_damage = 100000 + sequence * 100, total_dps = 10000, duration_ms = 10000 + sequence * 50 },
            participants = Characters.Select(key => new { character_key = key, character_name = key, total_damage = 25000 + sequence * 25, total_rd = 25000 + sequence * 25, crit_rate = .25 }),
            snapshot_quality = new { status = "verified" }
        }
    }));
    internal static int Run(string output, bool profile = false, string? input = null, int warmupFrames = 0, bool memoryProfile = false, string theme = "light")
    {
        var started = Stopwatch.StartNew();
        Dictionary<string, object> memoryStages = [];
        void RecordMemory(string phase)
        {
            using var current = Process.GetCurrentProcess();
            var gc = GC.GetGCMemoryInfo();
            memoryStages[phase] = new { rss_bytes = current.WorkingSet64, private_bytes = current.PrivateMemorySize64,
                managed_bytes = GC.GetTotalMemory(false), gc_committed_bytes = gc.TotalCommittedBytes,
                gc_heap_bytes = gc.HeapSizeBytes, handles = current.HandleCount };
        }
        RecordMemory("entry");
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var root = ProductApplication.ResolveRoot();
        var inputBytes = input is null ? null : File.ReadAllBytes(input);
        var messages = inputBytes is null ? Enumerable.Range(0, 201).Select(Message).ToArray()
            : ((EvidenceArray)EvidenceJson.Parse(System.Text.Encoding.UTF8.GetString(inputBytes))).Items.Select(value => (EvidenceObject)value).ToArray();
        RecordMemory("prepared_input");
        if (warmupFrames < 0 || messages.Length < warmupFrames + 2) throw new ArgumentException("The overlay workload requires a warmup and update snapshots");
        var temporary = Directory.CreateTempSubdirectory("endfield-overlay-benchmark-");
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        SettingsCodec codec = new(new(root));
        var entries = new[] { new OverlaySettings { Id = "damage", Theme = theme, Geometry = new(20, 20, 800, 380) },
            new OverlaySettings { Id = "combo_skill", Theme = theme, SourceValue = "combo_skill", Geometry = new(20, 440, 540, 180) },
            new OverlaySettings { Id = "uid_mask", Theme = theme, SourceValue = "uid_mask", Geometry = new(20, 650, 220, 32) } };
        SettingsStore store = new(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")) with { Overlays = entries }, codec, Path.Combine(temporary.FullName, "settings.json"));
        List<string> diagnostics = []; using OverlayManager manager = new(store, diagnostics.Add);
        // A benchmark frame can update both product streams before the next paint.
        void Receive(EvidenceObject frame)
        {
            if (frame.Get("messages") is EvidenceArray batch)
                foreach (var message in batch.Items) manager.Receive((EvidenceObject)message);
            else manager.Receive(frame);
        }
        Dictionary<string, (int Width, int Height)> sizes = new() { ["damage"] = (800, 380), ["combo_skill"] = (540, 180), ["uid_mask"] = (220, 32) };
        var exit = 1;
        app.Dispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                RecordMemory("before_windows");
                if (memoryProfile)
                    for (var index = 0; index < entries.Length; index++)
                    {
                        store.Update(current => current with { Overlays = entries.Take(index + 1).ToArray() }, save: false);
                        manager.Sync();
                        RecordMemory("window_" + entries[index].Id);
                    }
                manager.Sync(); Receive(messages[0]);
                RecordMemory("windows_created");
                // Content fitting remains enabled in production; hold this benchmark's logical dimensions constant.
                void FixSizes()
                {
                    foreach (var (id, window) in manager.Windows)
                    {
                        var size = sizes[id];
                        if (window.Width != size.Width) window.Width = size.Width;
                        if (window.Height != size.Height) window.Height = size.Height;
                    }
                }
                foreach (var window in manager.Windows.Values) window.Canvas.NaturalSizeChanged += FixSizes;
                FixSizes(); foreach (var window in manager.Windows.Values) window.UpdateLayout();
                var readyMs = started.Elapsed.TotalMilliseconds;
                // An external sampler can measure process creation through the first actual backing images.
                File.WriteAllText(output + ".ready", "ready");
                await Task.Delay(1800);
                using var process = Process.GetCurrentProcess();
                var warmCpu = process.TotalProcessorTime; var warmClock = Stopwatch.StartNew();
                for (var sequence = 1; sequence <= warmupFrames; sequence++)
                {
                    var send = Stopwatch.StartNew(); Receive(messages[sequence]);
                    await Dispatcher.Yield(DispatcherPriority.Background);
                    var remaining = sequence * 50 - warmClock.Elapsed.TotalMilliseconds;
                    if (remaining > 0) await Task.Delay(TimeSpan.FromMilliseconds(remaining));
                }
                if (warmupFrames > 0) await Task.Delay(2000);
                var warmCpuMs = (process.TotalProcessorTime - warmCpu).TotalMilliseconds;
                var warmSeconds = warmClock.Elapsed.TotalSeconds;
                RecordMemory("warmup_complete");
                var first = process.TotalProcessorTime; var clock = Stopwatch.StartNew();
                File.WriteAllText(output + ".phase", "idle");
                await Task.Delay(3000);
                var idleCpu = 100 * (process.TotalProcessorTime - first).TotalSeconds / clock.Elapsed.TotalSeconds;
                var idle = process.TotalProcessorTime; List<double> latencies = []; List<double> applyTimes = []; clock.Restart();
                var threadCpu = process.Threads.Cast<ProcessThread>().ToDictionary(thread => thread.Id, thread => thread.TotalProcessorTime);
                Dictionary<string, List<OverlayWindow.RenderCost>> rendering = [];
                foreach (var (id, window) in manager.Windows)
                {
                    List<OverlayWindow.RenderCost> costs = []; rendering[id] = costs;
                    window.RenderMeasured = costs.Add;
                }
                File.WriteAllText(output + ".phase", "update");
                var updateAllocated = GC.GetTotalAllocatedBytes(precise: true);
                for (var sequence = warmupFrames + 1; sequence < messages.Length; sequence++)
                {
                    var send = Stopwatch.StartNew(); Receive(messages[sequence]);
                    applyTimes.Add(send.Elapsed.TotalMilliseconds);
                    await Dispatcher.Yield(DispatcherPriority.Background);
                    if (manager.Windows.Values.Any(window => window.Canvas.PaintRevision != window.Canvas.LayoutRevision))
                        throw new InvalidOperationException("Snapshot did not reach the actual backing image");
                    latencies.Add(send.Elapsed.TotalMilliseconds);
                    var remaining = (sequence - warmupFrames) * 50 - clock.Elapsed.TotalMilliseconds;
                    if (remaining > 0) await Task.Delay(TimeSpan.FromMilliseconds(remaining));
                }
                var updateAllocatedBytes = GC.GetTotalAllocatedBytes(precise: true) - updateAllocated;
                var updateSeconds = clock.Elapsed.TotalSeconds;
                var updateCpu = 100 * (process.TotalProcessorTime - idle).TotalSeconds / updateSeconds;
                File.WriteAllText(output + ".phase", "complete");
                latencies.Sort(); process.Refresh();
                RecordMemory("update_complete");
                var result = new
                {
                    platform = "windows", theme, windows = manager.Windows.Count,
                    dimensions = sizes.ToDictionary(pair => pair.Key, pair => new[] { pair.Value.Width, pair.Value.Height }),
                    actual_dimensions = manager.Windows.ToDictionary(pair => pair.Key, pair => new[] { pair.Value.ActualWidth, pair.Value.ActualHeight }),
                    natural_dimensions = manager.Windows.ToDictionary(pair => pair.Key, pair => new[] { pair.Value.Canvas.NaturalSize.Width, pair.Value.Canvas.NaturalSize.Height }),
                    dpi_scales = manager.Windows.ToDictionary(pair => pair.Key, pair => EndfieldLogs.Native.Windows.WindowInterop.GetDpiForWindow(pair.Value.Handle) / 96d),
                    physical_image_dimensions = new[] { Math.Ceiling(manager.Windows["damage"].ActualWidth * EndfieldLogs.Native.Windows.WindowInterop.GetDpiForWindow(manager.Windows["damage"].Handle) / 96d), Math.Ceiling(manager.Windows["damage"].ActualHeight * EndfieldLogs.Native.Windows.WindowInterop.GetDpiForWindow(manager.Windows["damage"].Handle) / 96d) },
                    rss_mib = process.WorkingSet64 / 1024d / 1024, processes = 1,
                    idle_cpu_percent = idleCpu, update_cpu_percent = updateCpu,
                    update_seconds = updateSeconds, actual_update_hz = latencies.Count / updateSeconds,
                    latency_p50_ms = latencies.Count % 2 == 0 ? (latencies[latencies.Count / 2 - 1] + latencies[latencies.Count / 2]) / 2 : latencies[latencies.Count / 2],
                    latency_p95_ms = latencies[Math.Max(0, (int)(.95 * latencies.Count) - 1)],
                    apply_p50_ms = applyTimes.Order().ElementAt(applyTimes.Count / 2), apply_total_ms = applyTimes.Sum(),
                    input_sha256 = inputBytes is null ? null : Convert.ToHexStringLower(SHA256.HashData(inputBytes)),
                    prepared_snapshots = messages.Length,
                    warmup_frames = warmupFrames, warmup_seconds = warmSeconds, warmup_cpu_ms = warmCpuMs,
                    update_allocated_bytes = updateAllocatedBytes,
                    render_backends = manager.Windows.ToDictionary(pair => pair.Key, pair => pair.Value.HardwareRendering ? "Direct2D hardware" : "Direct2D software fallback"),
                    first_backing_images_ms = readyMs, diagnostics,
                    memory_stages = memoryStages,
                    thread_cpu_ms = process.Threads.Cast<ProcessThread>().Select(thread => new { thread.Id,
                        milliseconds = (thread.TotalProcessorTime - threadCpu.GetValueOrDefault(thread.Id)).TotalMilliseconds }).OrderByDescending(thread => thread.milliseconds).ToArray(),
                    rendering = rendering.ToDictionary(pair => pair.Key, pair => new
                    {
                        frames = pair.Value.Count, layout_ms = pair.Value.Sum(cost => cost.LayoutMs),
                        draw_submit_ms = pair.Value.Sum(cost => cost.DrawSubmitMs),
                        present_ms = pair.Value.Sum(cost => cost.PresentMs), allocated_bytes = pair.Value.Sum(cost => cost.AllocatedBytes)
                    }),
                    boundary = "prepared snapshot -> Direct2D EndDraw/presentation submission; 20 Hz, 4 participants; CPU percent of one core. draw_submit_ms includes immediate commands, text resources and EndDraw; it is not GPU raster duration. No CPU framebuffer/readback. Excludes physical scanout and capture/analysis",
                    raster_profile = profile ? OverlayRasterProfile.Measure(manager.Windows["damage"].Canvas,
                        EndfieldLogs.Native.Windows.WindowInterop.GetDpiForWindow(manager.Windows["damage"].Handle) / 96d, output) : null
                };
                File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                var canvas = manager.Windows["damage"].Canvas;
                var pixels = new RenderTargetBitmap((int)Math.Ceiling(canvas.ActualWidth), (int)Math.Ceiling(canvas.ActualHeight), 96, 96, PixelFormats.Pbgra32);
                OverlayCanvasReference.Render(pixels, canvas); PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(pixels));
                using (var image = File.Create(Path.ChangeExtension(output, ".png"))) encoder.Save(image);
                if (manager.Windows.Count == 3 && diagnostics.Count == 0) exit = 0;
            }
            catch (Exception error) { File.WriteAllText(output, JsonSerializer.Serialize(new { error = error.ToString(), diagnostics })); }
            finally { manager.Dispose(); app.Shutdown(exit); }
        }));
        try { app.Run(); }
        finally { try { temporary.Delete(true); } catch (IOException) { } }
        return exit;
    }
}
