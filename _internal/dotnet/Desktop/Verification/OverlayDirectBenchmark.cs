using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Same prepared snapshots and logical sizes as OverlayBenchmark. Measures process cost, not presentation latency.</summary>
internal static class OverlayDirectBenchmark
{
    internal static int Run(string input, string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var inputBytes = File.ReadAllBytes(input);
        var messages = ((EvidenceArray)EvidenceJson.Parse(System.Text.Encoding.UTF8.GetString(inputBytes))).Items.Cast<EvidenceObject>().ToArray();
        var root = ProductApplication.ResolveRoot(); AvatarCache avatars = new(root);
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var entries = new[] { (Type: "damage", Width: 800, Height: 380, Top: 20), (Type: "combo_skill", Width: 540, Height: 180, Top: 440), (Type: "uid_mask", Width: 220, Height: 32, Top: 650) };
        var windows = entries.Select(entry =>
        {
            var canvas = new OverlayCanvas(avatars).Apply(new OverlaySettings { SourceValue = entry.Type }, NativeSkins.Builtin(entry.Type));
            var window = new Window { Title = "Endfield Logs · " + entry.Type, Width = entry.Width, Height = entry.Height,
                Left = 20, Top = entry.Top, WindowStyle = WindowStyle.None, ResizeMode = ResizeMode.NoResize, AllowsTransparency = true,
                Background = Brushes.Transparent, ShowActivated = false, ShowInTaskbar = false, Topmost = true, Content = new OverlayCanvasReference(canvas) };
            window.SourceInitialized += (_, _) =>
            {
                var handle = new WindowInteropHelper(window).Handle; WindowInterop.ConfigureOverlay(handle, false);
                canvas.SetDpi(WindowInterop.GetDpiForWindow(handle) / 96d);
            };
            return (entry.Type, Window: window, Canvas: canvas);
        }).ToArray();
        OverlayFeed feed = new(); feed.Changed += (_, message) => { foreach (var item in windows) item.Canvas.Receive(message); };
        var exit = 1;
        app.Dispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                feed.Receive(messages[0]); foreach (var item in windows) item.Window.Show();
                await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
                File.WriteAllText(output + ".ready", "ready"); await Task.Delay(1800);
                using var process = Process.GetCurrentProcess();
                var first = process.TotalProcessorTime; var clock = Stopwatch.StartNew();
                File.WriteAllText(output + ".phase", "idle"); await Task.Delay(3000);
                var idleCpu = 100 * (process.TotalProcessorTime - first).TotalSeconds / clock.Elapsed.TotalSeconds;
                var idle = process.TotalProcessorTime; clock.Restart(); List<double> applies = [], prepared = [];
                var paints = windows.ToDictionary(item => item.Type, _ => 0);
                File.WriteAllText(output + ".phase", "update");
                for (var sequence = 1; sequence < messages.Length; sequence++)
                {
                    var previous = windows.Select(item => item.Canvas.PaintRevision).ToArray();
                    var send = Stopwatch.StartNew(); feed.Receive(messages[sequence]); applies.Add(send.Elapsed.TotalMilliseconds);
                    await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
                    if (windows[0].Canvas.PaintRevision != windows[0].Canvas.LayoutRevision) throw new InvalidOperationException("Drawing commands were not prepared");
                    for (var i = 0; i < windows.Length; i++) if (windows[i].Canvas.PaintRevision != previous[i]) paints[windows[i].Type]++;
                    prepared.Add(send.Elapsed.TotalMilliseconds);
                    var remaining = 50 - send.Elapsed.TotalMilliseconds;
                    if (remaining > 0) await Task.Delay(TimeSpan.FromMilliseconds(remaining));
                }
                process.Refresh();
                File.WriteAllText(output, JsonSerializer.Serialize(new
                {
                    prepared_snapshots = messages.Length, input_sha256 = Convert.ToHexStringLower(SHA256.HashData(inputBytes)),
                    render_tier = RenderCapability.Tier >> 16, rss_mib = process.WorkingSet64 / 1024d / 1024, idle_cpu_percent = idleCpu,
                    update_cpu_percent = 100 * (process.TotalProcessorTime - idle).TotalSeconds / clock.Elapsed.TotalSeconds,
                    apply_total_ms = applies.Sum(), dispatcher_prepared_p50_ms = prepared.Order().ElementAt(prepared.Count / 2),
                    dimensions = windows.ToDictionary(item => item.Type, item => new[] { item.Canvas.ActualWidth, item.Canvas.ActualHeight }),
                    dpi_scales = windows.ToDictionary(item => item.Type, item => WindowInterop.GetDpiForWindow(new WindowInteropHelper(item.Window).Handle) / 96d),
                    rendering = paints.ToDictionary(pair => pair.Key, pair => new { frames = pair.Value }),
                    boundary = "CPU and memory of the process tree; WPF direct transparent Window, same canvas/data, 20 Hz. Dispatcher preparation is not DWM presentation latency. No RenderTargetBitmap, readback, frame timer or capture in measured phase."
                }, new JsonSerializerOptions { WriteIndented = true }));
                exit = 0;
            }
            catch (Exception error) { File.WriteAllText(output, JsonSerializer.Serialize(new { error = error.ToString() })); }
            finally { foreach (var item in windows) item.Window.Close(); app.Shutdown(exit); }
        }));
        return app.Run();
    }
}
