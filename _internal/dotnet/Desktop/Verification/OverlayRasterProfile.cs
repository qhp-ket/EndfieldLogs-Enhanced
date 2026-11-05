using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Diagnostic raster isolation; never changes the product canvas or its presented image.</summary>
internal static class OverlayRasterProfile
{
    internal static object Measure(OverlayCanvas canvas, double dpi, string output)
    {
        var drawing = canvas.RecordDrawing();
        var counts = new Dictionary<string, int>();
        void Count(Drawing value)
        {
            var name = value.GetType().Name; counts[name] = counts.GetValueOrDefault(name) + 1;
            if (value is DrawingGroup group) foreach (var child in group.Children) Count(child);
        }
        Count(drawing);
        Drawing? Filter(Drawing value, string mode)
        {
            if (value is DrawingGroup group)
            {
                var clone = group.Clone(); clone.Children.Clear();
                if (mode == "no_clips") clone.ClipGeometry = null;
                foreach (var child in group.Children) if (Filter(child, mode) is { } kept) clone.Children.Add(kept);
                return clone.Children.Count == 0 ? null : clone;
            }
            if (value is GlyphRunDrawing && mode is ("no_text" or "geometry")
                || value is ImageDrawing && mode is ("no_images" or "geometry")) return null;
            return value.Clone();
        }
        var width = Math.Max(1, (int)Math.Ceiling(canvas.ActualWidth * dpi));
        var height = Math.Max(1, (int)Math.Ceiling(canvas.ActualHeight * dpi));
        var result = new Dictionary<string, object>();
        foreach (var mode in new[] { "full", "no_clips", "no_images", "no_text", "geometry", "empty" })
        {
            var filtered = mode == "empty" ? new DrawingGroup() : Filter(drawing, mode) ?? new DrawingGroup(); filtered.Freeze();
            DrawingVisual visual = new(); using (var context = visual.RenderOpen()) context.DrawDrawing(filtered);
            RenderTargetBitmap bitmap = new(width, height, 96 * dpi, 96 * dpi, PixelFormats.Pbgra32);
            byte[] pixels = new byte[checked(width * height * 4)];
            bitmap.Render(visual); bitmap.CopyPixels(pixels, width * 4, 0);
            var watch = Stopwatch.StartNew(); double clearMs = 0, drawMs = 0, copyMs = 0;
            for (var index = 0; index < 100; index++)
            {
                var stamp = Stopwatch.GetTimestamp(); bitmap.Clear(); clearMs += Stopwatch.GetElapsedTime(stamp).TotalMilliseconds;
                stamp = Stopwatch.GetTimestamp(); bitmap.Render(visual); drawMs += Stopwatch.GetElapsedTime(stamp).TotalMilliseconds;
                stamp = Stopwatch.GetTimestamp(); bitmap.CopyPixels(pixels, width * 4, 0); copyMs += Stopwatch.GetElapsedTime(stamp).TotalMilliseconds;
            }
            result[mode] = new { frames = 100, elapsed_ms = watch.Elapsed.TotalMilliseconds, clear_ms = clearMs, draw_ms = drawMs, copy_ms = copyMs };
            PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using var image = File.Create(Path.ChangeExtension(output, ".raster-" + mode + ".png")); encoder.Save(image);
        }
        return new { counts, width, height, dpi, variants = result,
            boundary = "retained drawing, frozen copy; remove image/text drawings only for diagnosis; 100 identical raster/copy operations; excludes layout, presentation and analysis" };
    }
}
