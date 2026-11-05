using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.History;

public sealed record TraceEventBattleBounds(TraceBattleBounds Bounds, long FirstHitCapturedAtMs);

public static partial class TraceBattleSplitter
{
    /// <summary>Keep only boundary metadata while streaming structured trace; reuse the legacy battle-selection rules.</summary>
    public static IReadOnlyList<TraceEventBattleBounds> FindEventBounds(IEnumerable<TraceEvent> events, int offsetMinutes,
        long idleSplitMs = 30_000, CancellationToken cancellationToken = default)
    {
        List<Row> rows = [], hits = [];
        Dictionary<int, long> hitTimes = []; HashSet<int> loadouts = [];
        long? origin = null; var index = 0;
        foreach (var item in events)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var local = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(offsetMinutes));
            var stamp = local.TimeOfDay.Ticks / TimeSpan.TicksPerMillisecond; origin ??= stamp;
            var absolute = origin.Value + ((stamp - origin.Value) % 86_400_000 + 86_400_000) % 86_400_000;
            var hint = local.ToString("HH-mm-ss-fff", CultureInfo.InvariantCulture);
            var marker = ""; IReadOnlyDictionary<string, string> fields = new Dictionary<string, string>();
            if (item.Type is "official_timer" or "battle_timer" or "battle_phase" or "battle_timer_missing")
                (marker, fields) = TimerWire.Observation(item);
            else if (item.Type == "game_instance")
            {
                var context = ContextWire.Observation(item);
                marker = context.Get("action") is EvidenceText action ? action.Value switch
                { "restart" => "GAME_INST_RESTART", "leave" => "GAME_INST_LEAVE", _ => "" } : "";
                fields = new Dictionary<string, string> { ["gameId"] = TraceDataText(context.Get("game_id")) };
            }
            var hit = item.Type == "damage";
            var elapsed = marker == "OFFICIAL_TIMER_END" ? TraceFields.OptionalInteger(fields.GetValueOrDefault("passTime"))
                : marker == "GAME_TIMER_END" && TraceFields.OptionalInteger(fields.GetValueOrDefault("sane")) is { IsZero: false }
                    ? TraceFields.OptionalInteger(fields.GetValueOrDefault("elapsedMs")) : null;
            Row row = new(index, absolute, hint, hit, item.Type == "dungeon", marker == "OFFICIAL_TIMER_START",
                marker == "GAME_TIMER_START", marker == "OFFICIAL_TIMER_END", marker == "GAME_TIMER_END",
                marker is "GAME_TIMER_RESET" or "GAME_INST_RESTART" or "GAME_INST_LEAVE", elapsed > 0 ? elapsed : null,
                fields.GetValueOrDefault("gameId"), fields.GetValueOrDefault("challengeStartTs"), fields.GetValueOrDefault("source"), fields.GetValueOrDefault("startMs"));
            rows.Add(row);
            if (hit) { hits.Add(row); hitTimes[index] = item.CapturedAtMs; }
            if (item.Type is "loadout_slot" or "loadout_stats") loadouts.Add(index);
            index++;
        }
        return FindBounds(rows, hits, index, loadouts.Contains, _ => false, idleSplitMs, cancellationToken)
            .Select(bounds => new TraceEventBattleBounds(bounds, hitTimes[bounds.FirstHitLineIndex])).ToArray();
    }

    private static string TraceDataText(EvidenceValue value) => value is EvidenceNull ? "" : PythonDisplay.String(value);
}
