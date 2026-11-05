using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>WPF adapter for reference screenshots and the explicit alternative-host experiment only.</summary>
internal sealed class OverlayCanvasReference : FrameworkElement
{
    private readonly OverlayCanvas canvas;
    internal OverlayCanvasReference(OverlayCanvas canvas)
    {
        this.canvas = canvas;
        canvas.Invalidated += InvalidateVisual;
        MouseMove += (_, args) =>
        {
            var tip = canvas.TooltipAt(args.GetPosition(this));
            if (!Equals(ToolTip, tip)) ToolTip = tip.Length > 0 ? tip : null;
        };
    }
    protected override Size ArrangeOverride(Size size) { canvas.ArrangeSurface(size); return size; }
    protected override void OnDpiChanged(DpiScale oldDpi, DpiScale newDpi)
    { base.OnDpiChanged(oldDpi, newDpi); canvas.SetDpi(newDpi.PixelsPerDip); }
    protected override void OnRender(DrawingContext context)
    { canvas.DrawContents(new WpfOverlayDrawContext(context)); canvas.MarkPresented(); }
    internal static void Render(RenderTargetBitmap target, OverlayCanvas canvas)
    {
        DrawingVisual visual = new();
        using (var context = visual.RenderOpen()) canvas.DrawContents(new WpfOverlayDrawContext(context));
        target.Render(visual);
    }
}
