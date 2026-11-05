using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.History;

public sealed record TraceBattleSegment(int BattleIndex, int StartLineIndex, string Content, string FirstHitHint,
    string LastHitHint, int FirstHitLineIndex);

public sealed record TraceBattleBounds(int BattleIndex, int StartLineIndex, int EndLineIndex, int ContentLineCount,
    string FirstHitHint, string LastHitHint, int FirstHitLineIndex);

/// <summary>Lightweight trace boundaries; no resource loading, canonical parser or damage computation.</summary>
public static partial class TraceBattleSplitter
{
    private sealed record Row(int Line, long Time, string Hint, bool Hit, bool Dungeon, bool OfficialStart,
        bool PacketStart, bool OfficialEnd, bool PacketEnd, bool Boundary, BigInteger? Elapsed,
        string? Game, string? Challenge, string? TimerSource, string? StartTick)
    { public bool End => OfficialEnd || PacketEnd; }
    [GeneratedRegex(@"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")]
    private static partial Regex Timestamp();
    [GeneratedRegex(@"\bGAME_TIMER_END\b.*?\belapsedMs=(\d+).*?\bsane=(\d+)")]
    private static partial Regex PacketElapsed();
    [GeneratedRegex(@"\bOFFICIAL_TIMER_END\b.*?\bpassTime=(\d+)")]
    private static partial Regex OfficialElapsed();
    private static BigInteger? Elapsed(string line)
    {
        var match = OfficialElapsed().Match(line);
        var official = match.Success ? TraceFields.OptionalInteger(match.Groups[1].Value) : null;
        if (official > 0) return official;
        match = PacketElapsed().Match(line);
        if (!match.Success || TraceFields.OptionalInteger(match.Groups[2].Value) is not { IsZero: false }) return null;
        var packet = TraceFields.OptionalInteger(match.Groups[1].Value); return packet > 0 ? packet : null;
    }
    private static List<Row> Starts(IReadOnlyList<Row> rows)
    {
        List<Row> starts = [];
        (string? Game, string? Start)? official = null;
        (string? Source, string? Start)? packet = null;
        foreach (var row in rows)
        {
            if (row.Boundary && (official is null || string.IsNullOrEmpty(row.Game) || row.Game == official.Value.Game)) { official = null; packet = null; }
            if (row.OfficialStart)
            {
                var identity = (row.Game, row.Challenge);
                if (official is not null && row.Challenge is not (null or "" or "0") && identity == official) continue;
                official = identity; packet = null; starts.Add(row);
            }
            else if (row.OfficialEnd)
            { if (official is not null && row.Game == official.Value.Game) { official = null; packet = null; } }
            else if (row.PacketStart)
            {
                if (official is not null) continue;
                var identity = (row.TimerSource, row.StartTick);
                if (row.StartTick is not null && identity == packet) continue;
                packet = identity; starts.Add(row);
            }
            else if (row.PacketEnd) packet = null;
        }
        return starts;
    }
    private static bool Loadout(string line) => line.Contains("LOADOUT slot=", StringComparison.Ordinal) || line.Contains("LOADOUT_STATS ", StringComparison.Ordinal);
    private static int ContextStart(IReadOnlyList<Row> rows, Func<int, bool> loadout, Func<int, bool> blank, int start, int minimum)
    {
        var context = rows.LastOrDefault(row => row.Dungeon && row.Line >= minimum && row.Line <= start)?.Line ?? start;
        for (var index = context; index >= minimum; index--)
        {
            if (!loadout(index)) continue;
            var block = index;
            for (var previous = index - 1; previous >= minimum; previous--)
            {
                if (loadout(previous)) block = previous;
                else if (!blank(previous)) break;
            }
            return Math.Min(context, block);
        }
        return context;
    }
    private static int Tail(IReadOnlyList<Row> rows, Row end, int next)
    {
        var result = end.Line;
        foreach (var row in rows)
        {
            if (row.Line <= end.Line) continue;
            if (row.Line >= next || row.Time - end.Time > 10_000 || row.Hit || row.Dungeon || row.OfficialStart || row.PacketStart) break;
            result = row.Line;
        }
        return result;
    }
    private static int FindLine(IReadOnlyList<Row> rows, long time) => rows.FirstOrDefault(row => row.Time >= time)?.Line ?? rows.LastOrDefault()?.Line ?? 0;

    public static IReadOnlyList<TraceBattleSegment> Split(string text, long idleSplitMs = 30_000, CancellationToken cancellationToken = default)
    {
        var lines = PythonTextLines.SplitKeepEnds(text).ToArray();
        return FindBounds(lines, idleSplitMs, cancellationToken).Select(bounds => new TraceBattleSegment(bounds.BattleIndex,
            bounds.StartLineIndex, PythonDisplay.Strip(string.Concat(lines.Skip(bounds.StartLineIndex).Take(bounds.EndLineIndex - bounds.StartLineIndex))),
            bounds.FirstHitHint, bounds.LastHitHint, bounds.FirstHitLineIndex)).ToArray();
    }

