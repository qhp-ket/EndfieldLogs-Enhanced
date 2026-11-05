using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Native.Windows;

namespace EndfieldLogs.Desktop.Overlays;

internal sealed record OverlayHit(Rect Area, string Text);
internal sealed record OverlayLayout(Size Size, IReadOnlyList<OverlayHit> Hits, object? Data = null)
{
    public string Tooltip(Point point) => string.Join("\n", Hits.Where(hit => hit.Area.Contains(point)).Select(hit => hit.Text).Where(text => text.Length > 0).Distinct());
}

internal interface IOverlayModule
{
    string Type { get; }
    void Configure(EvidenceObject settings, EvidenceObject theme);
    bool Receive(EvidenceObject message);
    bool Connected { get; set; }
    OverlayLayout Measure(double pixelsPerDip, double? width = null);
    void Draw(OverlayDrawContext context, Rect area, OverlayLayout layout, double pixelsPerDip, AvatarCache avatars, double pixelScale);
}

internal sealed class AvatarCache(string applicationRoot)
{
    private readonly string directory = Path.Combine(applicationRoot, "_internal", "data", "ui", "characters");
    private EvidenceObject? manifest;
    private readonly Dictionary<string, BitmapSource?> images = new(StringComparer.Ordinal);
    internal BitmapSource? Get(string key)
    {
        if (!key.StartsWith("chr_", StringComparison.Ordinal)) return null;
        if (images.TryGetValue(key, out var image)) return image;
        try
        {
            manifest ??= File.Exists(Path.Combine(directory, "manifest.json")) ? EvidenceJson.Parse(File.ReadAllText(Path.Combine(directory, "manifest.json"))) as EvidenceObject : EvidenceView.Empty();
            var alias = (manifest?.Get("aliases") as EvidenceObject)?.Get(key) as EvidenceText;
            var row = (manifest?.Get("portraits") as EvidenceObject)?.Get(alias?.Value ?? key) as EvidenceObject;
            var relative = EvidenceView.Text(row?.Get("path"));
            var path = relative.Length > 0 ? Path.GetFullPath(relative, directory) : Path.Combine(directory, "placeholder.png");
            if (!string.Equals(Path.GetDirectoryName(path), directory, StringComparison.OrdinalIgnoreCase) || !path.EndsWith(".png", StringComparison.OrdinalIgnoreCase)) path = Path.Combine(directory, "placeholder.png");
            image = Load(path) ?? Load(Path.Combine(directory, "placeholder.png"));
        }
        catch (Exception error) when (error is IOException or FormatException or NotSupportedException or ArgumentException) { image = null; }
        if (images.Count >= 160) images.Clear();
        return images[key] = image;
    }
    internal static BitmapSource? Load(string path)
    {
        if (!File.Exists(path)) return null;
        if (path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase))
        {
            var frame = WebPImage.Decode(File.ReadAllBytes(path));
            var decoded = BitmapSource.Create(frame.Width, frame.Height, 96, 96, PixelFormats.Pbgra32, null, frame.PremultipliedBgra, checked(frame.Width * 4));
            decoded.Freeze(); return decoded;
        }
        using var stream = File.OpenRead(path);
        var bitmap = new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad;
        bitmap.StreamSource = stream; bitmap.EndInit(); bitmap.Freeze(); return bitmap;
    }
}

internal sealed class OverlayPalette(EvidenceObject settings, EvidenceObject theme)
{
    internal double PixelScale { get; set; } = 1;
    internal string Mode => EvidenceView.Text(settings.Get("theme"), "light");
    internal bool Industrial => Mode == "endfield";
    internal double FontScale => Math.Clamp(OverlayDrawing.Number(settings.Get("_font_scale")) ?? 1, .5, 3);
    internal string FontFamily => EvidenceView.Text(theme.Get("font_family"), "Microsoft YaHei UI");
    internal Brush this[string key]
    {
        get
        {
            var dark = Mode is "dark" or "transparent";
            var color = key switch
            {
                "background" => Mode == "transparent" ? "transparent" : Industrial ? "#f0f0ec" : dark ? "#20252d" : "#f3f6fa",
                "foreground" => Industrial ? "#1a1c1c" : dark ? "#f0f3f7" : "#28313c",
                "muted" => Industrial ? "#6a685b" : dark ? "#a9b3c2" : "#667587",
                "accent" => Industrial ? "#c4193c" : "#168c9e",
                "ready" => dark ? "#6ede99" : "#23884c",
                _ => Industrial ? "#1a1c1c" : dark ? "#485261" : "#c7d0dc",
            };
            return OverlayDrawing.Brush(EvidenceView.Text(theme.Get(key), color));
        }
    }
}

