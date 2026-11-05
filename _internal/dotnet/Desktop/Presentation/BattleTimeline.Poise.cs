using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    internal EnemyObservationResult Enemies { get; }
    private readonly List<(Rect Area, EnemyObservationTrack Track)> poiseAreas = [];
    internal IReadOnlyList<(Rect Area, EnemyObservationTrack Track)> PoiseAreas => poiseAreas;
    private void DrawPoise(DrawingContext dc, double top, double rowHeight, Func<double, double> x)
    {
        poiseAreas.Clear();
        foreach (var track in Enemies.Tracks)
        {
            var height = rowHeight * (track.Samples.Count > 0 ? 3 : 1); var area = new Rect(Labels, top, Math.Max(1, ActualWidth - Labels - 10), height);
            poiseAreas.Add((area, track));
            if (!VisibleY(top, top + height)) { top += height; continue; }
            Text(dc, track.Name, new(6, top + 6), Ink, width: Labels - 55);
            if (track.Samples.Count == 0) Text(dc, "失衡值未知：没有可配对的 POISE_V1 采样", new(Labels + 6, top + 5), Ink, 11);
            else
            {
                var peak = Math.Max(1, track.Peak ?? 0); double Y(double value) => top + height - 12 - Math.Clamp(value / peak, 0, 1) * Math.Max(1, height - 36);
                Text(dc, $"失衡观测值 · 峰值 {track.Peak:N2}（非上限） · {track.Samples.Count} 个采样", new(Labels + 6, top + 2), Ink, 11);
                for (var tick = 0; tick <= 2; tick++)
                {
                    var value = peak * tick / 2; dc.DrawLine(axisGridPen, new(Labels, Y(value)), new(ActualWidth - 10, Y(value)));
                    Text(dc, value.ToString("G3"), new(Labels - 45, Y(value) - 6), Ink, 10);
                }
                dc.PushClip(new RectangleGeometry(area)); var pen = poisePen;
                var range = VisibleSamples(track.Samples, static point => point.Time, neighbors: true);
                for (var index = Math.Max(1, range.First + 1); index < range.End; index++)
                {
                    var previous = track.Samples[index - 1]; var point = track.Samples[index];
                    dc.DrawLine(pen, new(x(previous.Time), Y(previous.Value)), new(x(point.Time), Y(previous.Value)));
                    dc.DrawLine(pen, new(x(point.Time), Y(previous.Value)), new(x(point.Time), Y(point.Value)));
                }
                for (var index = range.First; index < range.End; index++)
                { var point = track.Samples[index]; dc.DrawEllipse(point.Value <= 0 ? Brushes.IndianRed : Brushes.DarkGoldenrod, null, new(x(point.Time), Y(point.Value)), 2.5, 2.5); }
                dc.Pop();
            }
            dc.DrawLine(poiseDividerPen, new(0, top + height), new(ActualWidth, top + height)); top += height;
        }
    }
    private string PoiseTooltip(Point point)
    {
        var axis = poiseAreas.FirstOrDefault(axis => axis.Area.Contains(point)); if (axis.Track is null) return "";
        var stamp = Math.Clamp((point.X - Labels) / Math.Max(1, ActualWidth - Labels - 10), 0, 1) * Duration;
        var sample = axis.Track.Samples.LastOrDefault(sample => sample.Time <= stamp);
        var prefix = $"{stamp / 1000:N3} 秒 · {axis.Track.Name}";
        if (sample is null) return prefix + " · 失衡值未知（此前没有观测）";
        var evidence = Math.Abs(sample.Time - stamp) < .001 ? "实测" : $"最近观测 {sample.Time / 1000:N3} 秒；不推算期间变化";
        return $"{prefix}\n失衡观测值 {sample.Value:N3} · {evidence}" + (sample.Ambiguous ? "\n同刻多目标命中，目标未绑定" : "");
    }
}
