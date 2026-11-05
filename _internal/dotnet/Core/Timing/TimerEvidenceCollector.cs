using System.Text.RegularExpressions;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Timing;

public sealed class TimerEvidenceCollector
{
    public OfficialTimerEvidence? Evidence { get; private set; }

    public void Observe(int lineNumber,string line,long? timestampMs)
    {
        if (!new[] { "OFFICIAL_TIMER_", "GAME_TIMER_", "GAME_INST_", "GAME_MECHANICS_TIME_FREEZE" }
            .Any(label => line.Contains(label,StringComparison.Ordinal))) return;
        var markers = new[] { "GAME_TIMER_RESET", "OFFICIAL_TIMER_START", "OFFICIAL_TIMER_END", "GAME_MECHANICS_TIME_FREEZE",
            "GAME_INST_RESTART", "GAME_INST_LEAVE", "GAME_TIMER_START", "GAME_TIMER_END" }
            .Where(label => line.Contains(label + " ", StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
        Observe(lineNumber, markers, TraceFields.Extract(line), timestampMs);
    }

    public void Observe(int evidenceIndex, TraceEvent item)
    {
        (string Marker, IReadOnlyDictionary<string, string> Fields)? observation = item.Type switch
        {
            "battle_timer" or "official_timer" or "battle_phase" or "battle_timer_missing" => TimerWire.Observation(item),
            "game_instance" or "game_mechanics" => ContextWire.TimerObservation(item),
            _ => null,
        };
        if (observation is { } row) Observe(evidenceIndex, new HashSet<string>(StringComparer.Ordinal) { row.Marker }, row.Fields, item.CapturedAtMs);
    }

    private void Observe(int lineNumber, IReadOnlySet<string> markers, IReadOnlyDictionary<string, string> fields, long? timestampMs)
    {
        var game = fields.GetValueOrDefault("gameId");
        if (string.IsNullOrEmpty(game)) game = fields.GetValueOrDefault("game_id");
        var source = fields.GetValueOrDefault("source");
        if (markers.Contains("GAME_TIMER_RESET") && source == "CAPTURE_SESSION_START")
        {
            if (Evidence is not null) Evidence = new();
            return;
        }
        if (markers.Contains("OFFICIAL_TIMER_START"))
        {
            var start = new TimerStart(lineNumber,timestampMs,game,source,fields.GetValueOrDefault("challengeStartTs"));
            if (Evidence?.Start is TimerStart prior && prior.GameId == game && start.ChallengeStartTs is not (null or "" or "0")
                && prior.ChallengeStartTs == start.ChallengeStartTs && prior.Source == start.Source
                && !Evidence.Events.Any(row => row.Kind == TimerLifecycleKind.Boundary)) return;
            Evidence = new() { Start=start };
            return;
        }
        if (markers.Contains("OFFICIAL_TIMER_END"))
        {
            if (Evidence?.Start is TimerStart start && game != start.GameId) return;
            Evidence ??= new();
            var complete = new TimerCompletion(lineNumber,timestampMs,game,source,fields.GetValueOrDefault("isPass"),fields.GetValueOrDefault("passTime"));
            if (Evidence.Complete is not TimerCompletion prior) Evidence.Complete = complete;
            else if (prior.GameId != complete.GameId || prior.Source != complete.Source || prior.IsPass != complete.IsPass || prior.PassTimeMs != complete.PassTimeMs)
                Evidence.Conflicts.Add("conflicting_official_completion");
            return;
        }
        if (Evidence is null || Evidence.Complete is not null) return;
        TimerLifecycleEvent? observation = null;
        if (markers.Contains("GAME_MECHANICS_TIME_FREEZE"))
            observation = new(lineNumber,timestampMs,game,source,TimerLifecycleKind.Freeze,Count:fields.GetValueOrDefault("count"),FreezeInfos:fields.GetValueOrDefault("freezeInfos"));
        else if (markers.Contains("GAME_TIMER_RESET") || markers.Contains("GAME_INST_RESTART") || markers.Contains("GAME_INST_LEAVE"))
            observation = new(lineNumber,timestampMs,game,source,TimerLifecycleKind.Boundary);
        else if (markers.Contains("GAME_TIMER_START"))
            observation = new(lineNumber,timestampMs,game,source,TimerLifecycleKind.BattleStart,StartMs:fields.GetValueOrDefault("startMs"));
        else if (markers.Contains("GAME_TIMER_END"))
            observation = new(lineNumber,timestampMs,game,source,TimerLifecycleKind.BattleEnd,StartMs:fields.GetValueOrDefault("startMs"),
                EndMs:fields.GetValueOrDefault("endMs"),PacketElapsedMs:fields.GetValueOrDefault("packetElapsedMs"));
        if (observation is not null) Evidence.Events.Add(observation);
    }

    public static OfficialTimerEvidence? Collect(string text,IReadOnlyDictionary<int,long>? observedTimes=null,
        IEnumerable<(int LineNumber,string Text)>? indexedLines=null)
    {
        TimerEvidenceCollector collector = new();
        if (indexedLines is null)
        {
            var lines = Regex.Split(text,@"\r\n|[\n\v\f\r\x1c-\x1e\x85\u2028\u2029]");
            indexedLines = lines.Select((line,index) => (index+1,line));
        }
        foreach (var (number,line) in indexedLines)
        {
            var time = observedTimes is null ? TraceFields.PrefixedTimestampMs(line)
                : observedTimes.TryGetValue(number,out var observed) ? observed : (long?)null;
            collector.Observe(number,line,time);
        }
        return collector.Evidence;
    }
}
