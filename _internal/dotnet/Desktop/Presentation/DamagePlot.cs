using System.Globalization;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class DamagePlot : FrameworkElement
{
    private readonly string[] colors = ["#4286AD", "#65A177", "#B58C4E", "#AA6E9C", "#7D85B5", "#B46B62"];
    private DamageSeriesResult series = new("rdmg", [], 0, 0, 0);
    private IReadOnlyDictionary<string, string> names = new Dictionary<string, string>();
    private string[] owners = [];
    private double maximum = 1;
    private (Size Size, double Labels, StreamGeometry[] Lines)? curves;
    private readonly TimeReferenceVisual reference = new();
    private readonly DrawingVisual axis = new();
    internal int ContentRenderCount { get; private set; }
    internal int AxisRenderCount { get; private set; }
    protected override int VisualChildrenCount => 2;
    protected override Visual GetVisualChild(int index) => index switch { 0 => axis, 1 => reference, _ => throw new ArgumentOutOfRangeException(nameof(index)) };
    internal DamageSeriesResult Series => series;
    private double? referenceTime;
    private double Labels = 260, viewportX, fontScale = 1;
    private BattlePalette palette = new(false);
    internal void ApplyAppearance(double scale, bool dark) { fontScale = scale; palette = new(dark); InvalidateVisual(); }
    internal void SetViewport(double offset)
    {
        if (viewportX == offset) return;
        viewportX = offset; axis.Offset = new(offset, 0); UpdateReference();
    }
    internal void SetLabelWidth(double width) { Labels = width; InvalidateVisual(); }
    internal event Action<double?>? ReferenceChanged;
    internal void SetReference(double? stamp) { if (referenceTime == stamp) return; referenceTime = stamp; UpdateReference(); }
    private void UpdateReference()
    {
        var x = series.Points.Count > 0 && series.DurationMs > 0 && referenceTime is { } time
            ? Labels + time / series.DurationMs * Math.Max(1, ActualWidth - Labels - 10) : (double?)null;
        reference.Set(x < viewportX + Labels ? null : x, 24, ActualHeight);
    }
    public DamagePlot() { AddVisualChild(axis); AddVisualChild(reference); ClipToBounds = true; MinHeight = 130; MouseMove += Hover; MouseLeave += (_, _) => { SetReference(null); ReferenceChanged?.Invoke(null); }; SizeChanged += (_, _) => InvalidateVisual(); }
    internal void SetSeries(DamageSeriesResult value, IReadOnlyDictionary<string, string> labels)
    {
        series = value; names = labels; curves = null;
        maximum = Math.Max(1, series.Points.SelectMany(point => point.Values.Values).DefaultIfEmpty(0).Max());
        owners = series.Points.SelectMany(point => point.Values.Keys).Distinct(StringComparer.Ordinal).ToArray();
        InvalidateVisual();
    }
    private StreamGeometry[] Curves(double width, double height)
    {
        if (curves is { } cached && cached.Size == RenderSize && cached.Labels == Labels) return cached.Lines;
        var lines = owners.Select(owner =>
        {
            StreamGeometry geometry = new();
            using (var context = geometry.Open())
            {
                bool started = false;
                foreach (var point in series.Points)
                {
                    var at = new Point(Labels + point.TimeMs / series.DurationMs * width, 24 + height * (1 - point.Values.GetValueOrDefault(owner) / maximum));
                    if (!started) { context.BeginFigure(at, false, false); started = true; } else context.LineTo(at, true, false);
                }
            }
            geometry.Freeze(); return geometry;
        }).ToArray();
        curves = (RenderSize, Labels, lines); return lines;
    }
    protected override void OnRender(DrawingContext dc)
    {
        ContentRenderCount++; UpdateReference();
        DrawAxis();
        dc.DrawRectangle(palette.Background, null, new Rect(RenderSize));
        void Text(string value, double x, double y, Brush? brush = null) => dc.DrawText(new FormattedText(value, CultureInfo.CurrentCulture,
            FlowDirection.LeftToRight, new Typeface("Microsoft YaHei UI"), 11 * fontScale, brush ?? palette.Ink, VisualTreeHelper.GetDpi(this).PixelsPerDip), new Point(x, y));
        if (series.Points.Count == 0) { Text("伤害曲线：缺少有效贡献或时间证据", 10, 8); return; }
        var width = Math.Max(1, ActualWidth - Labels - 10); var height = Math.Max(1, ActualHeight - 40);
        for (var index = 0; index <= 4; index++)
        {
            var y = 24 + height * index / 4; dc.DrawLine(new Pen(new SolidColorBrush(Color.FromArgb(30, 128, 128, 128)), .7), new Point(Labels, y), new Point(Labels + width, y));
        }
        var geometry = Curves(width, height); var legendX = Labels + 6;
        for (var index = 0; index < owners.Length; index++)
        {
            var owner = owners[index]; Brush color = new SolidColorBrush((Color)ColorConverter.ConvertFromString(colors[index % colors.Length]));
            dc.DrawGeometry(null, new Pen(color, 1.8), geometry[index]);
            var label = names.GetValueOrDefault(owner, owner); Text(label, legendX, 3, color); legendX += Math.Max(70, label.Length * 12 + 18);
        }
        if (series.Missing > 0) Text($"{series.Missing}/{series.Hits} 击缺少分配证据", Math.Max(70, ActualWidth - 220), ActualHeight - 14);
    }
    private void DrawAxis()
    {
        AxisRenderCount++; axis.Offset = new(viewportX, 0);
        using var dc = axis.RenderOpen();
        // Empty curves keep their original full-width explanation, without a covering axis.
        if (series.Points.Count == 0) return;
        dc.DrawRectangle(palette.Background, null, new(0, 0, Labels, ActualHeight));
        var height = Math.Max(1, ActualHeight - 40);
        var typeface = new Typeface("Microsoft YaHei UI"); var dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip;
        for (var index = 0; index <= 4; index++)
            dc.DrawText(new FormattedText((maximum * (4 - index) / 4).ToString("N0", CultureInfo.CurrentCulture), CultureInfo.CurrentCulture,
                FlowDirection.LeftToRight, typeface, 11 * fontScale, palette.Ink, dpi), new(2, 24 + height * index / 4 - 5));
    }
    private void Hover(object sender, MouseEventArgs args)
    {
        if (series.Points.Count == 0) return;
        if (args.GetPosition(this).X < viewportX + Labels) { ToolTip = series.Metric; return; }
        var stamp = Math.Clamp((args.GetPosition(this).X - Labels) / Math.Max(1, ActualWidth - Labels - 10), 0, 1) * series.DurationMs;
        SetReference(stamp); ReferenceChanged?.Invoke(stamp);
        var point = Nearest(stamp);
        var text = $"{point.TimeMs / 1000:N3} 秒\n" + string.Join("\n", point.Values.Select(pair => names.GetValueOrDefault(pair.Key, pair.Key) + "：" + pair.Value.ToString("N4", CultureInfo.CurrentCulture)));
        if (!Equals(ToolTip, text)) ToolTip = text;
    }
    internal DamageSeriesPoint Nearest(double stamp)
    {
        var first = 0; var end = series.Points.Count;
        while (first < end)
        {
            var middle = first + (end - first) / 2;
            if (series.Points[middle].TimeMs < stamp) first = middle + 1; else end = middle;
        }
        if (first == 0) return series.Points[0];
        if (first == series.Points.Count) return series.Points[^1];
        return stamp - series.Points[first - 1].TimeMs <= series.Points[first].TimeMs - stamp ? series.Points[first - 1] : series.Points[first];
    }
}
