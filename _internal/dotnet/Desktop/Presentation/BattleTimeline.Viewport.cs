using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    private double viewportX, viewportY, viewportWidth, viewportHeight;
    private double? fittedWidth;
    private bool collectLabels, resizingLabels, dividerHovered;
    private double resizeStartX, resizeStartWidth;
    private readonly List<(string Value, Point At, Brush Brush, double Size, double Width)> labelText = [];
    private double ContentWidth => fittedWidth ?? Labels + Math.Max(120, (viewportWidth > 0 ? viewportWidth : 760) - Labels - 10) * zoom + 10;
    private double CharacterWidth => Math.Clamp(Labels * 17 / 30, 90, 240);
    internal double LabelWidth => Labels;
    internal double PinnedLabelLeft => viewportX;
    internal double StickyHeaderTop => Math.Clamp(viewportY, 0, Math.Max(0, ActualHeight - Header));
    private bool VisibleX(double left, double right, double margin = 4) => viewportWidth <= 0
        || right >= viewportX + Labels - margin && left <= viewportX + viewportWidth + margin;
    private bool VisibleY(double top, double bottom) => viewportHeight <= 0 || bottom >= viewportY && top <= viewportY + viewportHeight;
    private (int First, int End) VisibleSamples<T>(IReadOnlyList<T> samples, Func<T, double> time, bool neighbors = false)
    {
        if (viewportWidth <= 0) return (0, samples.Count);
        var factor = Duration / Math.Max(1, ActualWidth - Labels - 10);
        var first = Bound((viewportX - 4) * factor, false);
        var end = Bound((viewportX + viewportWidth - Labels + 4) * factor, true);
        return neighbors ? (Math.Max(0, first - 1), Math.Min(samples.Count, end + 1)) : (first, end);
        int Bound(double value, bool after)
        {
            var low = 0; var high = samples.Count;
            while (low < high)
            {
                var middle = low + (high - low) / 2; var at = time(samples[middle]);
                if (at < value || after && at == value) low = middle + 1; else high = middle;
            }
            return low;
        }
    }
    internal event Action<double>? LabelWidthChanged;
    internal void SetViewport(double horizontal, double vertical, double width, double height = 0)
    {
        if (viewportX == horizontal && viewportY == vertical && viewportWidth == width && viewportHeight == height) return;
        if (viewportWidth != width) { trackCache = null; inputLayout = null; InvalidateMeasure(); }
        viewportX = horizontal; viewportY = vertical; viewportWidth = width; viewportHeight = height;
        if (fittedWidth is not null && Math.Abs(fittedWidth.Value - width) > 1) FitToWindow(width);
        InvalidateVisual();
    }
    internal void FitToWindow(double width)
    { fittedWidth = Math.Max(Labels + 120, width); trackCache = null; inputLayout = null; InvalidateMeasure(); InvalidateVisual(); }
    private void BeginLabelResize(Point point)
    { resizingLabels = true; resizeStartX = point.X; resizeStartWidth = Labels; CaptureMouse(); Cursor = Cursors.SizeWE; }
    internal void ResizeLabels(double width)
    {
        var value = Math.Clamp(width, 160, 440); if (Labels == value) return;
        Labels = value; trackCache = null; inputLayout = null; LabelWidthChanged?.Invoke(value); InvalidateMeasure(); InvalidateVisual();
    }
    private void DrawPinnedLabels(DrawingContext dc, IReadOnlyList<(double Stamp, double X)> ticks, IReadOnlyList<Track> tracks, double rowHeight)
    {
        var ink = Ink; var border = labelPen;
        dc.DrawRectangle(CanvasBackground, null, new(viewportX, 0, Labels, ActualHeight));
        DrawPortraits(dc, tracks, rowHeight);
        foreach (var label in labelText) Text(dc, label.Value, new(label.At.X + viewportX, label.At.Y), label.Brush, label.Size, label.Width);
        var row = 0;
        foreach (var track in tracks)
        {
            var y = Header + row * rowHeight; var end = y + track.Rows * rowHeight;
            dc.DrawLine(border, new(viewportX + CharacterWidth, end), new(viewportX + Labels, end));
            row += track.Rows;
        }
        dc.DrawLine(border, new(viewportX + CharacterWidth, Header), new(viewportX + CharacterWidth, Header + row * rowHeight));
        var handle = dividerHovered || resizingLabels ? labelHandlePen : labelDividerPen;
        dc.DrawLine(handle, new(viewportX + Labels, 0), new(viewportX + Labels, ActualHeight));
        var top = StickyHeaderTop; var width = Math.Max(1, viewportWidth > 0 ? viewportWidth : ActualWidth);
        dc.DrawRectangle(CanvasBackground, null, new(viewportX, top, width, Header));
        foreach (var (stamp, x) in ticks.Where(tick => tick.X >= viewportX + Labels && tick.X <= viewportX + width))
            Text(dc, frames ? $"{stamp / 1000 * 30:N0}F" : $"{stamp / 1000:N1}s", new(x + 3, top + 6), ink);
        Text(dc, frames ? "时间／30F" : "时间／秒", new(viewportX + 6, top + 6), ink);
        dc.DrawLine(border, new(viewportX, top + Header), new(viewportX + width, top + Header));
    }
}
