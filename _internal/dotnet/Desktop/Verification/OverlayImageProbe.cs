using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Desktop.Overlays;
using Vortice.Direct2D1;
using Vortice.Mathematics;
using Vortice.WIC;
using D2D = Vortice.Direct2D1;

namespace EndfieldLogs.Desktop.Verification;

internal static class OverlayImageProbe
{
    internal static unsafe Dictionary<string, bool> Verify(OverlayGraphicsDevice device, IWICBitmap surface)
    {
        Dictionary<string, bool> checks = [];
        void Check(string name, bool passed) { checks[name] = passed; if (!passed) throw new InvalidOperationException(name); }
        ID2D1RenderTarget Target() => device.Shapes.CreateWicBitmapRenderTarget(surface, new RenderTargetProperties(RenderTargetType.Software,
            new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), 96, 96, RenderTargetUsage.None, D2D.FeatureLevel.Default));
        using var target = Target(); using OverlayImageCache cache = new(target);
        var sources = Enumerable.Range(0, 170).Select(index => Image(1, (byte)(index + 1))).ToArray();
        var first = cache.Acquire(sources[0]);
        Check("same_source_reuses_native_bitmap", ReferenceEquals(first, cache.Acquire(sources[0])));
        target.BeginDraw(); target.Clear(new Color4(0, 0, 0, 0));
        for (var index = 0; index < sources.Length; index++)
            target.DrawBitmap(cache.Acquire(sources[index]), new Vortice.Mathematics.Rect(index % 40 * 5, index / 40 * 5, 4, 4), 1, D2D.BitmapInterpolationMode.Linear, new Vortice.Mathematics.Rect(0, 0, 1, 1));
        var replacement = cache.Acquire(sources[0]);
        Check("bounded_images_and_evicted_source_reloads", cache.Count == 160 && cache.Bytes == 640 && !ReferenceEquals(first, replacement));
        Check("evicted_bitmap_alive_until_end_draw", first.NativePointer != 0);
        target.EndDraw().CheckError(); cache.EndFrame();
        Check("evicted_bitmap_released_after_end_draw", first.NativePointer == 0 && replacement.NativePointer != 0);
        var pixels = Pixels(surface);
        Check("all_images_render_across_eviction", sources.Select((_, index) => pixels[((index / 40 * 5 + 2) * 240 + index % 40 * 5 + 2) * 4] == (byte)(index + 1)).All(value => value));
        cache.Dispose();
        Check("clear_releases_images_and_retained_sources", cache.Count == 0 && cache.Bytes == 0 && replacement.NativePointer == 0);
        var retained = cache.Acquire(Image(1024, 30));
        for (var index = 0; index < 5; index++) cache.Acquire(Image(1024, (byte)(40 + index)));
        Check("decoded_byte_budget", cache.Count == 4 && cache.Bytes == 16 * 1024 * 1024 && retained.NativePointer != 0);
        cache.EndFrame(); Check("byte_budget_eviction_releases", retained.NativePointer == 0);
        var oversized = cache.Acquire(Image(2049, 90));
        Check("oversized_image_not_retained", cache.Count == 4 && cache.Bytes == 16 * 1024 * 1024 && oversized.NativePointer != 0);
        cache.EndFrame(); Check("oversized_image_released_after_frame", oversized.NativePointer == 0);

        DrawingGroup drawing = new();
        foreach (var index in Enumerable.Range(0, 170).Append(0))
            drawing.Children.Add(new ImageDrawing(sources[index], new System.Windows.Rect(index % 40 * 5, index / 40 * 5, 4, 4)));
        drawing.Freeze();
        using var renderer = new OverlayGraphics(Target(), device, 1);
        renderer.Render(drawing, 240, 240, 1);
        Check("product_pixels_match_eviction_frame", Pixels(surface).AsSpan().SequenceEqual(pixels));
        renderer.DiscardImages(); renderer.Render(drawing, 240, 240, 1);
        Check("configuration_clear_reload_preserves_pixels", Pixels(surface).AsSpan().SequenceEqual(pixels));
        renderer.Dispose();
        using var recreated = new OverlayGraphics(Target(), device, 1);
        recreated.Render(drawing, 240, 240, 1);
        Check("target_recreation_preserves_pixels", Pixels(surface).AsSpan().SequenceEqual(pixels));
        return checks;
    }
    private static BitmapSource Image(int size, byte blue)
    {
        byte[] pixels = new byte[checked(size * size * 4)];
        for (var index = 0; index < pixels.Length; index += 4) { pixels[index] = blue; pixels[index + 1] = 100; pixels[index + 3] = 255; }
        var image = BitmapSource.Create(size, size, 96, 96, PixelFormats.Pbgra32, null, pixels, size * 4); image.Freeze(); return image;
    }
    private static unsafe byte[] Pixels(IWICBitmap bitmap)
    {
        byte[] pixels = new byte[240 * 240 * 4];
        fixed (byte* pointer = pixels) bitmap.CopyPixels(new RectI(0, 0, 240, 240), 240 * 4, (uint)pixels.Length, (nint)pointer);
        return pixels;
    }
}
