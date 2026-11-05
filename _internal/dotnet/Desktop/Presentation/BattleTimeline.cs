using System.Globalization;
using System.Diagnostics;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Core.Catalog;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed record TimelineMark(string Owner, string Lane, string Name, double Start, double End, IReadOnlyList<EvidenceObject> Evidence, TimelineSkill? Skill = null, BuffEpisode? Buff = null, EvidenceObject? FrameReference = null);

/// <summary>Paints report coordinates directly. Selection never modifies the underlying report.</summary>
internal sealed partial class BattleTimeline : FrameworkElement
{
    private readonly EvidenceObject snapshot;
    private readonly IReadOnlyList<TimelineMark> marks;
    private readonly Dictionary<string, string> names;
    private readonly Dictionary<string, int> ownerOrder;
    private readonly Dictionary<TimelineMark, double[]> damageTimes = new(ReferenceEqualityComparer.Instance);
    private readonly TimeReferenceVisual reference = new();
    // Keep decoration resources at their original painter positions. Changing selection updates
    // only the old/new block, without rebuilding report text, observations or hover indexes.
    private sealed record MarkDecoration(DrawingGroup Drawing, Rect Block, Rect Underline, Brush Fill, bool Buff, bool Fallback);
    private readonly Dictionary<TimelineMark, List<MarkDecoration>> decorations = [];
    internal int ContentRenderCount { get; private set; }
    internal Action<double, long>? RenderMeasured { get; set; }
    protected override int VisualChildrenCount => 1;
    protected override Visual GetVisualChild(int index) => index == 0 ? reference : throw new ArgumentOutOfRangeException(nameof(index));
    private readonly List<(Rect Bounds, TimelineMark Mark)> hitAreas = [];
    private readonly List<(Rect Bounds, string Tooltip)> inputHitAreas = [];
    private readonly List<(Rect Bounds, string Tooltip)> labelHitAreas = [];
    private readonly List<(Rect Bounds, TimelineInputSpan Span)> inputSpans = [];
    private readonly List<(Rect Bounds, string Owner)> settingsAreas = [];
    private readonly List<(Rect Bounds, string Owner, string Lane)> expandAreas = [];
    private readonly HashSet<(string Owner, string Lane)> expanded = [];
    private EvidenceObject laneConfigs = EvidenceView.Empty();
    private sealed record Track(string Owner, string Id, string Name, bool Buff, IReadOnlyList<(TimelineMark Mark, int Row)> Placements, int Rows)
    {
        internal TimelineIntervalIndex<(TimelineMark Mark, int Row)>? Index;
    }
    private readonly List<(TimelineMark Mark, int Row)> visiblePlacements = [];
    private (string Owner, string Lane)[]? laneRows;
    private EvidenceObject input = EvidenceView.Empty();
    private readonly Typeface typeface = new("Microsoft YaHei UI");
    private TimelineMark? selected;
    private string filter = "";
    private bool buffs = true, frames;
    private double zoom = 1, rowScale = 1;
    private double Labels = 180;
    private const double Header = 30, Row = 32;
    private IReadOnlyList<Track>? trackCache;
    private TimelineInputLayout? inputLayout;
    public event Action<IReadOnlyList<EvidenceObject>>? Selected;
    internal event Action<IReadOnlyList<TimelineMark>>? MarksSelected;
    internal event Action<string>? LaneSettingsRequested;
    internal IReadOnlyList<TimelineMark> Marks => marks;
    internal IReadOnlyList<TimelineSkillOption> SkillOptions(string owner) => TimelineSkills.Options(marks.Select(mark => mark.Skill).OfType<TimelineSkill>(), owner);
    internal IReadOnlyList<TimelineSkillLane> RoleLanes(string owner) => TimelineSkills.Resolve(SkillOptions(owner), owner, laneConfigs.Get(owner));
    internal IReadOnlyList<(string Owner, string Lane)> VisibleRows => Lanes();
    internal IReadOnlyList<(Rect Bounds, string Owner)> SettingsAreas => settingsAreas;
    internal IReadOnlyList<(Rect Bounds, TimelineInputSpan Span)> InputSpans => inputSpans;
    internal TimelineInputLayout InputLayout => inputLayout ??= TimelineInputs.Layout(input, Lanes(), filter);
    internal double Duration { get; }
    internal int BuffChangeMarkers { get; private set; }
    internal bool ShowFrameReference { get; private set; }
    internal IReadOnlyList<(Rect Bounds, TimelineMark Mark)> MarkAreas => hitAreas;
    internal (double Start, double End) DisplayBounds(TimelineMark mark) => ShowFrameReference && mark.FrameReference is { } rule && BattleEvidence.Number(rule.Get("anchor_ms")) is { } anchor && BattleEvidence.Number(rule.Get("end_ms")) is { } end ? (anchor, end) : (mark.Start, mark.End);
    internal void SetFrameReference(bool visible)
    { ShowFrameReference = visible; trackCache = null; inputLayout = null; InvalidateMeasure(); InvalidateVisual(); }
    public BattleTimeline(EvidenceObject snapshot, EvidenceObject? energyRules = null, ResourceFiles? resources = null)
    {
        AddVisualChild(reference);
        this.snapshot = snapshot; names = EvidenceView.Rows(snapshot.Get("participants")).ToDictionary(row => EvidenceView.Text(row.Get("character_key")), row => EvidenceView.Text(row.Get("character_name")), StringComparer.Ordinal);
        ownerOrder = names.Keys.Select((owner, index) => (owner, index)).ToDictionary(item => item.owner, item => item.index, StringComparer.Ordinal);
        Duration = Math.Max(1, EvidenceView.Number((snapshot.Get("battle") as EvidenceObject)?.Get("duration_ms")) ?? 1);
        Energy = EnergyObservations.Build(snapshot, energyRules); Control = EnergyObservations.Control(snapshot);
        Enemies = EnemyObservations.Build(snapshot);
        marks = BuildMarks(snapshot, names.Keys.ToHashSet(StringComparer.Ordinal), BuffDisplay.Names(resources), SkillFrameReference.Rules(resources)); ClipToBounds = true; Focusable = true;
        MouseMove += Hover; MouseLeave += (_, _) => { ToolTip = null; SetReference(null); ReferenceChanged?.Invoke(null); };
        MouseLeftButtonDown += (_, args) =>
        {
            var point = args.GetPosition(this);
            if (Math.Abs(point.X - viewportX - Labels) <= 4) { BeginLabelResize(point); args.Handled = true; return; }
            if (point.Y < StickyHeaderTop + Header) return;
            var settings = settingsAreas.FirstOrDefault(area => area.Bounds.Contains(point));
            if (settings.Owner is not null) { LaneSettingsRequested?.Invoke(settings.Owner); return; }
            var expansion = expandAreas.FirstOrDefault(area => area.Bounds.Contains(point));
            if (expansion.Owner is not null) { ToggleLane(expansion.Owner, expansion.Lane); return; }
            if (point.X < viewportX + Labels) return;
            var found = hitAreas.Where(area => area.Bounds.Contains(point)).Select(area => area.Mark).Distinct().ToArray();
            if (found.Length == 0) return; SelectMarks(found);
        };
        MouseLeftButtonUp += (_, args) => { if (resizingLabels) { resizingLabels = false; ReleaseMouseCapture(); args.Handled = true; } };
        LostMouseCapture += (_, _) => resizingLabels = false;
        SizeChanged += (_, _) => InvalidateVisual();
    }
    internal void SelectMarks(IReadOnlyList<TimelineMark> found)
    {
        if (found.Count == 0) return;
        var previous = selected; selected = found[0];
        if (previous != selected)
        {
            UpdateDecorations(previous, false); UpdateDecorations(selected, true);
        }
        Selected?.Invoke(found.SelectMany(mark => mark.Evidence).Distinct().ToArray()); MarksSelected?.Invoke(found);
    }
    private void UpdateDecorations(TimelineMark? mark, bool active)
    {
        if (mark is not null && decorations.TryGetValue(mark, out var entries))
            foreach (var entry in entries) PaintDecoration(entry, active);
    }
    private void PaintDecoration(MarkDecoration entry, bool active)
    {
        using var dc = entry.Drawing.Open();
        var rectangle = entry.Block;
        if (!rectangle.IsEmpty)
        {
            var border = active ? entry.Fallback ? selectedFallbackPen : selectedMarkPen : entry.Fallback ? fallbackMarkPen : normalMarkPen;
            if (entry.Buff) dc.DrawRectangle(entry.Fill, border, rectangle);
            else dc.DrawRoundedRectangle(entry.Fill, border, rectangle, 3, 3);
        }
        if (!entry.Underline.IsEmpty) dc.DrawLine(active ? selectedRangePen : originalRangePen, entry.Underline.TopLeft, entry.Underline.TopRight);
        if (active && !rectangle.IsEmpty && rectangle.Width > 10 && rectangle.Height > 8)
            dc.DrawRectangle(null, selectedInsetPen, new Rect(rectangle.X + 3, rectangle.Y + 3, rectangle.Width - 6, rectangle.Height - 6));
    }
    private static IReadOnlyList<TimelineMark> BuildMarks(EvidenceObject report, IReadOnlySet<string> owners, IReadOnlyDictionary<string, string> buffNames, EvidenceObject frameRules)
    {
        List<TimelineMark> result = [];
        foreach (var skill in TimelineSkills.Build(report)) result.Add(new(skill.Owner, skill.Cast is null ? "命中" : "施放", skill.Name, skill.Start, skill.End,
            skill.Cast is null ? skill.Events : [skill.Cast, .. skill.Events], skill, FrameReference: SkillFrameReference.For(skill, frameRules)));
        var events = EvidenceView.Rows(report.Get("timeline_events")).Where(row => owners.Contains(EvidenceView.Text(row.Get("source_character_key"))) || owners.Contains(EvidenceView.Text(row.Get("target_character_key")))).ToArray();
        foreach (var episode in BuffDisplay.Build(events.Where(row => EvidenceView.Text(row.Get("lane_type")) == "buff")))
        {
            var row = episode.Evidence[0];
            var target = EvidenceView.Text(row.Get("target_character_key")); var owner = owners.Contains(target) ? target : EvidenceView.Text(row.Get("source_character_key"));
            result.Add(new(owner, "BUFF", BuffDisplay.Name(row, buffNames), episode.Start, episode.End, episode.Evidence, Buff: episode));
        }
        return result.OrderBy(mark => mark.Start).ToArray();
    }
    internal void Configure(string character, bool showBuffs, double timeZoom, double graphScale, bool useFrames)
    {
        if (zoom != timeZoom) fittedWidth = null;
        filter = character; buffs = showBuffs; zoom = timeZoom; rowScale = graphScale; frames = useFrames;
        trackCache = null; inputLayout = null; InvalidateMeasure(); InvalidateVisual();
    }
    internal void SetInputEvidence(EvidenceObject value)
    { input = value; inputLayout = null; InvalidateMeasure(); InvalidateVisual(); }
    internal void SetLaneConfigs(EvidenceObject value) { laneConfigs = value; trackCache = null; inputLayout = null; InvalidateMeasure(); InvalidateVisual(); }
    internal void ToggleLane(string owner, string lane)
    { if (!expanded.Add((owner, lane))) expanded.Remove((owner, lane)); trackCache = null; inputLayout = null; InvalidateMeasure(); InvalidateVisual(); }
    private TimelineMark[] Visible() => marks.Where(mark => (filter.Length == 0 || mark.Owner == filter) && (buffs || mark.Lane != "BUFF")).ToArray();
    private IReadOnlyList<Track> Tracks()
    {
        if (trackCache is not null) return trackCache;
        laneRows = null; List<Track> tracks = []; var visible = Visible();
        var pixelsPerMs = Math.Max(1, Math.Max(ContentWidth, viewportWidth) - Labels - 10) / Duration;
        foreach (var owner in names.Keys.Where(owner => filter.Length == 0 || filter == owner))
        {
            foreach (var lane in RoleLanes(owner))
            {
                var members = lane.Skills.ToHashSet(StringComparer.Ordinal); var group = visible.Where(mark => mark.Owner == owner && mark.Skill is not null && members.Contains(mark.Skill.Key)).OrderBy(mark => mark.Start).ToArray();
                if (group.Length == 0) continue;
                List<double> edges = []; List<(TimelineMark, int)> placements = [];
                foreach (var mark in group)
                {
                    var bounds = DisplayBounds(mark); var start = bounds.Start * pixelsPerMs; var end = Math.Max(bounds.End * pixelsPerMs, start + 4);
                    var row = expanded.Contains((owner, lane.Id)) ? edges.FindIndex(edge => edge + 2 <= start) : 0;
                    if (row < 0) row = edges.Count;
                    if (row == edges.Count) edges.Add(end); else edges[row] = Math.Max(edges[row], end);
                    placements.Add((mark, row));
                }
                tracks.Add(new(owner, lane.Id, lane.Name, false, placements, Math.Max(1, edges.Count)));
            }
            var buffMarks = visible.Where(mark => mark.Owner == owner && mark.Lane == "BUFF").ToArray();
            foreach (var group in buffMarks.GroupBy(mark => mark.Buff!.Key))
            {
                var key = group.Key;
                var id = "buff:" + PythonSortedJson.Serialize(new EvidenceArray(new[] { key.Event, key.SourceCharacter, key.SourceActor, key.TargetCharacter, key.TargetActor }.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray()), compact: true);
                tracks.Add(new(owner, id, group.First().Name, true, group.Select(mark => (mark, 0)).ToArray(), 1));
            }
            if (!tracks.Any(track => track.Owner == owner) && SkillOptions(owner).Count > 0) tracks.Add(new(owner, "empty", "未选择技能", false, [], 1));
        }
        return trackCache = tracks;
    }
    private (string Owner, string Lane)[] Lanes()
    {
        var tracks = Tracks();
        return laneRows ??= tracks.SelectMany(track => Enumerable.Repeat((track.Owner, track.Id), track.Rows)).ToArray();
    }
    private IReadOnlyList<(TimelineMark Mark, int Row)> VisiblePlacements(Track track, double pixelsPerMs)
    {
        if (viewportWidth <= 0) return track.Placements;
        track.Index ??= new(track.Placements, placement =>
        {
            var mark = placement.Mark; var range = DisplayBounds(mark);
            var start = Math.Min(range.Start, mark.Start); var end = Math.Max(range.End, mark.End);
            foreach (var time in DamageTimes(mark)) { start = Math.Min(start, time); end = Math.Max(end, time); }
            if (mark.Buff is { } buff) foreach (var state in buff.States)
            { start = Math.Min(start, state.Start); end = Math.Max(end, state.Start); }
            return (start, end);
        });
        var margin = 4 + 3.5 * rowScale;
        track.Index.Query((viewportX - margin) / pixelsPerMs, (viewportX + viewportWidth - Labels + margin) / pixelsPerMs, visiblePlacements);
        return visiblePlacements;
    }
    private double[] DamageTimes(TimelineMark mark)
    {
        if (damageTimes.TryGetValue(mark, out var times)) return times;
        return damageTimes[mark] = mark.Evidence.Where(row => EvidenceView.Text(row.Get("event_type")) == "damage")
            .Select(row => EvidenceView.Number(row.Get("ts_ms_from_start"))).OfType<double>().ToArray();
    }
    protected override Size MeasureOverride(Size availableSize) => new(ContentWidth, Header + Math.Max(1, Lanes().Length + ObservationRows + (InputLayout.ExtraRow ? 1 : 0)) * RowHeight);
    private void Text(DrawingContext dc, string value, Point at, Brush brush, double size = 12, double width = double.PositiveInfinity)
    {
        if (collectLabels && at.X < Labels) { labelText.Add((value, at, brush, size, width)); return; }
        var dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip; var key = (value, size * fontScale, width, brush, dpi);
        if (!textCache.TryGetValue(key, out var text))
        {
            text = new FormattedText(value, CultureInfo.CurrentCulture, FlowDirection.LeftToRight, typeface, size * fontScale, brush, dpi);
            if (double.IsFinite(width)) { text.MaxTextWidth = Math.Max(1, width); text.Trimming = TextTrimming.CharacterEllipsis; text.MaxLineCount = 1; }
            if (textCache.Count >= 1024) textCache.Clear(); textCache[key] = text;
        }
        dc.DrawText(text, at);
    }
    protected override void OnRender(DrawingContext dc)
    {
        var measured = RenderMeasured;
        var started = measured is null ? 0 : Stopwatch.GetTimestamp();
        var allocated = measured is null ? 0 : GC.GetAllocatedBytesForCurrentThread();
        ContentRenderCount++;
        base.OnRender(dc); decorations.Clear(); hitAreas.Clear(); inputHitAreas.Clear(); labelHitAreas.Clear(); inputSpans.Clear(); settingsAreas.Clear(); expandAreas.Clear(); labelText.Clear(); collectLabels = true; BuffChangeMarkers = 0; var lanes = Lanes(); var tracks = Tracks(); var ink = Ink;
        dc.DrawRectangle(CanvasBackground, null, new Rect(RenderSize));
        var width = Math.Max(1, ActualWidth - Labels - 10); double X(double stamp) => Labels + stamp / Duration * width;
        var rowHeight = RowHeight; var grid = gridPen;
        var step = Math.Pow(10, Math.Floor(Math.Log10(Math.Max(1, Duration / 1000 / Math.Max(1, width / 90)))));
        while (step * width / (Duration / 1000) < 70) step *= 2;
        List<(double Stamp, double X)> ticks = [];
        var tickMs = step * 1000;
        var firstTick = viewportWidth > 0 ? Math.Max(0, Math.Floor(viewportX / width * Duration / tickMs) * tickMs) : 0;
        var lastTick = viewportWidth > 0 ? Math.Min(Duration, Math.Ceiling((viewportX + viewportWidth - Labels) / width * Duration / tickMs) * tickMs) : Duration;
        for (var stamp = firstTick; stamp <= lastTick; stamp += tickMs)
        {
            var x = X(stamp); dc.DrawLine(grid, new Point(x, Header), new Point(x, ActualHeight));
            ticks.Add((stamp, x));
        }
        var index = 0;
        for (var trackIndex = 0; trackIndex < tracks.Count; trackIndex++)
        {
            var track = tracks[trackIndex];
            var y = Header + index * rowHeight; var trackHeight = track.Rows * rowHeight;
            if (!VisibleY(y, y + trackHeight)) { index += track.Rows; continue; }
            if (ownerOrder.GetValueOrDefault(track.Owner) % 2 == 0) dc.DrawRectangle(trackTint, null, new Rect(0, y, ActualWidth, trackHeight));
            dc.DrawLine(grid, new Point(CharacterWidth, y + trackHeight), new Point(ActualWidth, y + trackHeight));
            if (track.Buff)
            {
                if (trackIndex == 0 || !tracks[trackIndex - 1].Buff) dc.DrawLine(grid, new(CharacterWidth, y), new(ActualWidth, y));
                dc.DrawLine(grid, new(CharacterWidth, y), new(CharacterWidth, y + trackHeight)); dc.DrawLine(grid, new(ActualWidth - .5, y), new(ActualWidth - .5, y + trackHeight));
                labelHitAreas.Add((new(viewportX + CharacterWidth + 1, y, Labels - CharacterWidth - 1, trackHeight), track.Name + "\n" + BuffDisplay.Source(track.Placements[0].Mark.Evidence[0])));
            }
            Text(dc, (track.Buff ? "" : expanded.Contains((track.Owner, track.Id)) ? "▾ " : "▸ ") + track.Name, new Point(CharacterWidth + 2, y + 7), ink, width: Labels - CharacterWidth - 8);
            if (!track.Buff && track.Id != "empty") expandAreas.Add((new(viewportX + CharacterWidth + 1, y, Labels - CharacterWidth - 1, rowHeight), track.Owner, track.Id));
            foreach (var (mark, subrow) in VisiblePlacements(track, width / Duration))
            {
                var markY = y + subrow * rowHeight;
                if (!VisibleY(markY, markY + rowHeight)) continue;
                var bounds = DisplayBounds(mark); var fallback = ShowFrameReference && mark.FrameReference is { } frameRule && BattleEvidence.Number(frameRule.Get("end_ms")) is not null;
                var rectangle = new Rect(X(bounds.Start), markY + 5, Math.Max(4, X(bounds.End) - X(bounds.Start)), rowHeight - 10);
                var visibleBlock = VisibleX(rectangle.Left, rectangle.Right);
                var fill = mark.Lane == "BUFF" ? buffFill : mark.Lane == "施放" ? skillFill : hitFill;
                if (visibleBlock)
                {
                    hitAreas.Add((rectangle, mark));
                }
                var visibleUnderline = Rect.Empty;
                if (fallback)
                {
                    var underline = new Rect(X(mark.Start), markY + rowHeight - 4, Math.Max(4, X(mark.End) - X(mark.Start)), 3);
                    if (VisibleX(underline.Left, underline.Right))
                    { visibleUnderline = underline; hitAreas.Add((underline, mark)); }
                }
                if (visibleBlock || !visibleUnderline.IsEmpty)
                {
                    MarkDecoration entry = new(new DrawingGroup(), visibleBlock ? rectangle : Rect.Empty, visibleUnderline, fill, mark.Buff is not null, fallback);
                    if (!decorations.TryGetValue(mark, out var entries)) decorations[mark] = entries = [];
                    entries.Add(entry); PaintDecoration(entry, mark == selected); dc.DrawDrawing(entry.Drawing);
                }
                if (visibleBlock && rectangle.Width > 30) Text(dc, mark.Buff is { } buff ? BuffDisplay.StateText(buff.States) : mark.Name, new Point(rectangle.X + 4, rectangle.Y + 3), Brushes.Black, width: rectangle.Width - 8);
                if (mark.Buff is { } stateful)
                {
                    System.Numerics.BigInteger? previous = 0;
                    foreach (var state in stateful.States)
                    {
                        if (state.Stacks is { } stacks && previous is { } before && stacks != before)
                        {
                            var center = new Point(X(state.Start), rectangle.Y + rectangle.Height / 2); var radius = 3.5 * rowScale;
                            if (!VisibleX(center.X - radius, center.X + radius)) { previous = state.Stacks; continue; }
                            dc.DrawEllipse(Brushes.DodgerBlue, buffPointPen, center, radius, radius); BuffChangeMarkers++;
                            inputHitAreas.Add((new Rect(center.X - radius, center.Y - radius, 2 * radius, 2 * radius), $"{state.Start / 1000:F3}s · 层数 {before} → {stacks}\n" + BuffDisplay.StateText(stateful.States, state.Start)));
                        }
                        previous = state.Stacks;
                    }
                }
                foreach (var stamp in DamageTimes(mark))
                {
                    var x = X(stamp); if (!VisibleX(x, x)) continue;
                    dc.DrawLine(damageHitPen, new Point(x, markY + rowHeight - 10), new Point(x, markY + rowHeight - 3));
                }
            }
            index += track.Rows;
        }
        var ownerRow = 0;
        foreach (var group in tracks.GroupBy(track => track.Owner))
        {
            var count = group.Sum(track => track.Rows); var y = Header + ownerRow * rowHeight;
            var portrait = PortraitSize(count * rowHeight); var nameLeft = portrait > 0 ? portrait + 11 : 6;
            Text(dc, names.GetValueOrDefault(group.Key, group.Key), new(nameLeft, y + count * rowHeight / 2 - 7 * fontScale), ink, width: Math.Max(15, CharacterWidth - nameLeft - 30));
            var button = new Rect(CharacterWidth - 26, y + (count * rowHeight - 23) / 2, 24, 23); Text(dc, "⚙", button.TopLeft, ink, 16); settingsAreas.Add((new(button.X + viewportX, button.Y, button.Width, button.Height), group.Key));
            labelHitAreas.Add((new(viewportX, y, CharacterWidth - 28, count * rowHeight), names.GetValueOrDefault(group.Key, group.Key)));
            dc.DrawLine(groupPen, new(0, y + count * rowHeight), new(ActualWidth, y + count * rowHeight)); ownerRow += count;
        }
        var inputs = InputLayout;
        DrawObservations(dc, Header + lanes.Length * rowHeight, rowHeight, X);
        DrawPoise(dc, Header + (lanes.Length + EnergyRows) * rowHeight, rowHeight, X);
        if (inputs.ExtraRow)
        {
            var y = Header + (lanes.Length + ObservationRows) * rowHeight; Text(dc, "输入证据", new Point(6, y + 7), ink);
            dc.DrawLine(grid, new Point(0, y + rowHeight), new Point(ActualWidth, y + rowHeight));
        }
        DrawInputs(dc, inputs, lanes.Length, rowHeight, X);
        if (lanes.Length == 0 && !inputs.ExtraRow) Text(dc, "没有对应的施放或命中证据", new Point(12, Header + 8), ink);
        collectLabels = false; DrawPinnedLabels(dc, ticks, tracks, rowHeight); UpdateReference();
        measured?.Invoke(Stopwatch.GetElapsedTime(started).TotalMilliseconds, GC.GetAllocatedBytesForCurrentThread() - allocated);
    }
    private void Hover(object sender, MouseEventArgs args)
    {
        var point = args.GetPosition(this); var found = hitAreas.Where(area => area.Bounds.Contains(point)).Select(area => area.Mark).Distinct().ToArray();
        if (resizingLabels) { ResizeLabels(resizeStartWidth + point.X - resizeStartX); return; }
        var onDivider = Math.Abs(point.X - viewportX - Labels) <= 4;
        if (dividerHovered != onDivider) { dividerHovered = onDivider; InvalidateVisual(); }
        if (onDivider) { Cursor = Cursors.SizeWE; ToolTip = "拖动调整角色与轨道列宽"; return; }
        var stamp = point.X >= viewportX + Labels ? Math.Clamp((point.X - Labels) / Math.Max(1, ActualWidth - Labels - 10), 0, 1) * Duration : (double?)null;
        SetReference(stamp); ReferenceChanged?.Invoke(stamp);
        if (settingsAreas.Any(area => area.Bounds.Contains(point))) { Cursor = Cursors.Hand; ToolTip = "配置此角色的技能轨道"; return; }
        if (expandAreas.Any(area => area.Bounds.Contains(point))) { Cursor = Cursors.Hand; ToolTip = "展开／合并重叠技能块"; return; }
        Cursor = Cursors.Arrow;
        if (point.Y < StickyHeaderTop + Header) { ToolTip = stamp is { } time ? BattleDetails.Time(time, frames) : "时间轴"; return; }
        if (point.X < viewportX + Labels) { ToolTip = string.Join("\n", labelHitAreas.Where(area => area.Bounds.Contains(point)).Select(area => area.Tooltip)); return; }
        var descriptions = found.Select(mark => BattleDetails.Description(mark, frames) + (mark.Buff is { } buff ? "\n当前位置：" + BuffDisplay.StateText(buff.States, stamp) : ""))
            .Concat(labelHitAreas.Where(area => area.Bounds.Contains(point)).Select(area => area.Tooltip))
            .Concat(inputHitAreas.Where(area => area.Bounds.Contains(point)).Select(area => area.Tooltip))
            .Concat(ObservationTooltip(point) is { Length: > 0 } observation ? [observation] : []).ToArray();
        var text = descriptions.Length == 0 ? null : string.Join("\n\n", descriptions);
        if (!Equals(ToolTip, text)) ToolTip = text;
    }
}
