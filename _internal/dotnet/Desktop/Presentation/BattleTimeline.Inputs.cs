using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleTimeline
{
    private sealed record InputRange(TimelineInputSpan Span, double Start, double End);
    private sealed record InputPoint(EvidenceObject Evidence, double Time, string Device, string Code);
    private TimelineInputLayout? indexedInput;
    private TimelineIntervalIndex<InputRange>? inputRangeIndex;
    private TimelineIntervalIndex<InputPoint>? inputPointIndex;
    private readonly List<InputRange> visibleInputRanges = [];
    private readonly List<InputPoint> visibleInputPoints = [];
    private readonly Dictionary<(string Device, string Code, double X), InputPoint> inputPixels = [];
    private static readonly (Brush Fill, Pen Line, Pen Dashed)[] inputStyles = new[]
    {
        Color.FromRgb(50, 135, 239), Color.FromRgb(237, 155, 50), Color.FromRgb(173, 101, 227),
        Color.FromRgb(105, 156, 165), Color.FromRgb(132, 146, 164)
    }.Select(color => ((Brush)Frozen(new SolidColorBrush(Color.FromArgb(36, color.R, color.G, color.B))),
        Frozen(new Pen(new SolidColorBrush(color), 1.5)),
        Frozen(new Pen(new SolidColorBrush(color), 1.5) { DashStyle = DashStyles.Dash }))).ToArray();

    private void IndexInput(TimelineInputLayout layout)
    {
        if (ReferenceEquals(indexedInput, layout)) return;
        var ranges = new List<InputRange>();
        foreach (var span in layout.Spans)
        {
            var start = EvidenceView.Number(span.Evidence.Get("start_ms")); var end = EvidenceView.Number(span.Evidence.Get("end_ms"));
            if (start is null || end is null || end < 0 || start > Duration || end < start) continue;
            ranges.Add(new(span, Math.Max(0, start.Value), Math.Min(Duration, end.Value)));
        }
        var points = new List<InputPoint>();
        foreach (var row in layout.Raw)
        {
            var stamp = EvidenceView.Number(row.Get("time_ms"));
            if (stamp is null || stamp < 0 || stamp > Duration) continue;
            points.Add(new(row, stamp.Value, EvidenceView.Text(row.Get("device")), EvidenceView.Text(row.Get("code"))));
        }
        // The existing interval index preserves source order, including unsorted and duplicate
        // input events. Coincident pixel reduction must still retain the last source event.
        inputRangeIndex = new(ranges, range => (range.Start, range.End));
        inputPointIndex = new(points, point => (point.Time, point.Time));
        indexedInput = layout;
    }
    private void DrawInputs(DrawingContext dc, TimelineInputLayout layout, int laneCount, double rowHeight, Func<double, double> x)
    {
        IndexInput(layout);
        var factor = Duration / Math.Max(1, ActualWidth - Labels - 10);
        // Include minimum-width blocks, stroke/hover bounds, and rounded sample centers.
        var start = viewportWidth > 0 ? (viewportX - 5) * factor : double.NegativeInfinity;
        var end = viewportWidth > 0 ? (viewportX + viewportWidth - Labels + 5) * factor : double.PositiveInfinity;
        inputRangeIndex!.Query(start, end, visibleInputRanges);
        foreach (var range in visibleInputRanges)
        {
            var span = range.Span;
            var top = Header + (span.FirstRow + (span.FirstRow >= laneCount ? ObservationRows : 0)) * rowHeight;
            var bottom = top + span.RowCount * rowHeight;
            if (!VisibleY(top, bottom)) continue;
            var left = x(range.Start); var right = x(range.End);
            var rectangle = new Rect(left, top, Math.Max(1, right - left), bottom - top);
            var action = EvidenceView.Text(span.Evidence.Get("action")); var interrupted = span.Evidence.Get("interrupted") is EvidenceBoolean { Value: true };
            var style = inputStyles[action switch { "skill" => 0, "ultimate" => 1, "combo" => 2, "switch" => 3, _ => 4 }];
            var pen = action == "combo" || interrupted ? style.Dashed : style.Line;
            dc.DrawRectangle(style.Fill, null, rectangle);
            dc.DrawLine(pen, rectangle.TopLeft, rectangle.BottomLeft); if (interrupted) dc.DrawLine(pen, rectangle.TopRight, rectangle.BottomRight);
            var tooltip = EvidenceView.Text(span.Evidence.Get("tooltip"), "输入意图");
            inputHitAreas.Add((new(rectangle.X - 2, rectangle.Y, Math.Max(5, rectangle.Width + 4), rectangle.Height), tooltip)); inputSpans.Add((rectangle, span));
        }
        inputPixels.Clear(); visibleInputPoints.Clear();
        var rawTop = Header + (laneCount + ObservationRows) * rowHeight;
        if (!VisibleY(rawTop, rawTop + rowHeight)) return;
        inputPointIndex!.Query(start, end, visibleInputPoints);
        foreach (var point in visibleInputPoints)
            inputPixels[(point.Device, point.Code, Math.Round(x(point.Time), MidpointRounding.ToEven))] = point;
        foreach (var ((device, code, at), point) in inputPixels)
        {
            var row = point.Evidence;
            var value = EvidenceView.Number(row.Get("value")); var ratio = value is { } number ? Math.Clamp(number, -32768, 32767) / 32768 : 0;
            var y = rawTop + rowHeight / 2 - ratio * rowHeight * .35;
            dc.DrawEllipse(Brushes.SlateGray, null, new Point(at, y), 1.2, 1.2);
            inputHitAreas.Add((new Rect(at - 3, y - 3, 6, 6), $"{EvidenceView.Format(row.Get("time_ms"), "N3")} ms · {device} · {code}\n{EvidenceView.Exact(row.Get("value"))}"));
        }
    }
}
