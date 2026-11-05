using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Vision;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Evaluate the existing canvas in a normal WPF transparent window before changing the product host.</summary>
internal static class OverlayDirectProbe
{
    private sealed record CaptureSample(int Width, int Height, long Nonzero, string Hash);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetLayeredWindowAttributes(nint window, uint key, byte alpha, uint flags);

    internal static int Run(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var root = ProductApplication.ResolveRoot();
        Dictionary<string, object?> result = []; var exit = 1;
        var entry = new OverlaySettings { Theme = "endfield" };
        var canvas = new OverlayCanvas(new(root)).Apply(entry, NativeSkins.Builtin("damage"));
        var window = new Window { Title = "Endfield Logs · WPF直接显示验证", Width = 800, Height = 380, Left = 20, Top = 20,
            AllowsTransparency = true, Background = Brushes.Transparent, WindowStyle = WindowStyle.None, ResizeMode = ResizeMode.NoResize,
            ShowInTaskbar = false, ShowActivated = false, Topmost = true, Content = new OverlayCanvasReference(canvas) };
        window.SourceInitialized += (_, _) =>
        {
            var handle = new WindowInteropHelper(window).Handle;
            WindowInterop.ConfigureOverlay(handle, false); canvas.SetDpi(WindowInterop.GetDpiForWindow(handle) / 96d);
        };
        app.Dispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                canvas.Receive(OverlayProductProbe.Summary("direct", 1)); window.Show(); await Task.Delay(400);
                var handle = new WindowInteropHelper(window).Handle;
                result["render_tier"] = RenderCapability.Tier >> 16;
                result["dpi"] = WindowInterop.GetDpiForWindow(handle) / 96d;
                result["window_visible"] = WindowInterop.IsWindowVisible(handle);
                result["canvas_size"] = new[] { canvas.ActualWidth, canvas.ActualHeight };
                result["frame_prepared"] = canvas.PaintRevision == canvas.LayoutRevision;
                using WgcCaptureBackend capture = new(); capture.SetTarget(handle);
                var normal = await Sample(capture); result["normal"] = normal;
                window.Opacity = 0; canvas.Receive(OverlayProductProbe.Summary("direct", 2, 987654));
                await Task.Delay(250);
                result["hidden_hwnd_visible"] = WindowInterop.IsWindowVisible(handle);
                var opacityHidden = await Sample(capture, normal.Hash); result["window_opacity_zero"] = opacityHidden;
                result["opacity_zero_retains_updated_pixels"] = opacityHidden.Nonzero > normal.Nonzero * .8 && opacityHidden.Hash != normal.Hash;
                window.Opacity = 1; canvas.Receive(OverlayProductProbe.Summary("direct", 3, 456789));
                await Task.Delay(250); var restored = await Sample(capture, opacityHidden.Hash); result["restored"] = restored;
                // This is an explicit compatibility trial: SLA can interfere with WPF's own layered presentation.
                result["native_alpha_zero_call"] = SetLayeredWindowAttributes(handle, 0, 0, 2);
                canvas.Receive(OverlayProductProbe.Summary("direct", 4, 654321)); await Task.Delay(250);
                var nativeHidden = await Sample(capture, restored.Hash); result["native_alpha_zero"] = nativeHidden;
                result["native_alpha_retains_updated_pixels"] = nativeHidden.Nonzero > restored.Nonzero * .8 && nativeHidden.Hash != restored.Hash;
                SetLayeredWindowAttributes(handle, 0, 255, 2);
                result["completed"] = true;
                exit = result["opacity_zero_retains_updated_pixels"] is true || result["native_alpha_retains_updated_pixels"] is true ? 0 : 1;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally
            {
                File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                window.Close(); app.Shutdown(exit);
            }
        }));
        return app.Run();
    }
    private static async Task<CaptureSample> Sample(WgcCaptureBackend capture, string? previous = null)
    {
        CaptureSample? latest = null; var watch = Stopwatch.StartNew();
        while (watch.Elapsed.TotalSeconds < 3)
        {
            using var frame = capture.AcquireLatest();
            if (frame is not null)
            {
                long nonzero = 0; using MemoryStream bytes = new();
                for (var y = 2; y < frame.Pixels.Height; y += 5)
                for (var x = 2; x < frame.Pixels.Width; x += 5)
                {
                    var a = frame.Pixels.At(x, y, 0); var b = frame.Pixels.At(x, y, 1); var c = frame.Pixels.At(x, y, 2);
                    if (a + b + c > 30) nonzero++; bytes.WriteByte(a); bytes.WriteByte(b); bytes.WriteByte(c);
                }
                latest = new(frame.Pixels.Width, frame.Pixels.Height, nonzero, Convert.ToHexStringLower(SHA256.HashData(bytes.ToArray())));
                if (nonzero > 0 && latest.Hash != previous) return latest;
            }
            await Task.Delay(30);
        }
        return latest ?? throw new TimeoutException("No WGC frame for the direct WPF host");
    }
}
