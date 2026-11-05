using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    private double? referenceTime;
    private Rect energyArea;
    private double? energyMaximum;
    internal EnergySeries Energy { get; }
    internal IReadOnlyList<ControlSegment> Control { get; }
    internal Rect EnergyArea => energyArea;
    internal int EnergyRows => (Control.Count > 0 ? 1 : 0) + (Energy.Samples.Count > 0 ? 3 : 0);
    internal int ObservationRows => EnergyRows + Enemies.Tracks.Sum(track => track.Samples.Count > 0 ? 3 : 1);
    internal event Action<double?>? ReferenceChanged;
    internal void SetReference(double? stamp) { if (referenceTime == stamp) return; referenceTime = stamp; UpdateReference(); }
    private void UpdateReference()
    {
        var x = referenceTime is { } time ? Labels + time / Duration * Math.Max(1, ActualWidth - Labels - 10) : (double?)null;
        if (x < viewportX + Labels || viewportWidth > 0 && x > viewportX + viewportWidth) x = null;
        reference.Set(x, StickyHeaderTop + Header, ActualHeight);
    }
    private void DrawObservations(DrawingContext dc, double top, double rowHeight, Func<double, double> x)
    {
        energyArea = Rect.Empty; var ink = Ink;
        if (Control.Count > 0)
        {
            if (VisibleY(top, top + rowHeight))
            {
            Text(dc, "主控观测", new(6, top + 7), ink);
            var range = VisibleSamples(Control, static segment => segment.Start, neighbors: true);
            for (var index = range.First; index < range.End; index++)
            {
                var segment = Control[index];
                var left = x(Math.Clamp(segment.Start, 0, Duration)); var right = x(Math.Clamp(segment.End, 0, Duration)); if (right <= left) continue;
                var rect = new Rect(left, top + 4, right - left, rowHeight - 8);
                var ownerIndex = ownerOrder.GetValueOrDefault(segment.Character, -1);
                dc.DrawRectangle(ownerIndex < 0 ? Brushes.LightGray : controlColors[ownerIndex % controlColors.Length], null, rect);
                if (rect.Width > 30) Text(dc, names.GetValueOrDefault(segment.Character, segment.Name), new(rect.X + 4, rect.Y + 3), Brushes.Black, width: rect.Width - 8);
                inputHitAreas.Add((rect, $"主控：{names.GetValueOrDefault(segment.Character, segment.Name)}\n{segment.Start / 1000:N3}–{segment.End / 1000:N3} 秒\n{segment.Evidence}"));
            }
            }
            top += rowHeight;
        }
        if (Energy.Samples.Count == 0) return;
        var height = rowHeight * 3; energyArea = new(Labels, top, Math.Max(1, ActualWidth - Labels - 10), height);
        if (!VisibleY(top, top + height)) return;
        Text(dc, "全队共享技力", new(6, top + 6), ink); Text(dc, Energy.Capacity is null ? "上限未知" : $"上限 {Energy.Capacity:N0}", new(6, top + 28), ink, 11);
        var maximum = energyMaximum ??= Math.Max(1, Energy.Samples.Select(row => EvidenceView.Number(row.Get("value")) ?? 0).Concat(Energy.Segments.SelectMany(row => new[] { row.StartValue, row.EndValue })).Max());
        double Y(double value) => top + height - 12 - value / maximum * Math.Max(1, height - 28);
        var grid = axisGridPen;
        for (var tick = 0; tick <= 2; tick++)
        { var value = maximum * tick / 2; dc.DrawLine(grid, new(Labels, Y(value)), new(ActualWidth - 10, Y(value))); Text(dc, $"{value:N0}", new(Labels - 44, Y(value) - 6), ink, 10); }
        dc.PushClip(new RectangleGeometry(energyArea));
        var estimated = estimatedEnergyPen;
        var segments = VisibleSamples(Energy.Segments, static segment => segment.Start, neighbors: true);
        for (var index = segments.First; index < segments.End; index++)
        { var segment = Energy.Segments[index]; dc.DrawLine(estimated, new(x(segment.Start), Y(segment.StartValue)), new(x(segment.End), Y(segment.EndValue))); }
        var samples = VisibleSamples(Energy.Samples, static sample => EvidenceView.Number(sample.Get("time_ms"))!.Value);
        for (var index = samples.First; index < samples.End; index++)
        {
            var sample = Energy.Samples[index];
            var time = EvidenceView.Number(sample.Get("time_ms"))!.Value; var value = EvidenceView.Number(sample.Get("value"))!.Value;
            dc.DrawEllipse(Brushes.SteelBlue, new(CanvasBackground, .8), new(x(time), Y(value)), 2.6, 2.6);
        }
        dc.Pop();
        Text(dc, "● 实测  ┄ 推算", new(Labels + 6, top + 2), ink, 10);
    }
    internal string ObservationTooltip(Point point)
    {
        if (!energyArea.Contains(point)) return PoiseTooltip(point);
        var stamp = Math.Clamp((point.X - Labels) / Math.Max(1, ActualWidth - Labels - 10), 0, 1) * Duration;
        var result = EnergyObservations.At(Energy, stamp);
        return $"全队共享技力 · {stamp / 1000:N3} 秒\n{(result.Value is { } value ? value.ToString("N3") : "未知")} · {result.Evidence}\n" + string.Join("\n", Energy.Notes);
    }
}
