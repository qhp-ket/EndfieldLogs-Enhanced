using System.Numerics;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Vortice.Direct2D1;
using Vortice.DirectWrite;
using Vortice.DXGI;
using Vortice.Mathematics;
using D2D = Vortice.Direct2D1;
using Wpf = System.Windows.Media;
using Rect = System.Windows.Rect;
using RectF = Vortice.Mathematics.Rect;
using Color = System.Windows.Media.Color;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Immediate module drawing to a D2D HWND target; only shaped text is retained. No CPU framebuffer or readback.</summary>
internal sealed class OverlayGraphics(nint window, OverlayGraphicsDevice? resources = null, bool preferHardware = true) : OverlayDrawContext, IDisposable
{
    private readonly OverlayGraphicsDevice device = resources ?? new();
    private OverlayClipGeometry? clipGeometry;
    private ID2D1Factory factory => device.Shapes;
    private IDWriteFactory textFactory => device.Text;
    private readonly Dictionary<(Color Color, double Opacity), ID2D1SolidColorBrush> brushes = [];
    private OverlayImageCache? images;
    private readonly Dictionary<GlyphTypeface, IDWriteFontFace?> fonts = [];
    private readonly ConditionalWeakTable<Wpf.GlyphRun, Vortice.DirectWrite.GlyphRun> glyphs = new();
    private readonly Stack<(Matrix3x2 Transform, int Clip, ID2D1PathGeometry? Mask, bool Owned)> states = new();
    private ID2D1RenderTarget? target;
    private int width, height;
    private double dpi;
    internal bool Hardware { get; private set; }
    internal int Frames { get; private set; }

    // The pixel probe owns this WIC target through the renderer; all drawing commands use the product path.
    internal OverlayGraphics(ID2D1RenderTarget bitmapTarget, OverlayGraphicsDevice resources, double scale) : this(0, resources)
    {
        target = bitmapTarget; var size = bitmapTarget.PixelSize; width = size.Width; height = size.Height; dpi = scale;
        target.SetDpi((float)(96 * scale), (float)(96 * scale)); target.TextAntialiasMode = D2D.TextAntialiasMode.Grayscale;
    }

