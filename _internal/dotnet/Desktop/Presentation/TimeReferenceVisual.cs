using System.Windows;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Transient cursor commands live apart from the retained report drawing and hit indexes.</summary>
internal sealed class TimeReferenceVisual : DrawingVisual
{
    private static readonly Pen pen = CreatePen();
    private (double? X, double Top, double Bottom, string? Label, double FontSize, Brush? Ink, Brush? Background, double Left, double Right, double Dpi)? position;
    private static Pen CreatePen()
    {
        Pen value = new(Brushes.SlateGray, 1) { DashStyle = DashStyles.Dot };
        value.Freeze(); return value;
    }
    internal void Set(double? x, double top, double bottom, string? label = null, double fontSize = 14,
        Brush? ink = null, Brush? background = null, double left = 0, double right = double.PositiveInfinity, double dpi = 1)
    {
        var next = (x, top, bottom, label, fontSize, ink, background, left, right, dpi); if (position == next) return;
        position = next;
        using var dc = RenderOpen();
        if (x is { } at && bottom > top) dc.DrawLine(pen, new(at, top), new(at, bottom));
        if (x is { } anchor && label is not null)
        {
            var text = new FormattedText(label, System.Globalization.CultureInfo.CurrentCulture, FlowDirection.LeftToRight,
                new Typeface("Microsoft YaHei UI"), fontSize, ink ?? Brushes.Black, dpi);
            var width = text.Width + 10; var height = text.Height + 4;
            var area = new Rect(Math.Clamp(anchor + 6, left, Math.Max(left, right - width)), Math.Max(0, top - height), width, height);
            dc.DrawRoundedRectangle(background ?? Brushes.White, null, area, 3, 3);
            dc.DrawText(text, new(area.X + 5, area.Y + 2));
        }
    }
    protected override HitTestResult? HitTestCore(PointHitTestParameters parameters) => null;
}
