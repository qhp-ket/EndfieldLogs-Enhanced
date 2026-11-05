using System.Numerics;
using System.IO;
using System.Text.Json;
using System.Windows.Media;
using EndfieldLogs.Desktop.Overlays;
using Vortice.Direct2D1;
using Vortice.DirectWrite;
using Vortice.Mathematics;
using Vortice.WIC;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Exact D2D glyph submission comparison on a WIC target, independent of desktop capture availability.</summary>
internal static class OverlayGlyphProbe
{
    internal static int Run(string output)
    {
        Dictionary<string, object?> checks = [];
        try
        {
            Verify((name, valid) => { checks[name] = valid; if (!valid) throw new InvalidOperationException(name); });
            checks["passed"] = true;
        }
        catch (Exception error) { checks["error"] = error.ToString(); }
        checks["boundary"] = "D2D software/WIC pixels; does not replace actual HWND/GPU/WGC checks";
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(checks, new JsonSerializerOptions { WriteIndented = true }));
        return checks.GetValueOrDefault("passed") is true ? 0 : 1;
    }
    private static unsafe void Verify(Action<string, bool> check)
    {
        using OverlayGraphicsDevice device = new();
        using IWICImagingFactory wic = new();
        using var bitmap = wic.CreateBitmap(480, 160, Vortice.WIC.PixelFormat.Format32bppPBGRA, BitmapCreateCacheOption.CacheOnLoad);
        foreach (var dpi in new[] { 96f, 168f, 240f })
        {
            using var target = device.Shapes.CreateWicBitmapRenderTarget(bitmap, new RenderTargetProperties(
                RenderTargetType.Software,
                new(Vortice.DXGI.Format.B8G8R8A8_UNorm, Vortice.DCommon.AlphaMode.Premultiplied), dpi, dpi,
                RenderTargetUsage.None, Vortice.Direct2D1.FeatureLevel.Default));
            target.TextAntialiasMode = Vortice.Direct2D1.TextAntialiasMode.Grayscale;
            using var ink = target.CreateSolidColorBrush(new Color4(.2f, .8f, .4f, .7f));
            foreach (var family in new[] { "Consolas", "Microsoft YaHei UI" })
            {
                var face = new Typeface(family);
                if (!face.TryGetGlyphTypeface(out var wpf)) throw new InvalidOperationException(family);
                using var collection = device.Text.GetSystemFontCollection(false);
                if (!collection.FindFamilyName(family, out var familyIndex)) throw new InvalidOperationException(family);
                using var fontFamily = collection.GetFontFamily(familyIndex);
                using var font = fontFamily.GetFirstMatchingFont(Vortice.DirectWrite.FontWeight.Normal,
                    Vortice.DirectWrite.FontStretch.Normal, Vortice.DirectWrite.FontStyle.Normal);
                using var fontFace = font.CreateFontFace();
                foreach (var variant in Enumerable.Range(0, 4))
                {
                    var value = family == "Consolas" ? "12,345 rDMG Agj" : "终末地技能 Agj 123";
                    if (variant == 3) value = string.Concat(Enumerable.Repeat(value, 8));
                    var indices = value.Select(character => wpf.CharacterToGlyphMap[character]).ToArray();
                    Vortice.DirectWrite.GlyphRun run = new()
                    {
                        FontFace = fontFace, FontEmSize = 24, Indices = indices,
                        Advances = indices.Select(index => (float)(wpf.AdvanceWidths[index] * 24)).ToArray(),
                        Offsets = variant == 0 ? null : indices.Select((_, index) => new GlyphOffset
                            { AdvanceOffset = index % 2 * .25f, AscenderOffset = index % 3 * .125f }).ToArray(),
                        BidiLevel = variant == 2 ? 1 : 0, IsSideways = variant == 1
                    };
                    byte[] Draw(bool borrowed)
                    {
                        target.BeginDraw(); target.Transform = Matrix3x2.Identity; target.Clear(new Color4(0, 0, 0, 0));
                        target.Transform = Matrix3x2.CreateScale(variant == 0 ? 1 : .875f) * Matrix3x2.CreateTranslation(.25f, .5f);
                        var origin = new Vector2(variant == 2 ? 180 : 12, 40);
                        if (borrowed) OverlayGlyphDrawing.Draw(target, origin, run, ink);
                        else target.DrawGlyphRun(origin, run, ink, Vortice.DCommon.MeasuringMode.Natural);
                        target.EndDraw().CheckError();
                        byte[] pixels = new byte[480 * 160 * 4];
                        fixed (byte* pointer = pixels) bitmap.CopyPixels(new RectI(0, 0, 480, 160), 480 * 4, (uint)pixels.Length, (nint)pointer);
                        return pixels;
                    }
                    var expected = Draw(false); var actual = Draw(true);
                    check($"borrowed_glyph_pixels_{family}_{variant}_{dpi}", expected.AsSpan().SequenceEqual(actual)
                        && actual.Where((_, index) => index % 4 == 3).Count(alpha => alpha > 0) > 50);
                }
            }
        }
    }
}