internal static class OverlayDrawing
{
    private static readonly Dictionary<string, Brush> brushes = new(StringComparer.Ordinal);
    private static readonly Dictionary<(Brush Color, double Opacity), Brush> translucent = [];
    private static readonly Dictionary<(Brush Color, double Width), Pen> pens = [];
    private static readonly Dictionary<(string Family, bool Bold), Typeface> faces = [];
    private readonly record struct MeasureKey(string Family, double Size, bool Bold, double Dpi, string Text, string Culture);
    private static readonly Dictionary<MeasureKey, Size> measurements = [];
    // Hand the natural line from measurement to painting once; a painted cache entry owns it thereafter.
    // The small pending set also covers headers/column labels which are measured before their first frame.
    private static readonly Dictionary<MeasureKey, (FormattedText Text, Brush Brush)> pendingText = [];
    private readonly record struct TextKey(string Family, double Size, bool Bold, double Dpi, string Value, Brush Brush, double Width, TextAlignment Alignment, string Culture);
    private sealed record PaintedText(FormattedText Text, DrawingGroup Drawing, Rect InkBounds, double AlignmentOffset);
    private static readonly Dictionary<TextKey, LinkedListNode<(TextKey Key, PaintedText Painted)>> paintedText = [];
    private static readonly LinkedList<(TextKey Key, PaintedText Painted)> textUse = [];
    internal static double? Number(EvidenceValue? value) => EvidenceView.Number(value) is { } number && double.IsFinite(number) ? number : null;
    internal static double Parameter(EvidenceObject value, string key, double fallback) => Number(value.Get(key)) ?? fallback;
    internal static Brush Brush(string value)
    {
        if (brushes.TryGetValue(value, out var brush)) return brush;
        brush = new SolidColorBrush(value == "transparent" ? Colors.Transparent : (Color)ColorConverter.ConvertFromString(value)); brush.Freeze();
        if (brushes.Count >= 256) brushes.Clear(); return brushes[value] = brush;
    }
    internal static Brush Alpha(Brush color, double opacity)
    {
        var key = (color, opacity);
        if (color.IsFrozen && translucent.TryGetValue(key, out var cached)) return cached;
        var result = color.Clone(); result.Opacity = opacity; result.Freeze();
        if (translucent.Count >= 256) translucent.Clear();
        if (color.IsFrozen) translucent[key] = result;
        return result;
    }
    internal static Pen Pen(Brush color, double width)
    {
        var key = (color, width);
        if (color.IsFrozen && pens.TryGetValue(key, out var cached)) return cached;
        var result = new Pen(color.IsFrozen ? color : color.Clone(), width); result.Freeze();
        if (pens.Count >= 256) pens.Clear();
        if (color.IsFrozen) pens[key] = result;
        return result;
    }
    internal static string Format(EvidenceValue? value, int digits = 0, bool compact = false)
    {
        var number = Number(value);
        return number is null ? "—" : compact && Math.Abs(number.Value) >= 1_000_000 ? (number / 1_000_000)?.ToString("N2", CultureInfo.CurrentCulture) + "M"
            : number.Value.ToString("N" + digits, CultureInfo.CurrentCulture);
    }
    internal static string Clock(EvidenceValue? value)
    {
        if (Number(value) is not { } number) return "—";
        var seconds = (long)Math.Max(0, number / 1000); return $"{seconds / 3600:00}:{seconds / 60 % 60:00}:{seconds % 60:00}";
    }
    internal static FormattedText Text(string value, OverlayPalette palette, double dpi, double size = 13, bool bold = false, Brush? brush = null, bool mono = false)
    {
        var key = (mono ? "Consolas" : palette.FontFamily, bold);
        if (!faces.TryGetValue(key, out var face))
        {
            face = new(new FontFamily(key.Item1), FontStyles.Normal, bold ? FontWeights.Bold : FontWeights.Normal, FontStretches.Normal);
            if (faces.Count >= 64) faces.Clear(); faces[key] = face;
        }
        return new(value, CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, face, Math.Max(8, size * palette.FontScale), brush ?? palette["foreground"], dpi);
    }
    internal static Size Measure(string value, OverlayPalette palette, double dpi, double size = 13, bool bold = false, bool mono = false)
    {
        var key = new MeasureKey(mono ? "Consolas" : palette.FontFamily, Math.Max(8, size * palette.FontScale), bold, dpi, value, CultureInfo.CurrentUICulture.Name);
        if (measurements.TryGetValue(key, out var measured)) return measured;
        var text = Text(value, palette, dpi, size, bold, mono: mono); measured = new(text.WidthIncludingTrailingWhitespace, text.Height);
        if (pendingText.Count >= 64) pendingText.Clear();
        pendingText[key] = (text, palette["foreground"]);
        if (measurements.Count >= 2048) measurements.Clear(); measurements[key] = measured; return measured;
    }
    internal static void Write(OverlayDrawContext context, string value, Rect rect, OverlayPalette palette, double dpi,
        double size = 13, Brush? brush = null, bool bold = false, TextAlignment align = TextAlignment.Left, bool mono = false)
    {
        if (rect.Width < 1 || rect.Height < 1) return;
        var key = new TextKey(mono ? "Consolas" : palette.FontFamily, Math.Max(8, size * palette.FontScale), bold, dpi, value,
            brush ?? palette["foreground"], Math.Max(1, rect.Width), align, CultureInfo.CurrentUICulture.Name);
        PaintedText painted;
        if (paintedText.TryGetValue(key, out var cached))
        {
            textUse.Remove(cached); textUse.AddFirst(cached); painted = cached.Value.Painted;
        }
        else
        {
            var measureKey = new MeasureKey(key.Family, key.Size, key.Bold, key.Dpi, value, key.Culture);
            var measured = pendingText.Remove(measureKey, out var pending);
            var text = measured ? pending.Text : Text(value, palette, dpi, size, bold, key.Brush, mono);
            if (measured && !ReferenceEquals(key.Brush, pending.Brush)) text.SetForegroundBrush(key.Brush);
            var naturalWidth = text.WidthIncludingTrailingWhitespace;
            var offset = 0d;
            if (naturalWidth <= key.Width && align != TextAlignment.Center && SimpleLine(value))
            {
                // A fitting single line already has the exact glyphs and metrics from Measure.
                // Align its origin instead of changing MaxTextWidth and shaping the line again.
                offset = align == TextAlignment.Right ? key.Width - naturalWidth : 0;
            }
            else
            {
                text.MaxTextWidth = key.Width; text.MaxLineCount = 1; text.Trimming = TextTrimming.CharacterEllipsis; text.TextAlignment = align;
            }
            DrawingGroup drawing = new(); using (var recorder = drawing.Open()) recorder.DrawText(text, new Point());
            drawing.Freeze();
            painted = new(text, drawing, drawing.Bounds, offset);
            if (paintedText.Count >= 256)
            {
                var oldest = textUse.Last!; paintedText.Remove(oldest.Value.Key); textUse.RemoveLast();
            }
            paintedText[key] = textUse.AddFirst((key, painted));
        }
        var origin = new Point(rect.X + painted.AlignmentOffset, rect.Y + Math.Max(0, (rect.Height - painted.Text.Height) / 2));
        var ink = painted.InkBounds;
        if (!ink.IsEmpty) { ink.Offset(origin.X, origin.Y); var margin = 1 / Math.Max(.0001, palette.PixelScale); ink.Inflate(margin, margin); }
        // A centered glyph run can round differently without its clip under fractional transforms.
        var clip = align == TextAlignment.Center || !SimpleLine(value) || ink.IsEmpty || !rect.Contains(ink);
        if (clip) context.PushClip(rect);
        context.DrawText(painted.Text, painted.Drawing, origin);
        if (clip) context.Pop();
    }
    private static bool SimpleLine(string value)
    {
        // Keep WPF's bounded-line handling for bidi, tabs, whitespace alignment and center rounding.
        if (value.Length == 0 || value[0] == ' ' || value[^1] == ' ') return false;
        foreach (var character in value) if (character is < ' ' or > '~') return false;
        return true;
    }
    internal static void Portrait(OverlayDrawContext context, AvatarCache avatars, string key, Rect area, bool circle, Brush fallback, string label, OverlayPalette palette, double dpi)
    {
        var image = avatars.Get(key);
        if (image is not null)
        {
            if (circle) context.PushClip(new EllipseGeometry(area)); else context.PushClip(area);
            var scale = Math.Min(area.Width / image.Width, area.Height / image.Height); var width = image.Width * scale; var height = image.Height * scale;
            context.DrawImage(image, new(area.X + (area.Width - width) / 2, area.Y + (area.Height - height) / 2, width, height)); context.Pop();
        }
        else Write(context, label, area, palette, dpi, brush: fallback, align: TextAlignment.Center);
    }
    internal static void Industrial(OverlayDrawContext context, Rect rect, double header, double footer = 0)
    {
        context.DrawRectangle(Brush("#101111"), null, new(rect.X, rect.Y, rect.Width, header));
        context.PushClip(new Rect(rect.Right - Math.Min(100, rect.Width), rect.Y + header, Math.Min(100, rect.Width), Math.Max(0, rect.Height - header - footer)));
        for (var offset = -100; offset < 210; offset += 10) context.DrawLine(Pen(Brush("#0c1a1c1c"), .8), new(rect.Right - 100 + offset, rect.Bottom - footer), new(rect.Right + offset, rect.Bottom - footer - 100));
        context.Pop();
        if (footer > 0)
        {
            var band = new Rect(rect.X, rect.Bottom - footer, rect.Width, footer); context.DrawRectangle(Brush("#feef00"), null, band);
            context.PushClip(band);
            for (var x = rect.X - footer; x < rect.Right + footer; x += 8) context.DrawLine(Pen(Brush("#d4c700"), 4), new(x, rect.Bottom), new(x + footer, rect.Bottom - footer));
            context.Pop(); context.DrawRectangle(Brush("#101111"), null, new(rect.X, rect.Bottom - footer, rect.Width, 2));
        }
        context.DrawRectangle(null, Pen(Brush("#101111"), 2), new(rect.X + 1, rect.Y + 1, Math.Max(0, rect.Width - 2), Math.Max(0, rect.Height - 2)));
    }
}
