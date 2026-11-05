using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Draws an owned thumbnail and maps selection through its letterboxed viewport.</summary>
internal sealed class VisionPreviewCanvas : FrameworkElement
{
    private WriteableBitmap? bitmap;
    private IReadOnlyList<HudSlotRegions> regions = [];
    private Point? dragStart, dragEnd;
    internal event Action<HudRegion>? RegionSelected;
    internal Rect ImageRect => bitmap is null ? Rect.Empty : Fit(new(bitmap.PixelWidth, bitmap.PixelHeight), RenderSize);
    internal long? TargetWindow { get; private set; }
    internal int SelectedSlot { get; set; }
    internal string SelectedRegion { get; set; } = "energy";
    internal BitmapSource? Image => bitmap;
    internal static Rect Fit(Size image, Size available)
    {
        if (image.Width <= 0 || image.Height <= 0 || available.Width <= 0 || available.Height <= 0) return Rect.Empty;
        var scale = Math.Min(available.Width / image.Width, available.Height / image.Height); var width = image.Width * scale; var height = image.Height * scale;
        return new((available.Width - width) / 2, (available.Height - height) / 2, width, height);
    }
    internal VisionPreviewCanvas()
    {
        MinHeight = 120; ClipToBounds = true; Cursor = Cursors.Cross; Focusable = true;
        MouseLeftButtonDown += (_, args) => { if (BeginSelection(args.GetPosition(this))) { CaptureMouse(); args.Handled = true; } };
        MouseMove += (_, args) => { if (dragStart is not null) { dragEnd = args.GetPosition(this); InvalidateVisual(); } };
        MouseLeftButtonUp += (_, args) => { if (dragStart is not null) { FinishSelection(args.GetPosition(this)); ReleaseMouseCapture(); args.Handled = true; } };
        LostMouseCapture += (_, _) => { dragStart = dragEnd = null; InvalidateVisual(); };
        SizeChanged += (_, _) => InvalidateVisual();
    }
    internal void SetPreview(VisionPreview preview)
    {
        if (preview.Width <= 0 || preview.Height <= 0 || preview.Bgra.Length != checked(preview.Width * preview.Height * 4)) throw new ArgumentException("预览像素尺寸无效");
        if (bitmap?.PixelWidth != preview.Width || bitmap.PixelHeight != preview.Height) bitmap = new(preview.Width, preview.Height, 96, 96, PixelFormats.Bgra32, null);
        bitmap.WritePixels(new Int32Rect(0, 0, preview.Width, preview.Height), preview.Bgra, preview.Width * 4, 0); TargetWindow = preview.Window; InvalidateVisual();
    }
    internal void SetRegions(IReadOnlyList<HudSlotRegions> value) { if (regions.SequenceEqual(value)) return; regions = value.ToArray(); InvalidateVisual(); }
    internal void ClearPreview() { bitmap = null; TargetWindow = null; dragStart = dragEnd = null; InvalidateVisual(); }
    internal bool BeginSelection(Point point)
    {
        if (!ImageRect.Contains(point)) return false; dragStart = dragEnd = point; InvalidateVisual(); return true;
    }
    internal void FinishSelection(Point point)
    {
        if (dragStart is not { } start) return; dragStart = dragEnd = null;
        var area = ImageRect; var selection = new Rect(start, point); selection.Intersect(area);
        if (!selection.IsEmpty && selection.Width >= 2 && selection.Height >= 1)
        {
            var x = (selection.X - area.X) / area.Width; var y = (selection.Y - area.Y) / area.Height;
            RegionSelected?.Invoke(new(x, y, Math.Min(1 - x, selection.Width / area.Width), Math.Min(1 - y, selection.Height / area.Height)));
        }
        InvalidateVisual();
    }
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc); dc.DrawRectangle(new SolidColorBrush(Color.FromRgb(24, 27, 33)), null, new Rect(RenderSize)); var area = ImageRect;
        if (area.IsEmpty)
        {
            var text = new FormattedText("等待游戏画面；预览只在设置窗口可见时生成", CultureInfo.CurrentCulture, FlowDirection.LeftToRight, new Typeface("Microsoft YaHei UI"), 13, Brushes.White, VisualTreeHelper.GetDpi(this).PixelsPerDip);
            dc.DrawText(text, new(Math.Max(8, (ActualWidth - text.Width) / 2), Math.Max(8, (ActualHeight - text.Height) / 2))); return;
        }
        dc.DrawImage(bitmap, area);
        for (var slot = 0; slot < regions.Count; slot++)
        {
            var row = regions[slot];
            foreach (var (kind, region) in new[] { ("energy", row.Energy), ("hp", row.Hp), ("portrait", row.Portrait) })
            {
                var selected = slot == SelectedSlot && kind == SelectedRegion;
                dc.DrawRectangle(null, new Pen(selected ? Brushes.Gold : Brushes.Turquoise, selected ? 2 : 1.2), new Rect(area.X + region.X * area.Width, area.Y + region.Y * area.Height, region.Width * area.Width, region.Height * area.Height));
            }
        }
        if (dragStart is { } begin && dragEnd is { } end) dc.DrawRectangle(null, new Pen(Brushes.Orange, 2) { DashStyle = DashStyles.Dash }, new Rect(begin, end));
    }
}