    /// <summary>Metadata-only boundaries over original lines; no battle text is materialized.</summary>
    public static IReadOnlyList<TraceBattleBounds> FindBounds(IReadOnlyList<string> lines, long idleSplitMs = 30_000,
        CancellationToken cancellationToken = default)
    {
        List<Row> rows = [], hits = []; long? origin = null;
        for (var index = 0; index < lines.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested(); var line = lines[index]; var stamp = Timestamp().Match(line);
            if (!stamp.Success) continue;
            var hintValue = string.Join('-', stamp.Groups.Cast<Group>().Skip(1).Select(group => group.Value));
            var relative = TraceFields.HintTimestampMs(hintValue)!.Value; origin ??= relative;
            var absolute = origin.Value + ((relative - origin.Value) % 86_400_000 + 86_400_000) % 86_400_000;
            // Keep out-of-range timestamp components exactly as the splitter reference does.
            var parts = stamp.Groups.Cast<Group>().Skip(1).Select(group => TraceFields.OptionalInteger(group.Value)!.Value).ToArray();
            var hint = $"{parts[0]:00}-{parts[1]:00}-{parts[2]:00}-{parts[3]:000}";
            var fields = line.Contains("TIMER", StringComparison.Ordinal) || line.Contains("GAME_INST_", StringComparison.Ordinal) ? TraceFields.Extract(line) : [];
            Row row = new(index, absolute, hint, line.Contains(" HP_V2 ", StringComparison.Ordinal), line.Contains("DUNGEON_CONTEXT", StringComparison.Ordinal),
                line.Contains("OFFICIAL_TIMER_START", StringComparison.Ordinal), line.Contains("GAME_TIMER_START", StringComparison.Ordinal),
                line.Contains("OFFICIAL_TIMER_END", StringComparison.Ordinal), line.Contains("GAME_TIMER_END", StringComparison.Ordinal),
                new[] { "GAME_TIMER_RESET ", "GAME_INST_RESTART ", "GAME_INST_LEAVE " }.Any(token => line.Contains(token, StringComparison.Ordinal)),
                Elapsed(line), fields.GetValueOrDefault("gameId"), fields.GetValueOrDefault("challengeStartTs"), fields.GetValueOrDefault("source"), fields.GetValueOrDefault("startMs"));
            rows.Add(row); if (row.Hit) hits.Add(row);
        }
        return FindBounds(rows, hits, lines.Count, index => Loadout(lines[index]),
            index => lines[index].All(unit => char.IsWhiteSpace(unit) || unit is >= '\u001c' and <= '\u001f'), idleSplitMs, cancellationToken);
    }

    private static IReadOnlyList<TraceBattleBounds> FindBounds(IReadOnlyList<Row> rows, IReadOnlyList<Row> hits, int count,
        Func<int, bool> loadout, Func<int, bool> blank, long idleSplitMs, CancellationToken cancellationToken)
    {
        if (hits.Count == 0) throw new InvalidDataException("未在日志中识别到可用 battle。");
        List<TraceBattleBounds> segments = [];
        void Add(int start, int end, IReadOnlyList<Row> selected, int? battleIndex = null)
        {
            if (selected.Count == 0) return;
            var first = start; var last = end;
            // Match len(stripped_content.splitlines()) while retaining the original source start.
            while (first <= last && blank(first)) first++;
            while (last >= first && blank(last)) last--;
            if (first <= last) segments.Add(new(battleIndex ?? segments.Count + 1, start, end + 1, last - first + 1,
                selected[0].Hint, selected[^1].Hint, selected[0].Line));
        }
        var starts = Starts(rows);
        for (var index = 0; index < starts.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested(); var start = starts[index];
            var minimum = Math.Max(index > 0 ? starts[index - 1].Line + 1 : 0, rows.Where(row => row.End && row.Line < start.Line).Select(row => row.Line).DefaultIfEmpty(-1).Max() + 1);
            var context = ContextStart(rows, loadout, blank, start.Line, minimum); var next = index + 1 < starts.Count ? starts[index + 1].Line : count;
            var end = start.OfficialStart ? rows.FirstOrDefault(row => row.OfficialEnd && row.Game == start.Game && row.Line >= start.Line && row.Line < next)
                ?? rows.FirstOrDefault(row => row.Boundary && (string.IsNullOrEmpty(row.Game) || row.Game == start.Game) && row.Line > start.Line && row.Line < next)
                : rows.FirstOrDefault(row => row.End && row.Line >= start.Line && row.Line < next);
            var hitEnd = end?.Line ?? next - 1;
            Add(context, end is null ? next - 1 : Tail(rows, end, next), hits.Where(row => row.Line >= start.Line && row.Line <= hitEnd).ToArray());
        }
        if (segments.Count > 0) return segments;
        var previousEnd = -1;
        foreach (var end in rows.Where(row => row.End && row.Elapsed is not null))
        {
            cancellationToken.ThrowIfCancellationRequested(); if (end.Line <= previousEnd) continue;
            var startTime = (long)BigInteger.Max(end.Time - end.Elapsed!.Value, 0);
            var marker = Math.Max(FindLine(rows, startTime), previousEnd + 1);
            var context = ContextStart(rows, loadout, blank, marker, previousEnd + 1); var tail = Tail(rows, end, count);
            Add(context, tail, hits.Where(row => row.Line >= context && row.Line <= tail && row.Time >= startTime && row.Time <= end.Time).ToArray());
            previousEnd = Math.Max(previousEnd, tail);
        }
        if (segments.Count > 0) return segments;
        List<(int Start, int End)> spans = []; var spanStart = 0;
        for (var index = 1; index < hits.Count; index++)
            if (hits[index].Time - hits[index - 1].Time > idleSplitMs) { spans.Add((spanStart, index - 1)); spanStart = index; }
        spans.Add((spanStart, hits.Count - 1));
        var startLines = spans.Select(span => FindLine(rows, Math.Max(hits[span.Start].Time - idleSplitMs, 0))).ToArray();
        for (var index = 0; index < spans.Count; index++)
            Add(startLines[index], index + 1 < spans.Count ? Math.Max(startLines[index + 1] - 1, startLines[index]) : count - 1,
                hits.Skip(spans[index].Start).Take(spans[index].End - spans[index].Start + 1).ToArray(), index + 1);
        return segments;
    }
}
