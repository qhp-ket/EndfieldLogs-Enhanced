using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class OverlayProductProbe
{
    private static void VerifyClipRendering(string output, Action<string, bool> check)
    {
        var rows = new List<object>(); var largest = 0;
        foreach (var theme in new[] { "light", "dark", "transparent", "endfield" })
        foreach (var font in new[] { .5, 1.8 })
        foreach (var scale in new[] { .2, .75, 1.0, 1.8 })
        foreach (var dpi in new[] { 1.0, 1.75, 2.5 })
        foreach (var alignment in new[] { TextAlignment.Left, TextAlignment.Right, TextAlignment.Center })
        foreach (var value in new[] { "角色名 Agj", new string('长', 100), "9,999,999.25", "  1  ", "Agj\n第二行", "اَلْعَرَبِيَّةُ" })
        {
            var palette = new OverlayPalette(new(new Dictionary<string, EvidenceValue>
                { ["theme"] = new EvidenceText(theme), ["_font_scale"] = new EvidenceReal(font) }), EvidenceView.Empty()) { PixelScale = dpi * scale };
            Rect cell = new(5.25, 6.5, 160, 36);
            byte[] Render(bool optimized)
            {
                DrawingVisual visual = new();
                using (var context = visual.RenderOpen())
                {
                    context.PushTransform(new ScaleTransform(scale, scale));
                    context.DrawRectangle(palette["background"], null, new(0, 0, 180, 60));
                    context.PushClip(new RectangleGeometry(new(0, 0, 180, 60)));
                    if (optimized)
                    {
                        var measuredPalette = new OverlayPalette(new(new Dictionary<string, EvidenceValue>
                            { ["theme"] = new EvidenceText(theme == "light" ? "dark" : "light"), ["_font_scale"] = new EvidenceReal(font) }), EvidenceView.Empty());
                        OverlayDrawing.Measure(value, measuredPalette, dpi);
                        OverlayDrawing.Write(new WpfOverlayDrawContext(context), value, cell, palette, dpi, align: alignment);
                    }
                    else
                    {
                        var text = OverlayDrawing.Text(value, palette, dpi);
                        text.MaxTextWidth = cell.Width; text.MaxLineCount = 1; text.Trimming = TextTrimming.CharacterEllipsis; text.TextAlignment = alignment;
                        context.PushClip(new RectangleGeometry(cell)); context.DrawText(text, new(cell.X, cell.Y + Math.Max(0, (cell.Height - text.Height) / 2))); context.Pop();
                    }
                    context.Pop(); context.Pop();
                }
                var width = (int)Math.Ceiling(180 * scale * dpi); var height = (int)Math.Ceiling(60 * scale * dpi);
                RenderTargetBitmap bitmap = new(width, height, 96 * dpi, 96 * dpi, PixelFormats.Pbgra32); bitmap.Render(visual);
                byte[] pixels = new byte[checked(width * height * 4)]; bitmap.CopyPixels(pixels, width * 4, 0); return pixels;
            }
            var before = Render(false); var after = Render(true); var max = 0; var changed = 0;
            for (var index = 0; index < before.Length; index++)
            {
                var difference = Math.Abs(before[index] - after[index]); max = Math.Max(max, difference); if (difference > 0) changed++;
            }
            rows.Add(new { theme, font, scale, dpi, alignment = alignment.ToString(), text = value, max_channel_delta = max, changed_channels = changed });
            largest = Math.Max(largest, max);
        }
        File.WriteAllText(Path.ChangeExtension(output, ".clip-pixels.json"), JsonSerializer.Serialize(rows, new JsonSerializerOptions { WriteIndented = true }));
        check("interior_text_clip_pixels_across_themes_sizes_and_dpi", rows.Count == 1728 && largest == 0);
    }
}
