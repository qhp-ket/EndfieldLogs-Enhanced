using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Vision;

public sealed record HudSlotRegions(HudRegion Energy, HudRegion Hp, HudRegion Portrait)
{
    public EvidenceObject ToEvidence() => TraceData.Make(("energy", Energy.Values), ("hp", Hp.Values), ("portrait", Portrait.Values));
}
public sealed record VisionConfiguration(string Layout, IReadOnlyList<HudSlotRegions> Regions, BigInteger TargetWindow)
{
    public static VisionConfiguration Normalize(EvidenceValue? source = null)
    {
        var value = TraceData.Obj(source); var mode = value.Get("layout") is EvidenceText text ? text.Value : "auto";
        if (mode is not ("auto" or "keyboard" or "gamepad" or "gamepad_expanded" or "custom")) mode = "auto";
        List<HudSlotRegions> clean = [];
        if (value.Get("regions") is EvidenceArray { Items.Count: 4 } rows)
            foreach (var row in rows.Items)
            {
                HudRegion? Rect(string key)
                {
                    if (TraceData.Obj(row).Get(key) is not EvidenceArray { Items.Count: 4 } raw) return null;
                    if (raw.Items.Any(v => v is not (EvidenceInteger or EvidenceReal))) return null;
                    var numbers = raw.Items.Select(v => SettingsData.Number(v, double.NaN)).ToArray(); var (x, y, w, h) = (numbers[0], numbers[1], numbers[2], numbers[3]);
                    return numbers.All(double.IsFinite) && x >= 0 && x < 1 && y >= 0 && y < 1 && w > 0 && h > 0 && x + w <= 1 && y + h <= 1 ? new(x, y, w, h) : null;
                }
                if (Rect("energy") is { } energy && Rect("hp") is { } hp && Rect("portrait") is { } portrait) clean.Add(new(energy, hp, portrait));
            }
        return new(mode, clean.Count == 4 ? clean : [], BigInteger.Max(0, SettingsData.Integer(value.Get("target_hwnd"), allowBoolean: true) ?? 0));
    }
    public EvidenceObject ToEvidence() => TraceData.Make(("layout", Layout), ("regions", new EvidenceArray(Regions.Select(row => row.ToEvidence()).ToArray())), ("target_hwnd", TargetWindow));
}
public sealed record VisionLayoutCandidate(string Name, string Identity, IReadOnlyList<HudSlotRegions> Regions);
public static class VisionLayout
{
    public static IReadOnlyList<VisionLayoutCandidate> Presets()
    {
        List<VisionLayoutCandidate> result = [];
        foreach (var name in new[] { "keyboard", "gamepad", "gamepad_expanded" })
        {
            (double X, double Y, double W, double H)[] positions = name == "keyboard"
                ? [(45, 1053, 89, 4), (169, 1053, 90, 4), (294, 1053, 89, 4), (419, 1053, 89, 4)]
                : [(117, 1017, 88, 2), (203, 923, 89, 2), (289, 1017, 89, 2), (203, 1103, 89, 2)];
            List<HudSlotRegions> rows = [];
            for (var index = 0; index < positions.Length; index++)
            {
                var (x, y, w, h) = positions[index];
                if (name == "gamepad_expanded") { var delta = index switch { 0 => (-8.5, 0.0), 1 => (0.0, -8.5), 2 => (8.5, 0.0), _ => (0.0, 8.5) }; x += delta.Item1; y += delta.Item2; }
                static HudRegion Normalize(double x, double y, double w, double h) => new(x / 2048, y / 1152, w / 2048, h / 1152);
                rows.Add(new(Normalize(x, y, w, h), Normalize(x, y + (name == "keyboard" ? 4 : 5), w, 7), Normalize(x + w / 2 - 13, y - 56, 26, 26)));
            }
            result.Add(new(name, name, rows));
        }
        return result;
    }
    public static IReadOnlyList<VisionLayoutCandidate> Fitted(PixelArea area)
    {
        var width = area.Width; var height = area.Height;
        if (width <= 0 || height <= 0) throw new ArgumentException("游戏图像区域为空");
        List<VisionLayoutCandidate> result = []; HashSet<double> seen = [];
        foreach (var scale in new[] { Math.Min(width / 2048.0, height / 1152.0), height / 1152.0, width / 2048.0 })
        {
            if (!seen.Add(PythonDecimalRounding.Round(scale, 6))) continue;
            foreach (var preset in Presets())
            {
                HudRegion Fit(HudRegion rect) => new(rect.X * 2048 * scale / width, 1 + (rect.Y * 1152 - 1152) * scale / height,
                    rect.Width * 2048 * scale / width, rect.Height * 1152 * scale / height);
                result.Add(new(preset.Name, preset.Name + ":" + PythonDecimalRounding.Round(scale, 6).ToString("F6", CultureInfo.InvariantCulture),
                    preset.Regions.Select(row => new HudSlotRegions(Fit(row.Energy), Fit(row.Hp), Fit(row.Portrait))).ToArray()));
            }
        }
        if (Math.Abs(width / (double)height - 2048.0 / 1152) > .01)
            result.AddRange(Presets().Select(preset => preset with { Identity = preset.Name + ":stretch" }));
        return result;
    }
    public static PixelArea GameArea(VisionPixels pixels, PixelArea client)
    {
        if (client.Width <= 0 || client.Height <= 0) return client;
        var dy = Math.Max(1, client.Height / 180); var dx = Math.Max(1, client.Width / 320);
        var rows = (client.Height + dy - 1) / dy; var cols = (client.Width + dx - 1) / dx;
        var visibleRows = new bool[rows]; var visibleCols = new bool[cols];
        for (var y = 0; y < rows; y++)
            for (var x = 0; x < cols; x++)
                for (var channel = 0; channel < 3; channel++)
                    if (pixels.At(client.X + x * dx, client.Y + y * dy, channel) > 14) { visibleRows[y] = visibleCols[x] = true; break; }
        var firstRow = Array.FindIndex(visibleRows, x => x); var firstCol = Array.FindIndex(visibleCols, x => x);
        if (firstRow < 0 || firstCol < 0) return client;
        var top = firstRow / (double)rows; var bottom = (rows - 1 - Array.FindLastIndex(visibleRows, x => x)) / (double)rows;
        var left = firstCol / (double)cols; var right = (cols - 1 - Array.FindLastIndex(visibleCols, x => x)) / (double)cols;
        var area = client;
        if (top is > .015 and < .22 && Math.Abs(top - bottom) < .015)
        { var trim = (int)Math.Round(Math.Min(top, bottom) * area.Height); area = area with { Y = area.Y + trim, Height = area.Height - 2 * trim }; }
        if (left is > .015 and < .3 && Math.Abs(left - right) < .015)
        { var trim = (int)Math.Round(Math.Min(left, right) * area.Width); area = area with { X = area.X + trim, Width = area.Width - 2 * trim }; }
        return area;
    }
}
