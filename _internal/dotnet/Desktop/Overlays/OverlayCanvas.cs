using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Native window content and hit areas, with no WPF visual, layout queue or frame timer.</summary>
internal sealed class OverlayCanvas(AvatarCache avatars)
{
    private Size renderSize;
    internal double ActualWidth => renderSize.Width;
    internal double ActualHeight => renderSize.Height;
    private NativeSkin skin = null!;
    private readonly List<IOverlayModule> modules = [];
    private sealed class ModuleMeasurement
    {
        internal OverlayLayout? Natural, Constrained;
        internal double? Width;
        internal void Invalidate() { Natural = null; Constrained = null; Width = null; }
    }
    private ModuleMeasurement[] measurements = [];
    private readonly List<(IOverlayModule Module, Rect Area, OverlayLayout Layout)> arranged = [];
    private OverlayLayout[] measured = [];
    private BitmapSource? image;
    private double scale = 1;
    private double drawingDpi = 1;
    internal bool ShowClose { get; set; } = true;
    internal Size NaturalSize { get; private set; }
    internal bool Bars => modules.Count == 1 && modules[0] is ComboOverlay && declarations[0].Settings.Get("display_style") is EvidenceText { Value: "bars" };
    internal bool UidOnly => modules.Count == 1 && modules[0] is UidOverlay;
    internal int LayoutRevision { get; private set; }
    internal int PaintRevision { get; private set; }
    internal void MarkPresented() => PaintRevision = LayoutRevision;
    internal IReadOnlyList<(IOverlayModule Module, Rect Area, OverlayLayout Layout)> Arranged => arranged;
    private IReadOnlyList<NativeSkinModule> declarations = [];
    internal event Action? NaturalSizeChanged;
    internal event Action? Invalidated;
    internal void SetDpi(double value) { if (drawingDpi == value) return; drawingDpi = value; if (modules.Count > 0) Relayout(); }
    internal OverlayCanvas Apply(OverlaySettings entry, NativeSkin nextSkin)
    {
        skin = nextSkin; declarations = NativeSkins.ResolveModules(entry, skin);
        if (!modules.Select(module => module.Type).SequenceEqual(declarations.Select(module => module.Type)))
        {
            modules.Clear();
            foreach (var declaration in declarations) modules.Add(declaration.Type switch { "damage" => new DamageOverlay(), "combo_skill" => new ComboOverlay(), _ => new UidOverlay() });
            measurements = modules.Select(_ => new ModuleMeasurement()).ToArray();
        }
        for (var index = 0; index < modules.Count; index++) modules[index].Configure(declarations[index].Settings, skin.Theme);
        image = skin.Theme.Get("image") is EvidenceText path && skin.Path is not null ? AvatarCache.Load(Path.Combine(Path.GetDirectoryName(skin.Path)!, path.Value)) : null;
        Relayout(); return this;
    }
    internal bool Receive(EvidenceObject message)
    {
        var changed = false;
        for (var index = 0; index < modules.Count; index++)
        {
            if (!modules[index].Receive(message)) continue;
            measurements[index].Invalidate(); changed = true;
        }
        if (changed) Relayout(invalidateAll: false); return changed;
    }
    internal void SetConnected(bool connected)
    {
        var changed = false;
        for (var index = 0; index < modules.Count; index++)
        {
            var module = modules[index]; if (module.Connected == connected) continue;
            module.Connected = connected; measurements[index].Invalidate(); changed = true;
        }
        if (changed) Relayout(invalidateAll: false);
    }
    private OverlayLayout MeasureModule(int index, double? width = null)
    {
        var cached = measurements[index];
        if (width is null) return cached.Natural ??= modules[index].Measure(drawingDpi);
        if (cached.Constrained is null || cached.Width != width)
        {
            cached.Constrained = Bars ? ComboOverlay.ArrangeBars(MeasureModule(index), width.Value) : modules[index].Measure(drawingDpi, width);
            cached.Width = width;
        }
        return cached.Constrained;
    }
    private void Relayout(bool invalidateAll = true)
    {
        var previous = NaturalSize;
        // A summary does not invalidate vision or UID layout in a composite skin.
        // Configuration and DPI edits invalidate every module, including width-constrained bars.
        if (invalidateAll) foreach (var cached in measurements) cached.Invalidate();
        if (measured.Length != modules.Count) measured = new OverlayLayout[modules.Count];
        for (var index = 0; index < modules.Count; index++) measured[index] = MeasureModule(index);
        var horizontal = skin.Layout.Get("direction") is EvidenceText { Value: "horizontal" };
        var padding = OverlayDrawing.Parameter(skin.Theme, "padding", 0); var gap = OverlayDrawing.Parameter(skin.Theme, "spacing", 8) * Math.Max(0, modules.Count - 1);
        NaturalSize = new((horizontal ? measured.Sum(layout => layout.Size.Width) + gap : measured.Max(layout => layout.Size.Width)) + 2 * padding,
            (horizontal ? measured.Max(layout => layout.Size.Height) : measured.Sum(layout => layout.Size.Height) + gap) + 2 * padding);
        LayoutRevision++; ArrangeModules(renderSize);
        if (previous != NaturalSize) NaturalSizeChanged?.Invoke();
        Invalidated?.Invoke();
    }
    private void ArrangeModules(Size size)
    {
        if (NaturalSize.Width <= 0 || size.Width <= 0 || size.Height <= 0) return;
        scale = Math.Max(.01, Math.Min(size.Width / NaturalSize.Width, size.Height / NaturalSize.Height));
        var padding = OverlayDrawing.Parameter(skin.Theme, "padding", 0); var gap = OverlayDrawing.Parameter(skin.Theme, "spacing", 8);
        var horizontal = skin.Layout.Get("direction") is EvidenceText { Value: "horizontal" }; var x = padding; var y = padding;
        arranged.Clear();
        for (var index = 0; index < modules.Count; index++)
        {
            var layout = measured[index];
            arranged.Add((modules[index], new(x, y, layout.Size.Width, layout.Size.Height), layout));
            if (horizontal) x += layout.Size.Width + gap; else y += layout.Size.Height + gap;
        }
    }
    internal void ArrangeSurface(Size size)
    {
        if (renderSize == size) return;
        renderSize = size; ArrangeModules(size);
    }
    internal string TooltipAt(Point point)
    {
        var local = new Point(point.X / scale, point.Y / scale);
        return string.Join("\n", arranged.Where(item => item.Area.Contains(local)).Select(item => item.Layout.Tooltip(new(local.X - item.Area.X, local.Y - item.Area.Y))).Where(text => text.Length > 0));
    }
    internal DrawingGroup RecordDrawing()
    {
        DrawingGroup drawing = new();
        using (var recorder = drawing.Open()) DrawContents(new WpfOverlayDrawContext(recorder));
        return drawing;
    }
    internal void DrawContents(OverlayDrawContext context)
    {
        if (arranged.Count == 0) return;
        context.PushScale(scale); var dpi = drawingDpi;
        if (UidOnly) modules[0].Draw(context, new(0, 0, ActualWidth / scale, ActualHeight / scale), arranged[0].Layout, dpi, avatars, dpi * scale);
        else
        {
            var outer = new Rect(0, 0, ActualWidth / scale, ActualHeight / scale);
            var palette = new OverlayPalette(declarations[0].Settings, skin.Theme);
            var radius = OverlayDrawing.Parameter(skin.Theme, "radius", palette.Industrial ? 0 : 8);
            context.DrawRoundedRectangle(palette["background"], OverlayDrawing.Pen(palette["border"], OverlayDrawing.Parameter(skin.Theme, "border_width", .7)), new(.5, .5, Math.Max(0, outer.Width - 1), Math.Max(0, outer.Height - 1)), radius, radius);
            if (image is not null) context.DrawImage(image, outer);
            foreach (var (module, area, layout) in arranged)
            {
                context.PushTranslation(area.X, area.Y); context.PushClip(new Rect(new Point(), area.Size));
                module.Draw(context, new(new Point(), area.Size), layout, dpi, avatars, dpi * scale); context.Pop(); context.Pop();
            }
        }
        context.Pop();
        if (ShowClose)
        {
            var x = ActualWidth - 26;
            context.DrawLine(OverlayDrawing.Pen(OverlayDrawing.Brush("#b0000000"), 3.5), new(x + 2, 14), new(x + 14, 26));
            context.DrawLine(OverlayDrawing.Pen(OverlayDrawing.Brush("#b0000000"), 3.5), new(x + 14, 14), new(x + 2, 26));
            context.DrawLine(OverlayDrawing.Pen(OverlayDrawing.Brush("#dcffffff"), 1.7), new(x + 2, 14), new(x + 14, 26));
            context.DrawLine(OverlayDrawing.Pen(OverlayDrawing.Brush("#dcffffff"), 1.7), new(x + 14, 14), new(x + 2, 26));
        }
    }
}
