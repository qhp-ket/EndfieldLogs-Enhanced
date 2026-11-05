using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Vision;

public readonly record struct PixelArea(int X, int Y, int Width, int Height);
public readonly record struct HudRegion(double X, double Y, double Width, double Height)
{
    public double[] Values => [X, Y, Width, Height];
}

/// <summary>Read-only RGB/BGR view. Alpha and row padding are excluded without copying a full capture frame.</summary>
public sealed class VisionPixels
{
    public ReadOnlyMemory<byte> Data { get; }
    public int Width { get; }
    public int Height { get; }
    public int Stride { get; }
    public int Channels { get; }
    private readonly int offset;
    public VisionPixels(ReadOnlyMemory<byte> data, int width, int height, int stride, int channels = 4)
        : this(data, width, height, stride, channels, 0)
    {
        if (width < 0 || height < 0 || channels is not (3 or 4) || stride < checked(width * channels)
            || data.Length < (height == 0 ? 0 : checked((height - 1) * stride + width * channels))) throw new ArgumentException("捕获像素缓冲区尺寸无效");
    }
    private VisionPixels(ReadOnlyMemory<byte> data, int width, int height, int stride, int channels, int offset)
    { Data = data; Width = width; Height = height; Stride = stride; Channels = channels; this.offset = offset; }
    public byte At(int x, int y, int channel) => Data.Span[offset + y * Stride + x * Channels + channel];
    public VisionPixels Crop(PixelArea area, HudRegion region)
    {
        var left = checked((int)Math.Round(area.X + region.X * area.Width)); var top = checked((int)Math.Round(area.Y + region.Y * area.Height));
        var right = checked((int)Math.Round(area.X + (region.X + region.Width) * area.Width)); var bottom = checked((int)Math.Round(area.Y + (region.Y + region.Height) * area.Height));
        // Match NumPy's positive-step slice normalization, including candidates outside the viewport.
        static int Slice(int value, int size) => value < 0 ? Math.Max(0, size + value) : Math.Min(size, value);
        var x = Slice(Math.Max(0, left), Width); var y = Slice(Math.Max(0, top), Height);
        var endX = Slice(Math.Min(Width, Math.Max(left + 1, right)), Width); var endY = Slice(Math.Min(Height, Math.Max(top + 1, bottom)), Height);
        return new(Data, Math.Max(0, endX - x), Math.Max(0, endY - y), Stride, Channels, offset + y * Stride + x * Channels);
    }
}

public sealed record VisionObservation(bool Readable = false, double? Progress = null, bool Ready = false, bool Consumed = false,
    bool Dead = false, bool Empty = false, double Confidence = 0, bool Partial = false, string Reason = "")
{
    public EvidenceObject ToEvidence() => TraceData.Make(("readable", Readable), ("progress", Progress), ("ready", Ready), ("consumed", Consumed),
        ("dead", Dead), ("empty", Empty), ("confidence", Confidence), ("partial", Partial), ("reason", Reason));
}

