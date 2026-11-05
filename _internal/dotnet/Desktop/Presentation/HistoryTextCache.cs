using System.Globalization;
using System.Windows;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>One bounded, window-owned cache of completed glyph drawings. Replaying
/// a DrawingGroup avoids formatting the same immutable history text on every visit.</summary>
internal sealed class HistoryTextCache
{
    private const int Capacity = 1024;
    private readonly record struct Key(string Text, string Family, FontStyle Style, FontWeight Weight,
        FontStretch Stretch, double Size, FlowDirection Direction, TextFormattingMode Formatting,
        string Culture, double Dpi, double Width, bool Number, Color Color, double Opacity, Brush? Other);
    internal sealed record Layout(DrawingGroup Drawing, Size Size, TextTrimming Trimming);
    private readonly Dictionary<Key, LinkedListNode<(Key Key, Layout Layout)>> entries = [];
    private readonly LinkedList<(Key Key, Layout Layout)> recent = [];
    internal int Count => entries.Count;
    internal long Hits { get; private set; }
    internal long Creations { get; private set; }

    internal Layout Get(string value, HistoryCell cell, double width)
    {
        var ink = cell.Foreground ?? Brushes.Black;
        var solid = ink as SolidColorBrush;
        var culture = CultureInfo.GetCultureInfo(cell.Language.IetfLanguageTag);
        var key = new Key(value, cell.FontFamily.Source, cell.FontStyle, cell.FontWeight, cell.FontStretch,
            cell.FontSize, cell.FlowDirection, TextOptions.GetTextFormattingMode(cell), culture.Name,
            VisualTreeHelper.GetDpi(cell).PixelsPerDip, width, cell.Column.Number,
            solid?.Color ?? default, ink.Opacity, solid is null ? ink : null);
        var canCache = solid is not null || ink.IsFrozen;
        if (canCache && entries.TryGetValue(key, out var cached))
        {
            recent.Remove(cached); recent.AddLast(cached); Hits++; return cached.Value.Layout;
        }
        var brush = ink.CloneCurrentValue(); if (brush.CanFreeze) brush.Freeze();
        FormattedText text = new(value, culture, cell.FlowDirection,
            new Typeface(cell.FontFamily, cell.FontStyle, cell.FontWeight, cell.FontStretch), cell.FontSize,
            brush, null, key.Formatting, key.Dpi);
        text.MaxLineCount = 1 + value.Count(character => character == '\n');
        text.Trimming = TextTrimming.CharacterEllipsis;
        text.TextAlignment = key.Number ? TextAlignment.Right : TextAlignment.Left;
        if (!double.IsPositiveInfinity(width)) text.MaxTextWidth = Math.Max(.01, width);
        var size = new Size(Math.Min(width, text.WidthIncludingTrailingWhitespace), text.Height);
        DrawingGroup drawing = new();
        using (var context = drawing.Open()) context.DrawText(text, new());
        if (drawing.CanFreeze) drawing.Freeze();
        Layout layout = new(drawing, size, text.Trimming); Creations++;
        if (canCache)
        {
            var node = recent.AddLast((key, layout)); entries.Add(key, node);
            if (entries.Count > Capacity) { entries.Remove(recent.First!.Value.Key); recent.RemoveFirst(); }
        }
        return layout;
    }
}
