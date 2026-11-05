using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Threading;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;
using EndfieldLogs.Native.Windows;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Native layered HWND with on-demand Direct2D drawing. Desktop alpha stays outside the captured pixels.</summary>
internal sealed class OverlayWindow
{
    internal readonly record struct RenderCost(double LayoutMs, double DrawSubmitMs, double PresentMs, long AllocatedBytes);
    internal Action<RenderCost>? RenderMeasured { get; set; }
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetWindowPos(nint hwnd, nint insertAfter, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetWindowText(nint hwnd, string text);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ValidateRect(nint hwnd, nint area);
    [StructLayout(LayoutKind.Sequential)] private struct NativePoint { internal int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct MinMaxInfo { internal NativePoint Reserved, MaxSize, MaxPosition, MinTrack, MaxTrack; }
    [StructLayout(LayoutKind.Sequential)] private struct MouseTracking { internal uint Size, Flags; internal nint Window; internal uint HoverTime; }
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool TrackMouseEvent(ref MouseTracking tracking);
    private readonly Action<OverlaySettings> changed;
    private NativeSkin skin;
    private readonly OverlayHost source;
    private readonly OverlayGraphics graphics;
    private ToolTip? tooltip;
    private readonly Dispatcher dispatcher = Dispatcher.CurrentDispatcher;
    private DispatcherOperation? render;
    private DispatcherOperation? geometryCommit;
    private bool disposed, manipulating, fitting, shown, positioning;
    private double contentScale, dpi = 1;
    private double left, top, width, height;
    private double presentedOpacity = double.NaN;
    internal OverlaySettings Entry { get; private set; }
    internal OverlayCanvas Canvas { get; }
    internal bool DesktopVisible { get; private set; }
    internal nint Handle => source.Handle;
    internal bool HardwareRendering => graphics.Hardware;
    internal bool IsVisible => !disposed && WindowInterop.IsWindowVisible(Handle);
    internal double ActualWidth => width;
    internal double ActualHeight => height;
    internal double Width { get => width; set { contentScale = value / Canvas.NaturalSize.Width; Fit(); } }
    internal double Height { get => height; set { contentScale = value / Canvas.NaturalSize.Height; Fit(); } }
    internal double Left => left;
    internal double Top => top;
    private double MinWidth => OverlayDrawing.Parameter(skin.Window, "min_width", 80);
    private double MinHeight => OverlayDrawing.Parameter(skin.Window, "min_height", 36);
    private string ScaleKey => Entry.SourceValue switch { "damage" => "_damage_window_scale", "combo_skill" => "_combo_window_scale", _ => "_native_window_scale" };
    internal OverlayWindow(OverlaySettings entry, NativeSkin skin, AvatarCache avatars, Action<OverlaySettings> changed, OverlayGraphicsDevice? graphicsDevice = null)
    {
        this.skin = skin; this.changed = changed; Entry = entry;
        Canvas = new OverlayCanvas(avatars).Apply(entry, skin);
        source = new(entry.Name) { Message = Hook };
        try { graphics = new(Handle, graphicsDevice); }
        catch { source.Dispose(); throw; }
        dpi = Math.Max(1u, WindowInterop.GetDpiForWindow(Handle)) / 96d; Canvas.SetDpi(dpi);
        contentScale = OverlayDrawing.Number(entry.TemplateSettings.Get(ScaleKey)) ?? entry.Scale;
        ApplyGeometry(entry.Geometry); ApplyDesktop(!entry.Hidden);
        Canvas.NaturalSizeChanged += Fit; Canvas.Invalidated += QueueRender;
    }
    internal void Show()
    {
        if (disposed) return;
        shown = true; Fit(); RenderSurface();
        positioning = true;
        try { SetWindowPos(Handle, (nint)(-1), (int)Math.Round(left * dpi), (int)Math.Round(top * dpi), (int)Math.Ceiling(width * dpi), (int)Math.Ceiling(height * dpi), 0x0010 | 0x0040); }
        finally { positioning = false; }
    }
    internal void Apply(OverlaySettings entry, NativeSkin nextSkin)
    {
        graphics.DiscardImages();
        var previous = Entry; Entry = entry; skin = nextSkin; SetWindowText(Handle, entry.Name);
        if (entry.Geometry != previous.Geometry)
        {
            contentScale = entry.Geometry is null ? 1 : Math.Min(entry.Geometry.Width / Canvas.NaturalSize.Width, entry.Geometry.Height / Canvas.NaturalSize.Height);
            ApplyGeometry(entry.Geometry);
            QueueGeometryCommit();
        }
        Canvas.ShowClose = !entry.ClickThrough; Canvas.Apply(entry, skin); ApplyDesktop(!entry.Hidden);
        Fit();
    }
    internal void ApplyDesktop(bool visible)
    {
        DesktopVisible = visible; Canvas.ShowClose = !Entry.ClickThrough;
        WindowInterop.ConfigureOverlay(Handle, Entry.ClickThrough || !visible);
        CloseTooltip();
        if (shown) Present();
    }
    private void ApplyGeometry(OverlayGeometry? geometry)
    {
        fitting = true;
        try
        {
            width = Math.Max(MinWidth, geometry?.Width ?? OverlayDrawing.Parameter(skin.Window, "default_width", 400));
            height = Math.Max(MinHeight, geometry?.Height ?? OverlayDrawing.Parameter(skin.Window, "default_height", 160));
            if (geometry is { } rect) { left = rect.X; top = rect.Y; }
            else DefaultPosition(); Position();
        }
        finally { fitting = false; }
        QueueGeometryCommit();
    }
    private void DefaultPosition()
    {
        var area = SystemParameters.WorkArea;
        left = Canvas.UidOnly ? area.Left + 12 : Math.Max(area.Left, area.Right - width - 24);
        top = Canvas.UidOnly ? area.Bottom - height - 10 : area.Top + 50;
    }
    private void Fit()
    {
        if (!shown || manipulating || fitting) return;
        var natural = Canvas.NaturalSize; if (natural.Width <= 0 || natural.Height <= 0) return;
        fitting = true;
        try
        {
            var bounds = OverlayScreen.WorkArea(Handle, dpi);
            contentScale = Math.Max(contentScale, Math.Max(MinWidth / natural.Width, MinHeight / natural.Height));
            contentScale = Math.Min(contentScale, Math.Min(Math.Max(MinWidth, bounds.Width) / natural.Width, Math.Max(MinHeight, bounds.Height) / natural.Height));
            var right = left + width;
            width = Math.Ceiling(natural.Width * contentScale); height = Math.Ceiling(natural.Height * contentScale);
            if (Entry.Geometry is null) DefaultPosition();
            else { left = Math.Clamp(right - width, bounds.Left, Math.Max(bounds.Left, bounds.Right - width)); top = Math.Clamp(top, bounds.Top, Math.Max(bounds.Top, bounds.Bottom - height)); }
            Position();
        }
        finally { fitting = false; }
        QueueGeometryCommit();
    }
    private void Position()
    {
        if (disposed) return;
        positioning = true;
        try { SetWindowPos(Handle, 0, (int)Math.Round(left * dpi), (int)Math.Round(top * dpi), (int)Math.Ceiling(width * dpi), (int)Math.Ceiling(height * dpi), 0x0010 | 0x0004); }
        finally { positioning = false; }
        QueueRender();
    }
    private void QueueRender()
    {
        if (disposed || !shown || render?.Status == DispatcherOperationStatus.Pending) return;
        render = dispatcher.BeginInvoke(DispatcherPriority.Render, new Action(() => { render = null; if (!disposed) RenderSurface(); }));
    }
    private void RenderSurface()
    {
        var measured = RenderMeasured;
        var started = measured is null ? 0 : Stopwatch.GetTimestamp();
        var allocated = measured is null ? 0 : GC.GetAllocatedBytesForCurrentThread();
        Canvas.ArrangeSurface(new(width, height));
        var layoutDone = measured is null ? 0 : Stopwatch.GetTimestamp();
        var pixelsX = Math.Max(1, (int)Math.Ceiling(width * dpi)); var pixelsY = Math.Max(1, (int)Math.Ceiling(height * dpi));
        graphics.Render(Canvas, pixelsX, pixelsY, dpi);
        Canvas.MarkPresented();
        var drawDone = measured is null ? 0 : Stopwatch.GetTimestamp();
        Present();
        if (measured is not null) measured(new(Stopwatch.GetElapsedTime(started, layoutDone).TotalMilliseconds,
            Stopwatch.GetElapsedTime(layoutDone, drawDone).TotalMilliseconds,
            Stopwatch.GetElapsedTime(drawDone).TotalMilliseconds, GC.GetAllocatedBytesForCurrentThread() - allocated));
    }
    private void Present()
    {
        if (disposed) return;
        positioning = true;
        try
        {
            var opacity = DesktopVisible ? Entry.Opacity : 0;
            if (presentedOpacity != opacity) { source.SetOpacity(opacity); presentedOpacity = opacity; }
        }
        finally { positioning = false; }
    }
    internal Point PointToScreen(Point point) => new((left + point.X) * dpi, (top + point.Y) * dpi);
    internal void UpdateLayout() { render?.Abort(); render = null; if (!disposed) RenderSurface(); }
    internal void CommitGeometry()
    {
        if (fitting || disposed) return;
        contentScale = Math.Min(width / Canvas.NaturalSize.Width, height / Canvas.NaturalSize.Height);
        var geometry = new OverlayGeometry((int)Math.Round(left), (int)Math.Round(top), (int)Math.Round(width), (int)Math.Round(height));
        if (Entry.Geometry == geometry && OverlayDrawing.Number(Entry.TemplateSettings.Get(ScaleKey)) == contentScale) return;
        var values = Entry.TemplateSettings.Fields.ToDictionary(); values[ScaleKey] = new EvidenceReal(contentScale);
        Entry = Entry with { Geometry = geometry, TemplateSettings = new(values) }; changed(Entry);
    }
    private void QueueGeometryCommit()
    {
        if (!shown || disposed || geometryCommit?.Status == DispatcherOperationStatus.Pending) return;
        geometryCommit = dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() => { geometryCommit = null; if (!manipulating) CommitGeometry(); }));
    }
    private nint Hook(nint hwnd, int message, nint wParam, nint lParam, ref bool handled)
    {
        if (disposed) return 0;
        if (message == 0x21) { handled = true; return 3; }
        if (message == 0x231) { manipulating = true; CloseTooltip(); }
        if (message == 0x232)
        {
            manipulating = false;
            contentScale = Math.Min(width / Canvas.NaturalSize.Width, height / Canvas.NaturalSize.Height);
            Fit();
            CommitGeometry();
        }
        if (message == 0x214)
        {
            var rect = Marshal.PtrToStructure<WindowRectangle>(lParam);
            var edge = (int)wParam;
            var size = ConstrainSize(new((rect.Right - rect.Left) / dpi, (rect.Bottom - rect.Top) / dpi),
                new(width, height), Canvas.NaturalSize, edge, MinWidth, MinHeight);
            var pixelsX = (int)Math.Ceiling(size.Width * dpi); var pixelsY = (int)Math.Ceiling(size.Height * dpi);
            if (edge is 1 or 4 or 7) rect.Left = rect.Right - pixelsX; else rect.Right = rect.Left + pixelsX;
            if (edge is 3 or 4 or 5) rect.Top = rect.Bottom - pixelsY; else rect.Bottom = rect.Top + pixelsY;
            Marshal.StructureToPtr(rect, lParam, false); handled = true; return 1;
        }
        if (message == 0x2e0)
        {
            var rect = Marshal.PtrToStructure<WindowRectangle>(lParam); dpi = ((long)wParam & 0xffff) / 96d;
            left = rect.Left / dpi; top = rect.Top / dpi; width = (rect.Right - rect.Left) / dpi; height = (rect.Bottom - rect.Top) / dpi;
            Canvas.SetDpi(dpi); Position(); handled = true; return 0;
        }
        if (message == 0x47 && !positioning && WindowInterop.GetWindowRect(hwnd, out var bounds))
        {
            var newWidth = (bounds.Right - bounds.Left) / dpi; var newHeight = (bounds.Bottom - bounds.Top) / dpi;
            left = bounds.Left / dpi; top = bounds.Top / dpi;
            if (width != newWidth || height != newHeight) { width = newWidth; height = newHeight; QueueRender(); }
        }
        if (message == 0xf) { ValidateRect(hwnd, 0); QueueRender(); handled = true; return 0; }
        if (message == 0x24)
        {
            var limits = Marshal.PtrToStructure<MinMaxInfo>(lParam);
            limits.MinTrack = new() { X = (int)Math.Ceiling(MinWidth * dpi), Y = (int)Math.Ceiling(MinHeight * dpi) };
            Marshal.StructureToPtr(limits, lParam, false); handled = true; return 0;
        }
        if (message == 0x10) { Close(); handled = true; return 0; }
        var raw = (long)lParam;
        var screen = new Point((short)(raw & 0xffff), (short)((raw >> 16) & 0xffff));
        var point = new Point(screen.X / dpi - left, screen.Y / dpi - top);
        if (message == 0x84 && DesktopVisible && !Entry.ClickThrough)
        {
            handled = true;
            if (OverClose(point)) return 1;
            if (Entry.Locked) return 1;
            var edgeLeft = point.X <= 6; var right = point.X >= width - 6; var edgeTop = point.Y <= 6; var bottom = point.Y >= height - 6;
            return edgeTop ? edgeLeft ? 13 : right ? 14 : 12 : bottom ? edgeLeft ? 16 : right ? 17 : 15 : edgeLeft ? 10 : right ? 11 : 2;
        }
        if (message == 0x202)
        {
            point = new(screen.X / dpi, screen.Y / dpi);
            if (OverClose(point)) { Close(); handled = true; }
        }
        if ((message == 0x200 || message == 0xa0) && !manipulating && DesktopVisible && !Entry.ClickThrough)
        {
            var tracking = new MouseTracking { Size = (uint)Marshal.SizeOf<MouseTracking>(), Window = hwnd, Flags = message == 0xa0 ? 0x12u : 2u }; TrackMouseEvent(ref tracking);
            if (message == 0x200) point = new(screen.X / dpi, screen.Y / dpi);
            var tip = OverClose(point) ? "隐藏此悬浮窗（分析继续运行）" : Canvas.TooltipAt(point);
            if (tip.Length == 0) { CloseTooltip(); return 0; }
            tooltip ??= new() { Placement = PlacementMode.AbsolutePoint, StaysOpen = true };
            if (!Equals(tooltip.Content, tip)) { tooltip.IsOpen = false; tooltip.Content = tip; }
            var location = PointToScreen(point); tooltip.HorizontalOffset = location.X / dpi + 12; tooltip.VerticalOffset = location.Y / dpi + 18; tooltip.IsOpen = true;
        }
        if (message is 0x2a2 or 0x2a3) CloseTooltip();
        return 0;
    }
    private void CloseTooltip() { if (tooltip is not null) tooltip.IsOpen = false; }
    internal static Size ConstrainSize(Size requested, Size original, Size natural, int edge, double minimumWidth, double minimumHeight)
    {
        var horizontal = edge is 1 or 2 or 4 or 5 or 7 or 8;
        var vertical = edge is 3 or 4 or 5 or 6 or 7 or 8;
        var useWidth = horizontal && (!vertical || Math.Abs(requested.Width / original.Width - 1) >= Math.Abs(requested.Height / original.Height - 1));
        var scale = Math.Max(useWidth ? requested.Width / natural.Width : requested.Height / natural.Height,
            Math.Max(minimumWidth / natural.Width, minimumHeight / natural.Height));
        return new(Math.Ceiling(natural.Width * scale), Math.Ceiling(natural.Height * scale));
    }
    private bool OverClose(Point point) => !Entry.ClickThrough && point.X >= width - 34 && point.X <= width - 6 && point.Y is >= 6 and <= 34;
    internal void Close() { if (disposed) return; Entry = Entry with { Hidden = true }; ApplyDesktop(false); changed(Entry); }
    internal void DisposeWindow()
    {
        if (disposed) return; disposed = true; render?.Abort(); geometryCommit?.Abort(); CloseTooltip();
        Canvas.Invalidated -= QueueRender; Canvas.NaturalSizeChanged -= Fit; graphics.Dispose(); source.Dispose();
    }
}