public static class VisionPixelObserver
{
    public static VisionObservation Observe(VisionPixels energy, VisionPixels hp, VisionPixels portrait)
    {
        if (energy.Width < 12 || energy.Height == 0 || hp.Width == 0 || hp.Height == 0 || portrait.Width == 0 || portrait.Height == 0) return new();
        var width = energy.Width; var height = energy.Height; var size = (double)width * height;
        bool[] columns = new bool[width]; double[] levels = new double[width]; var brightCount = 0; var railCount = 0; var neutralCount = 0; double maximumSum = 0;
        for (var x = 0; x < width; x++)
        {
            var brightColumn = 0; double level = 0;
            for (var y = 0; y < height; y++)
            {
                var a = energy.At(x, y, 0); var b = energy.At(x, y, 1); var c = energy.At(x, y, 2);
                var max = Math.Max(a, Math.Max(b, c)); var min = Math.Min(a, Math.Min(b, c)); var sum = a + b + c;
                var bright = min > 145 || max > 205 && min > 80 || sum / 3.0 > 165 && max > 220;
                if (bright) { brightColumn++; brightCount++; } if (max > 30 && max < 170) railCount++;
                if (max - min < 80 || min > 145) neutralCount++; maximumSum += max; level += sum;
            }
            columns[x] = brightColumn / (double)height > .45; levels[x] = level / (height * 3);
        }
        for (var x = 1; x < width - 1; x++) if (columns[x - 1] && columns[x + 1]) columns[x] = true;
        var edge = Math.Max(1, (int)Math.Ceiling(width * .03)); var first = Array.FindIndex(columns, value => value); var start = first >= 0 && first <= edge ? first : 0;
        var leading = start; foreach (var value in columns.AsSpan(start)) { if (!value) break; leading++; }
        var progress = leading >= width - edge ? 1.0 : leading / (double)width;
        var hpColumns = 0; var hpRowCounts = new int[hp.Height];
        for (var x = 0; x < hp.Width; x++)
        {
            var any = false;
            for (var y = 0; y < hp.Height; y++)
            {
                var a = hp.At(x, y, 0); var b = hp.At(x, y, 1); var c = hp.At(x, y, 2);
                var max = Math.Max(a, Math.Max(b, c)); var min = Math.Min(a, Math.Min(b, c));
                if (max - min > 45 && max > 95 && min < 155) { any = true; hpRowCounts[y]++; }
            }
            if (any) hpColumns++;
        }
        var hpFraction = hpColumns / (double)hp.Width; var rail = railCount / size; var neutral = neutralCount / size; var horizontalCount = 0;
        for (var x = 0; x < width; x++)
            for (var channel = 0; channel < 3; channel++)
            {
                double sum = 0; for (var y = 0; y < height; y++) sum += energy.At(x, y, channel); var mean = sum / height;
                double squared = 0; for (var y = 0; y < height; y++) { var delta = energy.At(x, y, channel) - mean; squared += delta * delta; }
                if (Math.Sqrt(squared / height) < 38) horizontalCount++;
            }
        var horizontal = horizontalCount / (width * 3.0);
        var hpEvidence = hpFraction > .012 && hpRowCounts.Max() / (double)hp.Width > .01 && horizontal > .7 && (neutral > .7 || brightCount / size > .1);
        int whiteDiagonal = 0, diagonalCount = 0, whiteOther = 0, otherCount = 0, portraitMax = 0;
        for (var y = 0; y < portrait.Height; y++)
            for (var x = 0; x < portrait.Width; x++)
            {
                var a = portrait.At(x, y, 0); var b = portrait.At(x, y, 1); var c = portrait.At(x, y, 2);
                var max = Math.Max(a, Math.Max(b, c)); var min = Math.Min(a, Math.Min(b, c)); portraitMax = Math.Max(portraitMax, max);
                var white = min > 170 && max - min < 60; var nx = x / (double)Math.Max(1, portrait.Width - 1); var ny = y / (double)Math.Max(1, portrait.Height - 1);
                if (Math.Abs(nx - ny) < .075 || Math.Abs(nx + ny - 1) < .075) { diagonalCount++; if (white) whiteDiagonal++; }
                else { otherCount++; if (white) whiteOther++; }
            }
        var deathShape = whiteDiagonal / (double)diagonalCount > .55 && whiteOther / (double)otherCount < .28;
        var readable = hpEvidence || deathShape && rail > .65; var dead = readable && hpFraction < .015 && deathShape;
        var empty = rail > .85 && hpFraction == 0 && portraitMax < 22;
        var confidence = readable ? Math.Min(1, hpFraction * 2 + .35 * (rail > .5 ? 1 : 0)) : 0;
        double Mean(int from, int to) { if (to <= from) return double.NaN; double sum = 0; for (var x = from; x < to; x++) sum += levels[x]; return sum / (to - from); }
        var darkSuffix = leading < width ? columns.AsSpan(leading).Count(false) / (double)(width - leading) : double.NaN;
        var partial = readable && edge + 2 < leading && leading < width - edge && Mean(start, leading) - Mean(leading + 1, width) > 45 && darkSuffix > .8;
        var ready = readable && progress >= .965 && columns.Count(value => value) >= width - 2 * edge;
        var consumed = readable && progress < .08 && columns.Count(value => value) / (double)width < .08 && rail > .65 && maximumSum / size < 100;
        var recognized = readable && (ready || consumed || partial || dead);
        return new(recognized, recognized ? progress : null, ready, consumed, dead, empty, recognized ? confidence : 0, partial,
            recognized && hpEvidence ? "hp_strip" : recognized ? "death_mark" : readable ? "ambiguous_energy" : "missing_hp_or_rail");
    }
}
