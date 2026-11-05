using System.IO;
using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Native.Windows;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    private static void VerifyImages(string directory, Action<string, bool> check)
    {
        // Synthetic 2x2 RGBA sources encoded losslessly by Google's cwebp/img2webp 1.6.0.
        const string still = "UklGRjgAAABXRUJQVlA4TCwAAAAvAUAAEB8gEEHaZ4D9xdYQCBBazMskFkxmlT9Xj0CA4Ny5GDM063CBhoj+Rw==";
        const string animation = "UklGRpwAAABXRUJQVlA4WAoAAAASAAAAAQAAAQAAQU5JTQYAAAD/////AABBTk1GQAAAAAAAAAAAAAEAAAEAAGQAAAJWUDhMKAAAAC8BQAAQHyAQIHj1v2BDIJDkbzbVIyMgKLpuuQCzUwPZAGWqMIvof3xBTk1GKAAAAAAAAAAAAAEAAAEAAGQAAABWUDhMDwAAAC8BQAAABxDR//4HIqL/AQA=";
        byte[] expected = [0, 0, 255, 255, 25, 50, 100, 128, 0, 0, 0, 0, 0, 255, 0, 255];
        var decoded = WebPImage.Decode(Convert.FromBase64String(still));
        check("webp_native_exact_pixels_alpha_and_channels", decoded.Width == 2 && decoded.Height == 2 && decoded.PremultipliedBgra.SequenceEqual(expected));
        var first = WebPImage.Decode(Convert.FromBase64String(animation));
        check("webp_animation_uses_composed_first_frame", first.Width == 2 && first.Height == 2 && first.PremultipliedBgra.SequenceEqual(expected));
        var path = Path.Combine(directory, "synthetic.webp"); File.WriteAllBytes(path, Convert.FromBase64String(still));
        var bitmap = AvatarCache.Load(path); byte[] pixels = new byte[16]; bitmap?.CopyPixels(Int32Rect.Empty, pixels, 8, 0);
        check("webp_skin_bitmap_frozen_and_releases_file", bitmap is { IsFrozen: true, Format: var format } && format == PixelFormats.Pbgra32 && pixels.SequenceEqual(expected));
        File.Delete(path);
        var rejected = 0;
        foreach (var bytes in new[] { Array.Empty<byte>(), "not webp"u8.ToArray(), Convert.FromBase64String(still)[..20] })
            try { WebPImage.Decode(bytes); } catch (InvalidDataException) { rejected++; }
        check("webp_rejects_invalid_and_truncated_images", rejected == 3);
    }
}
