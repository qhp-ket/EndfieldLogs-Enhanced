using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using EndfieldLogs.Native.Windows;

namespace EndfieldLogs.Desktop.Verification;

internal static class OverlayProbe
{
    public static int Run(string output)
    {
        var application = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new Window
        {
            Title = "Endfield Logs - Enhanced · 原生窗口验证",
            Width = 400, Height = 180, Left = 40, Top = 40,
            WindowStyle = WindowStyle.None, ResizeMode = ResizeMode.NoResize,
            AllowsTransparency = true, Background = Brushes.Transparent,
            ShowInTaskbar = false, ShowActivated = false, Topmost = true,
            Content = new ProbeCanvas(),
        };
        Dictionary<string, object?> result = [];
        var exitCode = 1;
        window.SourceInitialized += (_, _) =>
        {
            var handle = new WindowInteropHelper(window).Handle;
            WindowInterop.ConfigureOverlay(handle, true);
        };
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            try
            {
                var handle = new WindowInteropHelper(window).Handle;
                var styles = (long)WindowInterop.GetWindowLong(handle, WindowInterop.ExtendedStyle);
                if (!WindowInterop.GetWindowRect(handle, out var rectangle)) throw new InvalidOperationException("No HWND rectangle");
                result["visible"] = WindowInterop.IsWindowVisible(handle);
                result["click_through"] = (styles&WindowInterop.Transparent) != 0;
                result["no_activate"] = (styles&WindowInterop.NoActivate) != 0;
                result["tool_window"] = (styles&WindowInterop.ToolWindow) != 0;
                result["dpi"] = WindowInterop.GetDpiForWindow(handle);
                result["width_pixels"] = rectangle.Right-rectangle.Left;
                result["height_pixels"] = rectangle.Bottom-rectangle.Top;
                // Desktop alpha must leave the HWND alive for capture.
                window.Opacity = 0;
                result["desktop_hidden_hwnd_visible"] = WindowInterop.IsWindowVisible(handle);
                result["browser_loaded"] = System.Diagnostics.Process.GetCurrentProcess().Modules
                    .Cast<System.Diagnostics.ProcessModule>().Any(module =>
                        module.ModuleName.Contains("WebView", StringComparison.OrdinalIgnoreCase)
                        || module.ModuleName.Contains("WebEngine", StringComparison.OrdinalIgnoreCase));
                exitCode = result["visible"] is true && result["click_through"] is true
                           && result["no_activate"] is true && result["tool_window"] is false
                           && result["desktop_hidden_hwnd_visible"] is true && result["browser_loaded"] is false ? 0 : 1;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
            File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented=true }));
            window.Close();
            application.Shutdown(exitCode);
        };
        window.Show();
        timer.Start();
        return application.Run();
    }

    private sealed class ProbeCanvas : FrameworkElement
    {
        protected override void OnRender(DrawingContext context)
        {
            context.DrawRectangle(new SolidColorBrush(Color.FromArgb(220, 24, 26, 28)), null, new Rect(RenderSize));
            context.DrawRectangle(Brushes.Yellow, null, new Rect(0, 0, ActualWidth, 3));
            context.DrawText(new FormattedText("Endfield Logs - Enhanced", System.Globalization.CultureInfo.CurrentUICulture,
                FlowDirection.LeftToRight, new Typeface("Segoe UI"), 20, Brushes.White,
                VisualTreeHelper.GetDpi(this).PixelsPerDip), new Point(18, 24));
        }
    }
}
