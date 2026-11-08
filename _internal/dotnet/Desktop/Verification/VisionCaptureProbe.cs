using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using EndfieldLogs.Desktop.Vision;
using EndfieldLogs.Runtime.Vision;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Captures only this process's synthetic window; persists measurements, never desktop pixels.</summary>
internal static class VisionCaptureProbe
{
    public static int Run(string output, bool naturalLifetime = false, bool reuseDevice = false, bool reuseItem = false)
    {
        Application application = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Grid pattern = new(); pattern.ColumnDefinitions.Add(new()); pattern.ColumnDefinitions.Add(new());
        Border left = new() { Background = new SolidColorBrush(Color.FromRgb(32, 200, 80)) };
        Border right = new() { Background = new SolidColorBrush(Color.FromRgb(220, 64, 48)) };
        Grid.SetColumn(right, 1); pattern.Children.Add(left); pattern.Children.Add(right);
        Window window = new() { Title = "Endfield Logs · WGC 合成窗口验证", Width = 640, Height = 360, Left = 60, Top = 60, Content = pattern };
        BenchmarkWindow.Prepare(window);
        Dictionary<string, object?> result = []; var exit = 1;
        window.Loaded += async (_, _) =>
        {
            try
            {
                await Task.Delay(300);
                BenchmarkWindow.Check();
                var hwnd = new WindowInteropHelper(window).Handle;
                await Task.Run(async () =>
                {
                    var baseline = Process.GetCurrentProcess().HandleCount;
                    using WgcCaptureItemCache? captureItems = reuseItem ? new() : null;
                    WgcCaptureBackend CreateBackend() => captureItems is null ? new() : new(captureItems);
                    if (captureItems is not null)
                    {
                        var noTargetBackends = 0;
                        List<object> noTargetSamples = [];
                        await using (VisionService idle = new(() => { Interlocked.Increment(ref noTargetBackends); return CreateBackend(); },
                            Path.Combine(Path.GetTempPath(), "EndfieldLogs-missing-vision-target.exe")))
                        {
                            for (var cycle = 0; cycle < 12; cycle++)
                            {
                                await idle.SetEnabledAsync(true);
                                var waiting = Stopwatch.StartNew();
                                while (idle.State.Get("status") is not EvidenceText { Value: "等待游戏窗口" })
                                {
                                    if (waiting.Elapsed.TotalSeconds > 5) throw new TimeoutException("No-target worker did not reach idle");
                                    await Task.Delay(10);
                                }
                                await idle.SetEnabledAsync(false);
                                using var current = Process.GetCurrentProcess();
                                noTargetSamples.Add(new { cycle = cycle + 1, handles = current.HandleCount, privateBytes = current.PrivateMemorySize64,
                                    cpuMs = current.TotalProcessorTime.TotalMilliseconds });
                            }
                        }
                        Require(noTargetBackends == 12 && captureItems.CreatedCount == 0 && !captureItems.HasItem, "no_target_never_creates_capture_item");
                        result["no_target_restarts"] = noTargetSamples;
                    }
                    using WgcCaptureBackend backend = CreateBackend();
                    var targets = backend.Discover(Environment.ProcessPath!);
                    Require(targets.Windows.Contains((long)hwnd), "window_discovered");
                    backend.SetTarget(hwnd);
                    using (var first = await Next(backend, false))
                    {
                        result["first_frame"] = new { first.Pixels.Width, first.Pixels.Height, first.Client, first.ReceivedMono };
                        Require(Math.Abs(Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency - first.ReceivedMono) < 2, "qpc_timestamp");
                        Require(first.Client.Width > 400 && first.Client.Height > 200, "client_geometry");
                    }
                    await window.Dispatcher.InvokeAsync(() => { window.Width = 900; window.Height = 520; right.Background = new SolidColorBrush(Color.FromRgb(48, 96, 224)); });
                    using (var resized = await Next(backend, true, 800)) result["resized_frame"] = new { resized.Pixels.Width, resized.Pixels.Height, resized.Client };
                    if (captureItems is not null) Require(captureItems.CreatedCount == 1, "resize_reuses_capture_item");
                    backend.SetTarget(null); Require(backend.AcquireLatest() is null, "target_detached");
                    backend.SetTarget(hwnd);
                    var lease = await Next(backend, true, 800); var pixels = lease.Pixels;
                    backend.Dispose();
                    Require(pixels.At(lease.Client.X + 30, lease.Client.Y + 30, 1) > 150, "lease_survives_backend_close");
                    lease.Dispose(); lease.Dispose();
                    try { _ = pixels.At(0, 0, 0); throw new InvalidOperationException("released pixels remained accessible"); }
                    catch (ObjectDisposedException) { result["lease_invalidated"] = true; }
                    result["forced_gc"] = !naturalLifetime;
                    result["capture_owner"] = reuseItem ? "shared target, recreated device/pool/session"
                        : reuseDevice ? "shared device, recreated target/pool/session" : "recreated device/target/pool/session";
                    void Collect() { if (!naturalLifetime) { GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect(); } }
                    List<object> samples = [];
                    void Sample(string phase, int cycle)
                    {
                        using var process = Process.GetCurrentProcess();
                        samples.Add(new { phase, cycle, handles = process.HandleCount, rss = process.WorkingSet64,
                            privateBytes = process.PrivateMemorySize64, managed = GC.GetTotalMemory(false),
                            gen0 = GC.CollectionCount(0), gen1 = GC.CollectionCount(1), gen2 = GC.CollectionCount(2) });
                    }
                    Collect(); var warmHandles = Process.GetCurrentProcess().HandleCount;
                    Sample("before_warmup", 0);
                    for (var cycle = 0; cycle < 6; cycle++)
                    {
                        using WgcCaptureBackend repeated = CreateBackend(); repeated.SetTarget(hwnd); using (await Next(repeated, true, 800)) { }
                    }
                    Collect(); await Task.Delay(250); var initializedHandles = Process.GetCurrentProcess().HandleCount;
                    Sample("warmup_complete", 6);
                    var initializedTypes = HandleTypes();
                    var initializedItems = captureItems?.CreatedCount;
                    for (var cycle = 0; cycle < 6; cycle++) { using D3DReadback graphics = new(); }
                    Collect(); await Task.Delay(250); var graphicsOnlyHandles = Process.GetCurrentProcess().HandleCount;
                    Sample("graphics_only_complete", 6);
                    using WgcCaptureBackend? sharedBackend = reuseDevice ? CreateBackend() : null;
                    var measuredCycles = naturalLifetime ? 30 : 6;
                    for (var cycle = 0; cycle < measuredCycles; cycle++)
                    {
                        if (sharedBackend is not null)
                        {
                            sharedBackend.SetTarget(hwnd); using (await Next(sharedBackend, true, 800)) { }
                            sharedBackend.SetTarget(null);
                        }
                        else using (WgcCaptureBackend repeated = CreateBackend()) { repeated.SetTarget(hwnd); using (await Next(repeated, true, 800)) { } }
                        if (naturalLifetime) { await Task.Delay(250); Sample("capture_disposed", cycle + 1); }
                    }
                    sharedBackend?.Dispose();
                    Collect(); await Task.Delay(2000); Collect(); var finalHandles = Process.GetCurrentProcess().HandleCount;
                    Sample("settled", measuredCycles);
                    result["repeated_capture"] = new { cycles = 6 + measuredCycles, warmHandles, initializedHandles, graphicsOnlyHandles, finalHandles,
                        settledDelta = finalHandles - graphicsOnlyHandles, initializedItems, finalItems = captureItems?.CreatedCount, initializedTypes, finalTypes = HandleTypes(), samples };
                    if (captureItems is not null) Require(captureItems.CreatedCount == initializedItems && captureItems.HasItem, "restart_reuses_capture_item");
                    var resourcesBounded = finalHandles - graphicsOnlyHandles <= 8;

                    var regions = Enumerable.Range(0, 4).Select(i => new HudSlotRegions(new(.06 + i * .22, .22, .14, .025),
                        new(.06 + i * .22, .27, .14, .025), new(.06 + i * .22, .1, .05, .06))).ToArray();
                    var configuration = new VisionConfiguration("custom", regions, hwnd);
                    var hud = await window.Dispatcher.InvokeAsync(() => { HudPattern pattern = new(regions); window.Content = pattern; return pattern; });
                    WgcCaptureBackend? liveBackend = null;
                    await using (VisionService service = new(() => liveBackend = CreateBackend(), Environment.ProcessPath!, configuration.ToEvidence()))
                    {
                        service.SetPreview(true); await service.SetEnabledAsync(true);
                        var watch = Stopwatch.StartNew();
                        while (service.State.Get("status") is not EvidenceText { Value: "确认布局中" })
                        {
                            if (watch.Elapsed.TotalSeconds > 10) throw new TimeoutException("WGC 首帧未到达识别器：" + PythonSortedJson.Serialize(service.State));
                            await Task.Delay(30);
                        }
                        await window.Dispatcher.InvokeAsync(() => { hud.Pulse = true; hud.InvalidateVisual(); });
                        while (service.State.Get("frame_valid") is not EvidenceBoolean { Value: true })
                        {
                            if (watch.Elapsed.TotalSeconds > 12) throw new TimeoutException("WGC 识别未确认：" + PythonSortedJson.Serialize(service.State));
                            await Task.Delay(30);
                        }
                        service.SetIdentity([new(0, "synthetic_character", "合成角色")]);
                        var snapshot = service.TakeSnapshot()!; var visual = (EvidenceObject)snapshot.Get("snapshot");
                        var slots = ((EvidenceArray)visual.Get("slots")).Items.Cast<EvidenceObject>().ToArray();
                        Require(slots.Count(row => row.Get("status") is EvidenceText { Value: "ready" }) == 4, "wgc_service_four_ready_slots");
                        Require(slots[0].Get("character_key") is EvidenceText { Value: "synthetic_character" }, "wgc_service_identity");
                        Require(service.TakePreview() is { Width: > 0 and <= 960, Height: > 0 and <= 540 }, "wgc_service_preview");
                        result["wgc_service_timings"] = new { processingMs = (visual.Get("processing_ms") as EvidenceReal)?.Value, captureToPublishMs = (visual.Get("capture_to_publish_ms") as EvidenceReal)?.Value };
                        if (naturalLifetime)
                        {
                            var receivedBefore = JsonSerializer.SerializeToElement(liveBackend!.Diagnostics).GetProperty("receivedFrames").GetInt64();
                            var streaming = Stopwatch.StartNew(); var previews = 0;
                            for (var update = 0; update < 200; update++)
                            {
                                await window.Dispatcher.InvokeAsync(() => { hud.Pulse = !hud.Pulse; hud.InvalidateVisual(); });
                                await Task.Delay(50);
                                if (service.TakePreview() is not null) previews++;
                                if (update % 20 == 19) Sample("streaming", update + 1);
                            }
                            var receivedAfter = JsonSerializer.SerializeToElement(liveBackend.Diagnostics).GetProperty("receivedFrames").GetInt64();
                            var finalState = service.State;
                            Require(receivedAfter - receivedBefore >= 100 && previews >= 5
                                && finalState.Get("frame_valid") is EvidenceBoolean { Value: true }, "continuous_capture_and_recognition");
                            result["continuous_capture"] = new { updates = 200, elapsedMs = streaming.Elapsed.TotalMilliseconds,
                                capturedFrames = receivedAfter - receivedBefore, previews, diagnostic = liveBackend.Diagnostics };
                        }
                    }
                    if (naturalLifetime) { await Task.Delay(500); Sample("streaming_disposed", 200); }
                    using (WgcCaptureBackend closing = CreateBackend())
                    {
                        await window.Dispatcher.InvokeAsync(() => window.Content = pattern);
                        closing.SetTarget(hwnd); using (await Next(closing, true, 800)) { }
                        await window.Dispatcher.InvokeAsync(window.Close);
                        await Task.Delay(350);
                        using var final = closing.AcquireLatest();
                        Require(final is null && JsonSerializer.SerializeToElement(closing.Diagnostics).GetProperty("targetClosed").GetBoolean(), "window_close_clears_frame");
                        if (captureItems is not null) Require(!captureItems.HasItem, "window_close_invalidates_cached_item");
                    }
                    result["handles_before"] = baseline; result["handles_after"] = Process.GetCurrentProcess().HandleCount;
                    using (var current = Process.GetCurrentProcess())
                        result["injected_capture_modules"] = current.Modules.Cast<ProcessModule>()
                            .Where(module => module.ModuleName.Contains("nvspcap", StringComparison.OrdinalIgnoreCase))
                            .Select(module => new { module.ModuleName, module.FileVersionInfo.FileVersion, module.FileVersionInfo.ProductName,
                                containsSharedIpcIdentifier = System.Text.Encoding.ASCII.GetString(File.ReadAllBytes(module.FileName)).Contains("{2627E361-24E2-4F14-99ED-A20D0685D8DD}", StringComparison.Ordinal) }).ToArray();
                    result["functional_passed"] = true;
                    result["resource_stability"] = resourcesBounded ? "passed" : "failed; inspect repeated_capture and injected_capture_modules";
                    Require(resourcesBounded, "bounded_capture_handles");
                });
                result["passed"] = true; exit = 0;
            }
            catch (Exception error) { result["passed"] = false; result["error"] = error.ToString(); }
            finally
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
                File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                window.Close(); application.Shutdown();
            }
        };
        window.Show(); application.Run(); return exit;
        void Require(bool value, string key) { if (!value) throw new InvalidOperationException(key); result[key] = true; }
    }
    private static Dictionary<string, int> HandleTypes()
    {
        var buffer = Marshal.AllocHGlobal(1 << 20);
        try
        {
            using var process = Process.GetCurrentProcess();
            if (NtQueryInformationProcess(process.Handle, 51, buffer, 1 << 20, out _) < 0) return [];
            var count = (int)Marshal.ReadInt64(buffer); Dictionary<string, int> counts = []; Dictionary<int, string> names = [];
            var typeBuffer = Marshal.AllocHGlobal(4096);
            try
            {
            for (var i = 0; i < count; i++)
            {
                var offset = 16 + i * 40; var type = Marshal.ReadInt32(buffer, offset + 28);
                if (!names.TryGetValue(type, out var name))
                {
                    name = NtQueryObject(Marshal.ReadIntPtr(buffer, offset), 2, typeBuffer, 4096, out _) < 0 ? type.ToString()
                        : Marshal.PtrToStringUni(Marshal.ReadIntPtr(typeBuffer, 8), Marshal.ReadInt16(typeBuffer) / 2) ?? type.ToString();
                    names[type] = name;
                }
                if (name is "Mutant" or "Section" && NtQueryObject(Marshal.ReadIntPtr(buffer, offset), 1, typeBuffer, 4096, out _) >= 0)
                    name += ":" + (Marshal.ReadIntPtr(typeBuffer, 8) == 0 ? "" : Marshal.PtrToStringUni(Marshal.ReadIntPtr(typeBuffer, 8), Marshal.ReadInt16(typeBuffer) / 2));
                counts[name] = counts.GetValueOrDefault(name) + 1;
            }
            }
            finally { Marshal.FreeHGlobal(typeBuffer); }
            return counts;
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }
    [DllImport("ntdll.dll")] private static extern int NtQueryInformationProcess(nint process, int information, nint buffer, int length, out int returned);
    [DllImport("ntdll.dll")] private static extern int NtQueryObject(nint handle, int information, nint buffer, int length, out int returned);
    private sealed class HudPattern(IReadOnlyList<HudSlotRegions> regions) : FrameworkElement
    {
        public bool Pulse;
        protected override void OnRender(DrawingContext drawing)
        {
            drawing.DrawRectangle(new SolidColorBrush(Color.FromRgb(30, 30, 30)), null, new(0, 0, ActualWidth, ActualHeight));
            void Paint(HudRegion r, Color color) => drawing.DrawRectangle(new SolidColorBrush(color), null,
                new(r.X * ActualWidth, r.Y * ActualHeight, r.Width * ActualWidth, r.Height * ActualHeight));
            foreach (var row in regions)
            { Paint(row.Energy, Color.FromRgb(235, 235, 235)); Paint(row.Hp, Color.FromRgb(210, 150, 30)); Paint(row.Portrait, Color.FromRgb(40, 40, 40)); }
            Paint(new(.9, .9, .02, .02), Pulse ? Colors.Silver : Colors.DimGray);
        }
    }
    private static async Task<VisionCaptureFrame> Next(WgcCaptureBackend backend, bool blue, int minimumWidth = 0)
    {
        var began = Stopwatch.StartNew();
        object? last = null;
        while (began.Elapsed < TimeSpan.FromSeconds(12))
        {
            var frame = backend.AcquireLatest();
            if (frame is not null)
            {
                var p = frame.Pixels; var c = frame.Client;
                if (c.Width >= Math.Max(100, minimumWidth) && c.Height > 100)
                {
                    var x1 = c.X + c.Width / 4; var x2 = c.X + c.Width * 3 / 4; var y = c.Y + c.Height / 2;
                    last = new { p.Width, p.Height, client = c, left = new[] { p.At(x1, y, 0), p.At(x1, y, 1), p.At(x1, y, 2) }, right = new[] { p.At(x2, y, 0), p.At(x2, y, 1), p.At(x2, y, 2) } };
                    bool Near(int x, int b, int g, int r) => Math.Abs(p.At(x, y, 0) - b) < 8 && Math.Abs(p.At(x, y, 1) - g) < 8 && Math.Abs(p.At(x, y, 2) - r) < 8;
                    if (Near(x1, 80, 200, 32) && (blue ? Near(x2, 224, 96, 48) : Near(x2, 48, 64, 220))) return frame;
                }
                frame.Dispose();
            }
            await Task.Delay(30);
        }
        throw new TimeoutException("WGC 未收到尺寸、客户区与色块均匹配的窗口帧：" + JsonSerializer.Serialize(new { last, backend = backend.Diagnostics }));
    }
}
