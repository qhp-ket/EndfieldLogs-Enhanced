using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    private AvatarCache? avatars;
    private bool showAvatars;
    private double avatarScale = 1, fontScale = 1;
    private BattlePalette palette = new(false);
    private Brush CanvasBackground => palette.Background;
    private Brush Ink => palette.Ink;
    private readonly Dictionary<(string Value, double Size, double Width, Brush Brush, double Dpi), FormattedText> textCache = [];
    private double RowHeight => Math.Max(Row * rowScale, 16 * fontScale + 12);
    internal int AvatarCount { get; private set; }
    internal double FontScale => fontScale;
    internal void ApplyPresentation(AvatarCache cache, int fontPercent, bool portraits, int portraitPercent, bool dark)
    {
        avatars = cache; fontScale = Math.Clamp(fontPercent / 100d, .8, 1.8); showAvatars = portraits; avatarScale = Math.Clamp(portraitPercent / 100d, .5, 3); palette = new(dark);
        hoverTip.FontSize = 14 * fontScale;
        hoverTip.FontFamily = typeface.FontFamily; hoverTip.Background = CanvasBackground; hoverTip.Foreground = Ink;
        textCache.Clear(); InvalidateMeasure(); InvalidateVisual();
    }
    private double PortraitSize(double height) => showAvatars ? Math.Min(Math.Min(24 * avatarScale * rowScale, height - 8), CharacterWidth * .4) : 0;
    private void DrawPortraits(DrawingContext dc, IReadOnlyList<Track> tracks, double rowHeight)
    {
        AvatarCount = 0; var row = 0;
        foreach (var group in tracks.GroupBy(track => track.Owner))
        {
            var count = group.Sum(track => track.Rows); var height = count * rowHeight; var size = PortraitSize(height);
            if (size > 0 && avatars?.Get(group.Key) is { } image)
            {
                var area = new Rect(viewportX + 5, Header + row * rowHeight + (height - size) / 2, size, size);
                dc.PushClip(new EllipseGeometry(area));
                var ratio = Math.Max(size / image.PixelWidth, size / image.PixelHeight); var width = image.PixelWidth * ratio; var imageHeight = image.PixelHeight * ratio;
                dc.DrawImage(image, new(area.X + (size - width) / 2, area.Y + (size - imageHeight) / 2, width, imageHeight)); dc.Pop(); AvatarCount++;
            }
            row += count;
        }
    }
}
