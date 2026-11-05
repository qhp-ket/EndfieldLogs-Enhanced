using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Vision;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Checks the pixels captured from the real D2D product windows, separately from the WPF reference screenshots.</summary>
internal static class OverlayGraphicsProbe
{
    [DllImport("user32.dll")] private static extern bool GetLayeredWindowAttributes(nint window, out uint key, out byte alpha, out uint flags);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(nint window, nint order, int x, int y, int width, int height, uint flags);
    private sealed record Pixels(int Width, int Height, byte[] Data)
    {
        public string Hash => Convert.ToHexStringLower(SHA256.HashData(Data));
    }
    internal static int Run(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var temporary = Directory.CreateTempSubdirectory("endfield-d2d-graphics-");
        var portraits = Path.Combine(temporary.FullName, "_internal", "data", "ui", "characters"); Directory.CreateDirectory(portraits);
        OverlayProductProbe.WriteImage(Path.Combine(portraits, "portrait.png")); OverlayProductProbe.WriteImage(Path.Combine(portraits, "placeholder.png"));
        File.WriteAllText(Path.Combine(portraits, "manifest.json"), """{"version":"synthetic","portraits":{"chr_0001_test":{"path":"portrait.png"}},"aliases":{"chr_0002_test":"chr_0001_test"}}""");
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Dictionary<string, object?> checks = []; List<object> frames = []; var exit = 1;
        void Check(string name, bool valid) { checks[name] = valid; if (!valid) throw new InvalidOperationException(name); }
        app.Dispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                using (OverlayHost host = new("Endfield Logs · 软件回退验证"))
                using (OverlayGraphics graphics = new(host.Handle, preferHardware: false))
                using (WgcCaptureBackend capture = new())
                {
                    SetWindowPos(host.Handle, (nint)(-1), 20, 20, 300, 160, 0x0010 | 0x0040);
                    void Draw(Brush color)
                    {
                        DrawingGroup drawing = new(); using (var recorder = drawing.Open()) recorder.DrawRoundedRectangle(color, null, new(10, 10, 280, 140), 12, 12);
                        graphics.Render(drawing, 300, 160, 1);
                    }
                    Draw(Brushes.Red); capture.SetTarget(host.Handle); Draw(Brushes.Red);
                    var normal = await Capture(capture, null);
                    host.SetOpacity(0); Draw(Brushes.Lime);
                    var hidden = await Capture(capture, normal.Hash);
                    Check("software_fallback_draws_and_hidden_capture_updates", !graphics.Hardware && hidden.Data.Where((_, index) => index % 4 == 1).Count(value => value > 200) > 1000);
                }
                foreach (var module in new[] { "damage", "combo_skill", "uid_mask" })
                {
                    var entry = new OverlaySettings { Id = module, SourceValue = module, Geometry = new(30, 40, module == "uid_mask" ? 220 : 700, module == "uid_mask" ? 48 : 300) };
                    var skin = NativeSkins.Builtin(module);
                    var window = new OverlayWindow(entry, skin, new AvatarCache(temporary.FullName), _ => { });
                    try
                    {
                        window.Show(); window.Canvas.Receive(OverlayProductProbe.Summary("graphics", 1)); window.Canvas.Receive(OverlayProductProbe.Combo("graphics", 1)); window.UpdateLayout();
                        using WgcCaptureBackend capture = new(); capture.SetTarget(window.Handle);
                        window.UpdateLayout();
                        string? previous = (await Capture(capture, null)).Hash;
                        foreach (var theme in module == "uid_mask" ? new[] { "dark" } : new[] { "dark", "light", "transparent", "endfield" })
                        {
                            entry = entry with { Theme = theme }; window.Apply(entry, skin); window.UpdateLayout();
                            // Wait for the capture to deliver the new submitted drawing, not its previous theme.
                            var dpi = WindowInterop.GetDpiForWindow(window.Handle) / 96d;
                            var gpu = await Capture(capture, module == "uid_mask" ? null : previous,
                                (int)Math.Ceiling(window.ActualWidth * dpi), (int)Math.Ceiling(window.ActualHeight * dpi)); previous = gpu.Hash;
                            var reference = new RenderTargetBitmap(gpu.Width, gpu.Height, dpi * 96, dpi * 96, PixelFormats.Pbgra32);
                            OverlayCanvasReference.Render(reference, window.Canvas); byte[] expected = new byte[checked(gpu.Width * gpu.Height * 4)]; reference.CopyPixels(expected, gpu.Width * 4, 0);
                            Save(gpu, Path.ChangeExtension(output, $".{module}-{theme}.gpu.png"));
                            Save(new(gpu.Width, gpu.Height, expected), Path.ChangeExtension(output, $".{module}-{theme}.reference.png"));
                            var channelError = 0L; var changed = 0; var visible = 0; var glyphPixels = 0; var transparent = 0; var portraitPixels = 0;
                            for (var index = 0; index < expected.Length; index += 4)
                            {
                                var a = gpu.Data[index + 3]; if (a > 0) visible++; else transparent++;
                                if (Math.Abs(gpu.Data[index] - 180) < 3 && Math.Abs(gpu.Data[index + 1] - 90) < 3 && Math.Abs(gpu.Data[index + 2] - 35) < 3 && a == 255) portraitPixels++;
                                if (a > 180 && (theme == "dark" || theme == "transparent" ? gpu.Data[index] > 200 && gpu.Data[index + 1] > 200 && gpu.Data[index + 2] > 200
                                    : gpu.Data[index] < 110 && gpu.Data[index + 1] < 110 && gpu.Data[index + 2] < 110)) glyphPixels++;
                                for (var channel = 0; channel < 4; channel++)
                                { var difference = Math.Abs(expected[index + channel] - gpu.Data[index + channel]); channelError += difference; if (difference > 8) changed++; }
                            }
                            var meanError = channelError / (double)expected.Length;
                            frames.Add(new { module, theme, gpu.Width, gpu.Height, hardware = window.HardwareRendering, visible, transparent, glyphPixels, mean_channel_error = meanError, changed_channels = changed });
                            Check(module + "_" + theme + "_source_pixels", visible > 100 && (module == "uid_mask" || glyphPixels > 30));
                            Check(module + "_" + theme + "_drawing_retained", meanError < 12);
                            if (module != "uid_mask") Check(module + "_" + theme + "_avatar_pixels", portraitPixels > 100);
                            if (theme == "transparent") Check(module + "_transparent_background_alpha", transparent > gpu.Width * gpu.Height / 8);
                        }
                        if (module != "uid_mask")
                        {
                            window.Apply(entry with { Hidden = true }, skin); window.ApplyDesktop(false);
                            window.Canvas.Receive(module == "damage" ? OverlayProductProbe.Summary("graphics", 2, 1234567) : OverlayProductProbe.Combo("graphics-next", 1));
                            if (module == "combo_skill") window.Canvas.SetConnected(false);
                            window.UpdateLayout();
                            var hidden = await Capture(capture, previous); Save(hidden, Path.ChangeExtension(output, $".{module}.hidden.png"));
                            Check(module + "_hidden_current_pixels", hidden.Hash != previous && hidden.Data.Where((_, index) => index % 4 == 3).Any(alpha => alpha > 0));
                            Check(module + "_desktop_hidden_without_destroy", GetLayeredWindowAttributes(window.Handle, out _, out var alpha, out _) && alpha == 0 && window.IsVisible);
                        }
                    }
                    finally { window.DisposeWindow(); }
                }
                checks["passed"] = true; exit = 0;
            }
            catch (Exception error) { checks["error"] = error.ToString(); }
            finally
            {
                checks["frames"] = frames;
                File.WriteAllText(output, JsonSerializer.Serialize(checks, new JsonSerializerOptions { WriteIndented = true })); app.Shutdown(exit);
            }
        }));
        try { app.Run(); }
        finally { try { temporary.Delete(true); } catch (IOException) { } }
        return exit;
    }
    private static void Save(Pixels pixels, string output)
    {
        var image = BitmapSource.Create(pixels.Width, pixels.Height, 96, 96, PixelFormats.Pbgra32, null, pixels.Data, pixels.Width * 4);
        PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(image)); using var file = File.Create(output); encoder.Save(file);
    }
    private static async Task<Pixels> Capture(WgcCaptureBackend capture, string? previous, int? width = null, int? height = null)
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed.TotalSeconds < 6)
        {
            using var frame = capture.AcquireLatest();
            if (frame is not null)
            {
                var pixels = frame.Pixels; var stride = checked(pixels.Width * 4); byte[] data = new byte[checked(stride * pixels.Height)];
                if (width is not null && (pixels.Width != width || pixels.Height != height)) { await Task.Delay(30); continue; }
                for (var y = 0; y < pixels.Height; y++) pixels.Data.Span.Slice(y * pixels.Stride, stride).CopyTo(data.AsSpan(y * stride));
                Pixels result = new(pixels.Width, pixels.Height, data);
                if (result.Hash != previous) return result;
            }
            await Task.Delay(30);
        }
        throw new TimeoutException("未收到新的悬浮窗像素");
    }
}
