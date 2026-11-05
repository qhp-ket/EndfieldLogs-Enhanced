using System.Windows.Media;
using System.Windows.Media.Imaging;
using Vortice.Direct2D1;
using Vortice.DXGI;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Target-owned images, bounded by source count and decoded pixel bytes.</summary>
internal sealed class OverlayImageCache(ID2D1RenderTarget target) : IDisposable
{
    private const int MaximumImages = 160;
    private const long MaximumBytes = 16 * 1024 * 1024;
    private readonly Dictionary<BitmapSource, (ID2D1Bitmap Bitmap, long Bytes)> images = new(ReferenceEqualityComparer.Instance);
    private readonly Queue<BitmapSource> order = [];
    private readonly List<ID2D1Bitmap> retired = [];
    internal int Count => images.Count;
    internal long Bytes { get; private set; }

    internal unsafe ID2D1Bitmap Acquire(BitmapSource source)
    {
        if (images.TryGetValue(source, out var found)) return found.Bitmap;
        BitmapSource converted = source.Format == PixelFormats.Pbgra32 ? source : new FormatConvertedBitmap(source, PixelFormats.Pbgra32, null, 0);
        var stride = checked(converted.PixelWidth * 4);
        var bytes = checked(stride * converted.PixelHeight);
        byte[] pixels = new byte[bytes]; converted.CopyPixels(pixels, stride, 0);
        ID2D1Bitmap bitmap;
        fixed (byte* pointer = pixels) bitmap = target.CreateBitmap(new(converted.PixelWidth, converted.PixelHeight), (nint)pointer, (uint)stride,
            new BitmapProperties(new(Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), 96, 96));
        // A single large skin image is still drawn, but is not retained after this frame.
        if (bytes > MaximumBytes) { retired.Add(bitmap); return bitmap; }
        while (images.Count >= MaximumImages || Bytes + bytes > MaximumBytes)
        {
            var oldest = order.Dequeue(); var entry = images[oldest];
            images.Remove(oldest); Bytes -= entry.Bytes; retired.Add(entry.Bitmap);
        }
        order.Enqueue(source); images.Add(source, (bitmap, bytes)); Bytes += bytes;
        return bitmap;
    }

    // D2D can still refer to an evicted image until EndDraw completes.
    internal void EndFrame() { foreach (var image in retired) image.Dispose(); retired.Clear(); }
    public void Dispose()
    {
        EndFrame(); foreach (var entry in images.Values) entry.Bitmap.Dispose();
        images.Clear(); order.Clear(); Bytes = 0;
    }
}
