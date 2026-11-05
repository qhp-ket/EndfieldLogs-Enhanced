using System.Windows;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Transient cursor commands live apart from the retained report drawing and hit indexes.</summary>
internal sealed class TimeReferenceVisual : DrawingVisual
{
    private static readonly Pen pen = CreatePen();
    private (double? X, double Top, double Bottom)? position;
    private static Pen CreatePen()
    {
        Pen value = new(Brushes.SlateGray, 1) { DashStyle = DashStyles.Dot };
        value.Freeze(); return value;
    }
    internal void Set(double? x, double top, double bottom)
    {
        var next = (x, top, bottom); if (position == next) return;
        position = next;
        using var dc = RenderOpen();
        if (x is { } at && bottom > top) dc.DrawLine(pen, new(at, top), new(at, bottom));
    }
    protected override HitTestResult? HitTestCore(PointHitTestParameters parameters) => null;
}
