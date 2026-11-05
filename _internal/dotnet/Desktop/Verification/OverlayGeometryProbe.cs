using System.Diagnostics;
using System.IO;
using System.Numerics;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Desktop.Overlays;
using Vortice.Direct2D1;
using Vortice.Mathematics;
using Vortice.WIC;
using D2D = Vortice.Direct2D1;

namespace EndfieldLogs.Desktop.Verification;

internal static class OverlayGeometryProbe
{
    internal static unsafe int Run(string output)
    {
        Dictionary<string, object?> result = [];
        void Check(string name, bool passed) { result[name] = passed; if (!passed) throw new InvalidOperationException(name); }
        try
        {
            using OverlayGraphicsDevice device = new();
            using IWICImagingFactory wic = new();
            using var bitmap = wic.CreateBitmap(240, 240, Vortice.WIC.PixelFormat.Format32bppPBGRA, BitmapCreateCacheOption.CacheOnLoad);
            using OverlayClipGeometry cache = new(device.Shapes);
            var comparisons = 0;
            foreach (var dpi in new[] { 1d, 1.75, 2.5 })
            {
                using var target = device.Shapes.CreateWicBitmapRenderTarget(bitmap, new RenderTargetProperties(RenderTargetType.Software,
                    new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), (float)(96 * dpi), (float)(96 * dpi),
                    RenderTargetUsage.None, D2D.FeatureLevel.Default));
                using var ink = target.CreateSolidColorBrush(new Color4(.2f, .8f, .4f, .7f));
                foreach (var radius in new[] { 8d, 30, 67.25 })
                foreach (var scale in new[] { .5f, 1f, 1.8f })
                foreach (var shift in new[] { 0f, .25f, .6f })
                {
                    EllipseGeometry clip = new(new System.Windows.Point(37.5, 39.25), radius, radius * .8);
                    byte[] Draw(ID2D1PathGeometry mask)
                    {
                        target.BeginDraw(); target.Transform = Matrix3x2.CreateScale(scale) * Matrix3x2.CreateTranslation(shift, shift);
                        target.Clear(new Color4(0, 0, 0, 0));
                        target.PushLayer(new LayerParameters { ContentBounds = new(-1e6f, -1e6f, 2e6f, 2e6f), GeometricMask = mask,
                            MaskTransform = Matrix3x2.Identity, MaskAntialiasMode = AntialiasMode.PerPrimitive, Opacity = 1 }, null);
                        for (var x = 0; x < 200; x += 6) target.FillRectangle(new Vortice.Mathematics.Rect(x, 0, 4, 200), ink);
                        target.PopLayer(); target.EndDraw().CheckError();
                        byte[] pixels = new byte[240 * 240 * 4];
                        fixed (byte* pointer = pixels) bitmap.CopyPixels(new RectI(0, 0, 240, 240), 240 * 4, (uint)pixels.Length, (nint)pointer);
                        return pixels;
                    }
                    using var original = Original(device.Shapes, clip, dpi);
                    var expected = Draw(original); var actual = Draw(cache.Acquire(clip, dpi));
                    if (!expected.AsSpan().SequenceEqual(actual) || !actual.Any(value => value > 0)) throw new InvalidOperationException("mask pixels changed");
                    comparisons++;
                }
            }
            Check("exact_mask_pixels_dpi_scale_fractional_translation", comparisons == 81);
            result["arc_comparisons"] = VerifyProgressArcs(device, bitmap);
            Check("compact_progress_arcs_preserve_pixels", (int)result["arc_comparisons"]! == 216);
            result["transform_comparisons"] = VerifyTransforms(device, bitmap);
            Check("product_transform_stack_preserves_pixels", (int)result["transform_comparisons"]! == 24);
            result["image_cache"] = OverlayImageProbe.Verify(device, bitmap);
            EllipseGeometry mutable = new(new System.Windows.Point(40, 40), 30, 30);
            var first = cache.Acquire(mutable, 1.75);
            Check("new_geometry_same_values_reuses_mask", ReferenceEquals(first, cache.Acquire(mutable.Clone(), 1.75)));
            mutable.RadiusX = 31;
            Check("changed_geometry_and_dpi_get_distinct_masks", !ReferenceEquals(first, cache.Acquire(mutable, 1.75)) && !ReferenceEquals(first, cache.Acquire(mutable, 2.5)));
            // Keep the first mask alive while a nested sequence evicts its dictionary entry.
            for (var index = 0; index < 150; index++) cache.Acquire(new(new System.Windows.Point(index, 12), 12, 12), 1);
            Check("bounded_cache_with_live_evicted_mask", cache.Count == 64 && first.NativePointer != 0);
            cache.EndFrame(); cache.Dispose();
            Check("release_and_recreate_mask", cache.Count == 0 && cache.Acquire(mutable, 1).NativePointer != 0);
            // Diagnostic only: equal work, resource creation versus warm cache lookup; not a frame benchmark.
            List<object> timings = [];
            for (var round = 0; round < 3; round++)
            {
                var allocated = GC.GetAllocatedBytesForCurrentThread(); var watch = Stopwatch.StartNew();
                for (var index = 0; index < 2000; index++) using (Original(device.Shapes, mutable, 1.75)) { }
                var before = watch.Elapsed.TotalMilliseconds; var beforeBytes = GC.GetAllocatedBytesForCurrentThread() - allocated;
                cache.Acquire(mutable, 1.75); allocated = GC.GetAllocatedBytesForCurrentThread(); watch.Restart();
                for (var index = 0; index < 2000; index++) cache.Acquire(mutable, 1.75);
                timings.Add(new { round, uncached_ms = before, cached_ms = watch.Elapsed.TotalMilliseconds,
                    uncached_bytes = beforeBytes, cached_bytes = GC.GetAllocatedBytesForCurrentThread() - allocated });
            }
            result["comparisons"] = comparisons; result["geometry_lookup_diagnostic"] = timings;
            result["passed"] = true;
        }
        catch (Exception error) { result["error"] = error.ToString(); }
        result["boundary"] = "Exact software D2D/WIC mask pixels against the original flattening algorithm; not actual HWND/GPU/WGC/OBS validation. No forced GC.";
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
        return result.GetValueOrDefault("passed") is true ? 0 : 1;
    }
    private static unsafe int VerifyProgressArcs(OverlayGraphicsDevice device, IWICBitmap bitmap)
    {
        var comparisons = 0;
        foreach (var dpi in new[] { 1d, 1.75, 2.5 })
        {
            using var target = device.Shapes.CreateWicBitmapRenderTarget(bitmap, new RenderTargetProperties(RenderTargetType.Software,
                new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), (float)(96 * dpi), (float)(96 * dpi),
                RenderTargetUsage.None, D2D.FeatureLevel.Default));
            using var ink = target.CreateSolidColorBrush(new Color4(.2f, .8f, .4f, .7f));
            foreach (var radius in new[] { 8d, 30, 47.25 })
            foreach (var shift in new[] { 0d, .25, .6 })
            foreach (var progress in new[] { .0001, .01, .125, .333333333, .5, .500001, .9, .99999 })
            {
                System.Windows.Rect icon = new(3 + shift, 4 + shift, radius * 2, radius * 1.5);
                var angle = progress * 2 * Math.PI; var center = new System.Windows.Point(icon.X + icon.Width / 2, icon.Y + icon.Height / 2);
                // Independent original PathFigure/ArcSegment implementation, retained as the reference.
                PathFigure figure = new() { StartPoint = new(center.X, icon.Y), IsClosed = false };
                figure.Segments.Add(new System.Windows.Media.ArcSegment(new(center.X + icon.Width / 2 * Math.Sin(angle), center.Y - icon.Height / 2 * Math.Cos(angle)),
                    new(icon.Width / 2, icon.Height / 2), 0, progress > .5, System.Windows.Media.SweepDirection.Clockwise, true));
                PathGeometry original = new([figure]); original.Freeze();
                byte[] Draw(Geometry geometry)
                {
                    using var path = Original(device.Shapes, geometry, dpi);
                    target.BeginDraw(); target.Transform = Matrix3x2.CreateScale(.8f); target.Clear(new Color4(0, 0, 0, 0));
                    target.DrawGeometry(path, ink, 4); target.EndDraw().CheckError();
                    return Pixels(bitmap);
                }
                var expected = Draw(original); var actual = Draw(ComboOverlay.ProgressArc(icon, progress));
                if (!expected.AsSpan().SequenceEqual(actual) || (progress > .01 && !actual.Any(value => value > 0)))
                    throw new InvalidOperationException($"progress arc pixels changed: {dpi}, {radius}, {shift}, {progress}");
                comparisons++;
            }
        }
        return comparisons;
    }
    private static int VerifyTransforms(OverlayGraphicsDevice device, IWICBitmap bitmap)
    {
        var comparisons = 0;
        foreach (var dpi in new[] { 1d, 1.75, 2.5 })
        foreach (var opacity in new[] { 1d, .45 })
        foreach (var geometricClip in new[] { false, true })
        foreach (var transformed in new[] { false, true })
        {
            DrawingGroup inner = new() { Opacity = opacity,
                ClipGeometry = geometricClip ? new EllipseGeometry(new System.Windows.Rect(4, 4, 65, 52)) : new RectangleGeometry(new(4, 4, 65, 52)),
                Transform = transformed ? new MatrixTransform(1.1, .1, -.15, .9, .25, .6) : Transform.Identity };
            DrawingGroup plain = new(); using (var dc = plain.Open()) { dc.DrawRectangle(Brushes.Orange, null, new(0, 0, 50, 40)); dc.DrawEllipse(Brushes.Blue, null, new(32, 38), 30, 20); }
            inner.Children.Add(plain);
            DrawingGroup outer = new() { Transform = new TranslateTransform(3.25, 5.6) }; outer.Children.Add(inner);
            // A subsequent sibling reveals leaked state after a nested clip or transformed group.
            outer.Children.Add(new GeometryDrawing(Brushes.Lime, null, new RectangleGeometry(new(60, 60, 10, 8)))); outer.Freeze();
            using var reference = device.Shapes.CreateWicBitmapRenderTarget(bitmap, new RenderTargetProperties(RenderTargetType.Software,
                new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), (float)(96 * dpi), (float)(96 * dpi),
                RenderTargetUsage.None, D2D.FeatureLevel.Default));
            reference.BeginDraw(); reference.Transform = Matrix3x2.Identity; reference.Clear(new Color4(0, 0, 0, 0));
            OriginalDraw(reference, device.Shapes, outer, dpi); reference.EndDraw().CheckError(); var expected = Pixels(bitmap);
            using var product = new OverlayGraphics(device.Shapes.CreateWicBitmapRenderTarget(bitmap, new RenderTargetProperties(RenderTargetType.Software,
                new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), (float)(96 * dpi), (float)(96 * dpi),
                RenderTargetUsage.None, D2D.FeatureLevel.Default)), device, dpi);
            product.Render(outer, 240, 240, dpi); var actual = Pixels(bitmap);
            if (!expected.AsSpan().SequenceEqual(actual) || !actual.Any(value => value > 0))
                throw new InvalidOperationException($"product transform pixels changed: dpi={dpi}, opacity={opacity}, ellipse={geometricClip}, transform={transformed}; channels={expected.Where((value, index) => value != actual[index]).Count()}, nonzero={expected.Count(value => value > 0)}/{actual.Count(value => value > 0)}, sample={string.Join(',', expected.Skip(20 * 240 * 4 + 20 * 4).Take(4))}/{string.Join(',', actual.Skip(20 * 240 * 4 + 20 * 4).Take(4))}");
            // BeginDraw resets both native and managed transform state, including a changed DPI.
            product.Render(outer, 240, 240, dpi); if (!actual.AsSpan().SequenceEqual(Pixels(bitmap))) throw new InvalidOperationException("transform state leaked between frames");
            comparisons++;
        }
        return comparisons;
    }
    private static unsafe byte[] Pixels(IWICBitmap bitmap)
    {
        byte[] pixels = new byte[240 * 240 * 4];
        fixed (byte* pointer = pixels) bitmap.CopyPixels(new RectI(0, 0, 240, 240), 240 * 4, (uint)pixels.Length, (nint)pointer);
        return pixels;
    }
    private static void OriginalDraw(ID2D1RenderTarget target, ID2D1Factory factory, Drawing drawing, double dpi)
    {
        if (drawing is DrawingGroup group)
        {
            var previous = target.Transform; var matrix = group.Transform?.Value ?? Matrix.Identity;
            target.Transform = new Matrix3x2((float)matrix.M11, (float)matrix.M12, (float)matrix.M21, (float)matrix.M22, (float)matrix.OffsetX, (float)matrix.OffsetY) * previous;
            var clip = group.ClipGeometry; var axis = clip is RectangleGeometry rect && rect.RadiusX == 0 && rect.RadiusY == 0 && (rect.Transform?.Value.IsIdentity ?? true);
            ID2D1PathGeometry? mask = null;
            static Vortice.Mathematics.Rect Rect(System.Windows.Rect r) => new((float)r.X, (float)r.Y, (float)r.Width, (float)r.Height);
            if (axis) target.PushAxisAlignedClip(Rect(((RectangleGeometry)clip!).Rect), AntialiasMode.PerPrimitive);
            else if (clip is not null || group.Opacity != 1)
            {
                if (clip is not null) mask = Original(factory, clip, dpi);
                target.PushLayer(new LayerParameters { ContentBounds = new(-1e6f, -1e6f, 2e6f, 2e6f), GeometricMask = mask,
                    MaskTransform = Matrix3x2.Identity, MaskAntialiasMode = AntialiasMode.PerPrimitive, Opacity = (float)group.Opacity }, null);
            }
            if (axis && group.Opacity != 1) target.PushLayer(new LayerParameters { ContentBounds = Rect(((RectangleGeometry)clip!).Rect), MaskTransform = Matrix3x2.Identity, Opacity = (float)group.Opacity }, null);
            foreach (var child in group.Children) OriginalDraw(target, factory, child, dpi);
            if (axis && group.Opacity != 1) target.PopLayer(); if (axis) target.PopAxisAlignedClip(); else if (clip is not null || group.Opacity != 1) target.PopLayer();
            mask?.Dispose(); target.Transform = previous;
        }
        else if (drawing is GeometryDrawing shape)
        {
            var color = ((SolidColorBrush)shape.Brush).Color; using var ink = target.CreateSolidColorBrush(new Color4(color.R / 255f, color.G / 255f, color.B / 255f, color.A / 255f));
            if (shape.Geometry is RectangleGeometry rect) target.FillRectangle(new Vortice.Mathematics.Rect((float)rect.Rect.X, (float)rect.Rect.Y, (float)rect.Rect.Width, (float)rect.Rect.Height), ink);
            else if (shape.Geometry is EllipseGeometry oval) target.FillEllipse(new(new((float)oval.Center.X, (float)oval.Center.Y), (float)oval.RadiusX, (float)oval.RadiusY), ink);
            else throw new InvalidOperationException("unsupported reference primitive");
        }
        else throw new InvalidOperationException("unsupported reference drawing");
    }
    private static ID2D1PathGeometry Original(ID2D1Factory factory, Geometry geometry, double dpi)
    {
        var path = geometry.GetFlattenedPathGeometry(.025 / Math.Max(1, dpi), ToleranceType.Absolute);
        var transform = path.Transform?.Value ?? Matrix.Identity;
        static Vector2 Point(System.Windows.Point point) => new((float)point.X, (float)point.Y);
        var native = factory.CreatePathGeometry(); using var sink = native.Open();
        sink.SetFillMode(path.FillRule == FillRule.EvenOdd ? FillMode.Alternate : FillMode.Winding);
        foreach (var figure in path.Figures)
        {
            sink.BeginFigure(Point(transform.Transform(figure.StartPoint)), figure.IsFilled ? FigureBegin.Filled : FigureBegin.Hollow);
            foreach (var segment in figure.Segments)
            {
                sink.SetSegmentFlags(segment.IsStroked ? D2D.PathSegment.None : D2D.PathSegment.ForceUnstroked);
                if (segment is LineSegment line) sink.AddLine(Point(transform.Transform(line.Point)));
                else if (segment is PolyLineSegment lines) foreach (var point in lines.Points) sink.AddLine(Point(transform.Transform(point)));
                else throw new InvalidOperationException("Unexpected unflattened geometry");
            }
            sink.EndFigure(figure.IsClosed ? FigureEnd.Closed : FigureEnd.Open);
        }
        sink.Close(); return native;
    }
}
