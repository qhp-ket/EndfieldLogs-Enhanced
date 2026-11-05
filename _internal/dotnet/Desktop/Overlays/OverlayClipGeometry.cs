using System.Numerics;
using System.Windows;
using System.Windows.Media;
using Vortice.Direct2D1;
using D2D = Vortice.Direct2D1;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Reuse the exact flattened portrait masks; geometries belong to the factory, not a frame.</summary>
internal sealed class OverlayClipGeometry(ID2D1Factory factory) : IDisposable
{
    private readonly record struct Key(Point Center, double RadiusX, double RadiusY, double Dpi);
    private readonly Dictionary<Key, ID2D1PathGeometry> ellipses = [];
    private readonly Queue<Key> order = [];
    private readonly List<ID2D1PathGeometry> retired = [];
    internal int Count => ellipses.Count;
    internal ID2D1PathGeometry Acquire(EllipseGeometry ellipse, double dpi)
    {
        var key = new Key(ellipse.Center, ellipse.RadiusX, ellipse.RadiusY, dpi);
        if (ellipses.TryGetValue(key, out var cached)) return cached;
        var geometry = Create(factory, ellipse, dpi);
        if (ellipses.Count == 64)
        {
            var oldest = order.Dequeue(); retired.Add(ellipses[oldest]); ellipses.Remove(oldest);
        }
        order.Enqueue(key); ellipses.Add(key, geometry); return geometry;
    }
    // A resized skin can evict a mask still referenced by a nested layer in this frame.
    // Retire after EndDraw, never while the layer stack is using it.
    internal void EndFrame() { foreach (var geometry in retired) geometry.Dispose(); retired.Clear(); }
    internal static ID2D1PathGeometry Create(ID2D1Factory factory, Geometry geometry, double dpi)
    {
        var path = geometry.GetFlattenedPathGeometry(.025 / Math.Max(1, dpi), ToleranceType.Absolute);
        var transform = path.Transform?.Value ?? Matrix.Identity;
        static Vector2 Point(System.Windows.Point point) => new((float)point.X, (float)point.Y);
        var native = factory.CreatePathGeometry();
        try
        {
            using var sink = native.Open();
            sink.SetFillMode(path.FillRule == FillRule.EvenOdd ? FillMode.Alternate : FillMode.Winding);
            foreach (var figure in path.Figures)
            {
                sink.BeginFigure(Point(transform.Transform(figure.StartPoint)), figure.IsFilled ? FigureBegin.Filled : FigureBegin.Hollow);
                foreach (var segment in figure.Segments)
                {
                    sink.SetSegmentFlags(segment.IsStroked ? D2D.PathSegment.None : D2D.PathSegment.ForceUnstroked);
                    if (segment is LineSegment line) sink.AddLine(Point(transform.Transform(line.Point)));
                    else if (segment is PolyLineSegment lines) foreach (var point in lines.Points) sink.AddLine(Point(transform.Transform(point)));
                    else throw new NotSupportedException("未展开的悬浮窗曲线");
                }
                sink.EndFigure(figure.IsClosed ? FigureEnd.Closed : FigureEnd.Open);
            }
            sink.Close(); return native;
        }
        catch { native.Dispose(); throw; }
    }
    public void Dispose()
    {
        EndFrame(); foreach (var geometry in ellipses.Values) geometry.Dispose(); ellipses.Clear(); order.Clear();
    }
}