    internal void Render(Drawing drawing, int pixelsX, int pixelsY, double scale) => RenderFrame(drawing, null, pixelsX, pixelsY, scale);
    internal void Render(OverlayCanvas canvas, int pixelsX, int pixelsY, double scale) => RenderFrame(null, canvas, pixelsX, pixelsY, scale);
    private void RenderFrame(Drawing? drawing, OverlayCanvas? canvas, int pixelsX, int pixelsY, double scale)
    {
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                EnsureTarget(pixelsX, pixelsY, scale);
                target!.BeginDraw(); target.Transform = Matrix3x2.Identity;
                target.Clear(new Color4(0, 0, 0, 0));
                if (canvas is not null) canvas.DrawContents(this); else Draw(drawing!);
                target.EndDraw().CheckError(); clipGeometry?.EndFrame(); images?.EndFrame(); Frames++; return;
            }
            catch (SharpGen.Runtime.SharpGenException error) when (error.ResultCode.Code == unchecked((int)0x8899000c) && attempt == 0)
            {
                // D2DERR_RECREATE_TARGET: all target-owned resources must follow the target.
                ReleaseTarget();
            }
        }
    }
    private void EnsureTarget(int x, int y, double scale)
    {
        if (target is null)
        {
            var properties = new RenderTargetProperties(preferHardware ? RenderTargetType.Hardware : RenderTargetType.Software,
                new(Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), (float)(96 * scale), (float)(96 * scale), RenderTargetUsage.None, D2D.FeatureLevel.Default);
            var hwnd = new HwndRenderTargetProperties { Hwnd = window, PixelSize = new(x, y), PresentOptions = PresentOptions.Immediately };
            try { target = factory.CreateHwndRenderTarget(properties, hwnd); Hardware = preferHardware; }
            catch (SharpGen.Runtime.SharpGenException)
            {
                properties.Type = RenderTargetType.Software;
                target = factory.CreateHwndRenderTarget(properties, hwnd); Hardware = false;
            }
            target.TextAntialiasMode = D2D.TextAntialiasMode.Grayscale;
            width = x; height = y; dpi = scale;
        }
        if (width != x || height != y)
        {
            if (target is not ID2D1HwndRenderTarget hwndTarget) throw new InvalidOperationException("位图验证目标尺寸不可变");
            hwndTarget.Resize(new(x, y)); width = x; height = y;
        }
        if (dpi != scale) { target.SetDpi((float)(96 * scale), (float)(96 * scale)); dpi = scale; }
    }
    private static Matrix3x2 Matrix(Wpf.Matrix value) => new((float)value.M11, (float)value.M12, (float)value.M21, (float)value.M22, (float)value.OffsetX, (float)value.OffsetY);
    private static Vector2 Point(System.Windows.Point point) => new((float)point.X, (float)point.Y);
    private static RectF Rectangle(Rect rect) => new((float)rect.X, (float)rect.Y, (float)rect.Width, (float)rect.Height);
    private ID2D1SolidColorBrush Brush(Wpf.Brush brush)
    {
        if (brush is not SolidColorBrush solid) throw new NotSupportedException("悬浮窗绘制仅使用声明式纯色画笔");
        var key = (solid.Color, solid.Opacity);
        if (brushes.TryGetValue(key, out var found)) return found;
        var color = solid.Color;
        return brushes[key] = target!.CreateSolidColorBrush(new(color.R / 255f, color.G / 255f, color.B / 255f, (float)(color.A / 255d * solid.Opacity)));
    }
    private void Draw(Drawing drawing)
    {
        switch (drawing)
        {
            case DrawingGroup group:
                var previous = target!.Transform;
                target.Transform = Matrix(group.Transform?.Value ?? Wpf.Matrix.Identity) * previous;
                var clip = group.ClipGeometry;
                var axis = clip is RectangleGeometry rectangle && rectangle.RadiusX == 0 && rectangle.RadiusY == 0 && (rectangle.Transform?.Value.IsIdentity ?? true);
                ID2D1PathGeometry? mask = null;
                if (axis) target.PushAxisAlignedClip(Rectangle(((RectangleGeometry)clip!).Rect), AntialiasMode.PerPrimitive);
                else if (clip is not null || group.Opacity != 1)
                {
                    if (clip is not null) mask = Geometry(clip);
                    target.PushLayer(new LayerParameters { ContentBounds = new RectF(-1e6f, -1e6f, 2e6f, 2e6f),
                        GeometricMask = mask, MaskTransform = Matrix3x2.Identity, MaskAntialiasMode = AntialiasMode.PerPrimitive, Opacity = (float)group.Opacity }, null);
                }
                // Opacity and a rectangular clip are independent, and both must be retained.
                if (axis && group.Opacity != 1) target.PushLayer(new LayerParameters { ContentBounds = Rectangle(((RectangleGeometry)clip!).Rect), MaskTransform = Matrix3x2.Identity, Opacity = (float)group.Opacity }, null);
                foreach (var child in group.Children) Draw(child);
                if (axis && group.Opacity != 1) target.PopLayer();
                if (axis) target.PopAxisAlignedClip();
                else if (clip is not null || group.Opacity != 1) target.PopLayer();
                mask?.Dispose(); target.Transform = previous;
                break;
            case GeometryDrawing shape: DrawGeometry(shape.Brush, shape.Pen, shape.Geometry); break;
            case GlyphRunDrawing text: Glyphs(text); break;
            case ImageDrawing { ImageSource: BitmapSource image } picture: DrawImage(image, picture.Rect); break;
            default: throw new NotSupportedException("不支持的悬浮窗绘制项：" + drawing.GetType().Name);
        }
    }
    internal override void DrawDrawing(Drawing drawing) => Draw(drawing);
    internal override void DrawText(FormattedText text, Drawing drawing, System.Windows.Point origin)
    {
        var previous = target!.Transform;
        target.Transform = Matrix3x2.CreateTranslation((float)origin.X, (float)origin.Y) * previous;
        Draw(drawing);
        target.Transform = previous;
    }
    internal override void DrawRectangle(Wpf.Brush? brush, Wpf.Pen? pen, Rect rect)
    {
        if (brush is not null) target!.FillRectangle(Rectangle(rect), Brush(brush));
        if (pen is not null) target!.DrawRectangle(Rectangle(rect), Brush(pen.Brush), (float)pen.Thickness);
    }
    internal override void DrawRoundedRectangle(Wpf.Brush? brush, Wpf.Pen? pen, Rect rect, double radiusX, double radiusY)
    {
        if (radiusX == 0 && radiusY == 0) { DrawRectangle(brush, pen, rect); return; }
        RoundedRectangle rounded = new(new System.Drawing.RectangleF((float)rect.X, (float)rect.Y, (float)rect.Width, (float)rect.Height), (float)radiusX, (float)radiusY);
        if (brush is not null) target!.FillRoundedRectangle(rounded, Brush(brush));
        if (pen is not null) target!.DrawRoundedRectangle(rounded, Brush(pen.Brush), (float)pen.Thickness);
    }
    internal override void DrawEllipse(Wpf.Brush? brush, Wpf.Pen? pen, System.Windows.Point center, double radiusX, double radiusY)
    {
        Ellipse oval = new(Point(center), (float)radiusX, (float)radiusY);
        if (brush is not null) target!.FillEllipse(oval, Brush(brush));
        if (pen is not null) target!.DrawEllipse(oval, Brush(pen.Brush), (float)pen.Thickness);
    }
    internal override void DrawLine(Wpf.Pen pen, System.Windows.Point from, System.Windows.Point to)
        => target!.DrawLine(Point(from), Point(to), Brush(pen.Brush), (float)pen.Thickness);
    internal override void DrawGeometry(Wpf.Brush? brush, Wpf.Pen? pen, Wpf.Geometry geometry)
    {
        if (geometry is RectangleGeometry rect && (rect.Transform?.Value.IsIdentity ?? true))
            DrawRoundedRectangle(brush, pen, rect.Rect, rect.RadiusX, rect.RadiusY);
        else if (geometry is EllipseGeometry ellipse && (ellipse.Transform?.Value.IsIdentity ?? true))
            DrawEllipse(brush, pen, ellipse.Center, ellipse.RadiusX, ellipse.RadiusY);
        else
        {
            using var path = Geometry(geometry);
            if (brush is not null) target!.FillGeometry(path, Brush(brush));
            if (pen is not null) target!.DrawGeometry(path, Brush(pen.Brush), (float)pen.Thickness);
        }
    }
    internal override void DrawImage(BitmapSource image, Rect rect)
    {
        var bitmap = (images ??= new(target!)).Acquire(image);
        target!.DrawBitmap(bitmap, Rectangle(rect), 1, BitmapInterpolationMode.Linear, new RectF(0, 0, image.PixelWidth, image.PixelHeight));
    }
    internal override void PushTransform(Wpf.Transform transform)
    {
        states.Push((target!.Transform, 0, null, false));
        target.Transform = Matrix(transform.Value) * target.Transform;
    }
    internal override void PushScale(double scale)
    {
        states.Push((target!.Transform, 0, null, false));
        target.Transform = Matrix3x2.CreateScale((float)scale) * target.Transform;
    }
    internal override void PushTranslation(double x, double y)
    {
        states.Push((target!.Transform, 0, null, false));
        target.Transform = Matrix3x2.CreateTranslation((float)x, (float)y) * target.Transform;
    }
    internal override void PushClip(Rect clip)
    {
        states.Push((target!.Transform, 1, null, false));
        target.PushAxisAlignedClip(Rectangle(clip), AntialiasMode.PerPrimitive);
    }
    internal override void PushClip(Wpf.Geometry clip)
    {
        if (clip is RectangleGeometry rectangle && rectangle.RadiusX == 0 && rectangle.RadiusY == 0 && (rectangle.Transform?.Value.IsIdentity ?? true))
        {
            states.Push((target!.Transform, 1, null, false));
            target.PushAxisAlignedClip(Rectangle(rectangle.Rect), AntialiasMode.PerPrimitive);
        }
        else
        {
            var owned = clip is not EllipseGeometry || !(clip.Transform?.Value.IsIdentity ?? true);
            var mask = owned ? Geometry(clip) : (clipGeometry ??= new(factory)).Acquire((EllipseGeometry)clip, dpi);
            states.Push((target!.Transform, 2, mask, owned));
            target.PushLayer(new LayerParameters { ContentBounds = new RectF(-1e6f, -1e6f, 2e6f, 2e6f),
                GeometricMask = mask, MaskTransform = Matrix3x2.Identity, MaskAntialiasMode = AntialiasMode.PerPrimitive, Opacity = 1 }, null);
        }
    }
    internal override void Pop()
    {
        var state = states.Pop();
        if (state.Clip == 1) target!.PopAxisAlignedClip();
        if (state.Clip == 2) target!.PopLayer();
        if (state.Owned) state.Mask?.Dispose(); target!.Transform = state.Transform;
    }
    private ID2D1PathGeometry Geometry(Wpf.Geometry geometry)
        => OverlayClipGeometry.Create(factory, geometry, dpi);
    private void Glyphs(GlyphRunDrawing drawing)
    {
        var run = drawing.GlyphRun;
        if (!fonts.TryGetValue(run.GlyphTypeface, out var face))
        {
            using var collection = textFactory.GetSystemFontCollection(false);
            foreach (var family in run.GlyphTypeface.Win32FamilyNames.Values)
            {
                if (!collection.FindFamilyName(family, out var index)) continue;
                using var fontFamily = collection.GetFontFamily(index);
                using var font = fontFamily.GetFirstMatchingFont((Vortice.DirectWrite.FontWeight)run.GlyphTypeface.Weight.ToOpenTypeWeight(),
                    (Vortice.DirectWrite.FontStretch)run.GlyphTypeface.Stretch.ToOpenTypeStretch(),
                    run.GlyphTypeface.Style == FontStyles.Italic ? Vortice.DirectWrite.FontStyle.Italic : run.GlyphTypeface.Style == FontStyles.Oblique ? Vortice.DirectWrite.FontStyle.Oblique : Vortice.DirectWrite.FontStyle.Normal);
                face = font.CreateFontFace(); break;
            }
            fonts[run.GlyphTypeface] = face;
        }
        if (face is null)
        {
            // Private WPF font families can be outside the system collection; preserve their exact outlines.
            using var outline = Geometry(run.BuildGeometry()); target!.FillGeometry(outline, Brush(drawing.ForegroundBrush)); return;
        }
        if (!glyphs.TryGetValue(run, out var native))
        {
            native = new Vortice.DirectWrite.GlyphRun
            {
                FontFace = face, FontEmSize = (float)run.FontRenderingEmSize, Indices = run.GlyphIndices.ToArray(),
                Advances = run.AdvanceWidths.Select(value => (float)value).ToArray(),
                Offsets = run.GlyphOffsets?.Select(value => new GlyphOffset { AdvanceOffset = (float)value.X, AscenderOffset = (float)value.Y }).ToArray(),
                IsSideways = run.IsSideways, BidiLevel = run.BidiLevel
            };
            glyphs.Add(run, native);
        }
        OverlayGlyphDrawing.Draw(target!, Point(run.BaselineOrigin), native, Brush(drawing.ForegroundBrush));
    }
    private void ReleaseTarget()
    {
        clipGeometry?.Dispose(); clipGeometry = null;
        foreach (var brush in brushes.Values) brush.Dispose(); brushes.Clear();
        DiscardImages();
        target?.Dispose(); target = null;
    }
    internal void DiscardImages()
    {
        images?.Dispose(); images = null;
        // Settings/skin edits can introduce arbitrary colors and font families, unlike snapshot updates.
        if (brushes.Count > 512) { foreach (var brush in brushes.Values) brush.Dispose(); brushes.Clear(); }
        if (fonts.Count > 64) { glyphs.Clear(); foreach (var font in fonts.Values) font?.Dispose(); fonts.Clear(); }
    }
    public void Dispose()
    {
        ReleaseTarget(); glyphs.Clear(); foreach (var font in fonts.Values) font?.Dispose(); fonts.Clear();
        if (resources is null) device.Dispose();
    }
}
