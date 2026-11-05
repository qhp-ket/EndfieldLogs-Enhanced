using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Immediate module commands. Product windows draw directly; WPF is only a reference/screenshot adapter.</summary>
internal abstract class OverlayDrawContext
{
    internal abstract void DrawRectangle(Brush? brush, Pen? pen, Rect rect);
    internal abstract void DrawRoundedRectangle(Brush? brush, Pen? pen, Rect rect, double radiusX, double radiusY);
    internal abstract void DrawEllipse(Brush? brush, Pen? pen, Point center, double radiusX, double radiusY);
    internal abstract void DrawLine(Pen pen, Point from, Point to);
    internal abstract void DrawGeometry(Brush? brush, Pen? pen, Geometry geometry);
    internal abstract void DrawImage(BitmapSource image, Rect rect);
    internal abstract void DrawDrawing(Drawing drawing);
    internal abstract void DrawText(FormattedText text, Drawing drawing, Point origin);
    internal abstract void PushTransform(Transform transform);
    internal abstract void PushClip(Geometry clip);
    internal virtual void PushScale(double scale) => PushTransform(new ScaleTransform(scale, scale));
    internal virtual void PushTranslation(double x, double y) => PushTransform(new TranslateTransform(x, y));
    internal virtual void PushClip(Rect clip) => PushClip(new RectangleGeometry(clip));
    internal abstract void Pop();
}

internal sealed class WpfOverlayDrawContext(DrawingContext context) : OverlayDrawContext
{
    internal override void DrawRectangle(Brush? brush, Pen? pen, Rect rect) => context.DrawRectangle(brush, pen, rect);
    internal override void DrawRoundedRectangle(Brush? brush, Pen? pen, Rect rect, double radiusX, double radiusY) => context.DrawRoundedRectangle(brush, pen, rect, radiusX, radiusY);
    internal override void DrawEllipse(Brush? brush, Pen? pen, Point center, double radiusX, double radiusY) => context.DrawEllipse(brush, pen, center, radiusX, radiusY);
    internal override void DrawLine(Pen pen, Point from, Point to) => context.DrawLine(pen, from, to);
    internal override void DrawGeometry(Brush? brush, Pen? pen, Geometry geometry) => context.DrawGeometry(brush, pen, geometry);
    internal override void DrawImage(BitmapSource image, Rect rect) => context.DrawImage(image, rect);
    internal override void DrawDrawing(Drawing drawing) => context.DrawDrawing(drawing);
    internal override void DrawText(FormattedText text, Drawing drawing, Point origin) => context.DrawText(text, origin);
    internal override void PushTransform(Transform transform) => context.PushTransform(transform);
    internal override void PushClip(Geometry clip) => context.PushClip(clip);
    internal override void Pop() => context.Pop();
}
