using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Presentation;

internal static class WindowPlacement
{
    internal static Rect Fit(Rect work, Size preferred, Size minimum, Point? center = null)
    {
        var width = Math.Min(Math.Max(minimum.Width, preferred.Width), Math.Max(1, work.Width - 40));
        var height = Math.Min(Math.Max(minimum.Height, preferred.Height), Math.Max(1, work.Height - 60));
        var at = center ?? new Point(work.Left + work.Width / 2, work.Top + work.Height / 2);
        return new(Math.Clamp(at.X - width / 2, work.Left, work.Right - width), Math.Clamp(at.Y - height / 2, work.Top, work.Bottom - height), width, height);
    }
    internal static void Initialize(Window window)
    {
        window.WindowStartupLocation = WindowStartupLocation.Manual;
        window.SourceInitialized += (_, _) =>
        {
            var anchor = window.Owner ?? window; var scale = VisualTreeHelper.GetDpi(anchor).DpiScaleX;
            var work = OverlayScreen.WorkArea(new WindowInteropHelper(anchor).Handle, scale);
            var center = window.Owner is { } owner ? new Point(owner.Left + owner.ActualWidth / 2, owner.Top + owner.ActualHeight / 2) : (Point?)null;
            var bounds = Fit(work, new(window.Width, window.Height), new(window.MinWidth, window.MinHeight), center);
            window.MinWidth = Math.Min(window.MinWidth, bounds.Width); window.MinHeight = Math.Min(window.MinHeight, bounds.Height);
            window.Width = bounds.Width; window.Height = bounds.Height; window.Left = bounds.Left; window.Top = bounds.Top;
        };
    }
}
