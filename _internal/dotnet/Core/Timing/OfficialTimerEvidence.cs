using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Timing;

public sealed record TimerStart(int Line,long? ObservedMs,string? GameId,string? Source,string? ChallengeStartTs);
public sealed record TimerCompletion(int Line,long? ObservedMs,string? GameId,string? Source,string? IsPass,string? PassTimeMs);
public enum TimerLifecycleKind { Freeze, Boundary, BattleStart, BattleEnd }
public sealed record TimerLifecycleEvent(int Line,long? ObservedMs,string? GameId,string? Source,TimerLifecycleKind Kind,
    string? Count=null,string? FreezeInfos=null,string? StartMs=null,string? EndMs=null,string? PacketElapsedMs=null);

public sealed class OfficialTimerEvidence
{
    public TimerStart? Start { get; internal set; }
    public TimerCompletion? Complete { get; internal set; }
    public List<TimerLifecycleEvent> Events { get; } = [];
    public List<string> Conflicts { get; } = [];

    public OfficialTimerEvidence Copy()
    {
        OfficialTimerEvidence copy = new() { Start = Start, Complete = Complete };
        copy.Events.AddRange(Events); copy.Conflicts.AddRange(Conflicts);
        return copy;
    }

    public EvidenceObject ToEvidence()
    {
        static EvidenceValue Text(string? value) => value is null ? EvidenceNull.Value : new EvidenceText(value);
        static Dictionary<string,EvidenceValue> Common(int line,long? time,string? game,string? source) => new(StringComparer.Ordinal)
        {
            ["line"]=new EvidenceInteger(line), ["observedMs"]=time is null ? EvidenceNull.Value : new EvidenceInteger(time.Value),
            ["gameId"]=Text(game), ["source"]=Text(source),
        };
        EvidenceValue start = EvidenceNull.Value, complete = EvidenceNull.Value;
        if (Start is TimerStart first)
        {
            var fields = Common(first.Line,first.ObservedMs,first.GameId,first.Source);
            fields["challengeStartTs"] = Text(first.ChallengeStartTs);
            start = new EvidenceObject(fields);
        }
        if (Complete is TimerCompletion last)
        {
            var fields = Common(last.Line,last.ObservedMs,last.GameId,last.Source);
            fields["isPass"] = Text(last.IsPass);
            fields["passTimeMs"] = Text(last.PassTimeMs);
            complete = new EvidenceObject(fields);
        }
        List<EvidenceValue> events = [];
        foreach (var row in Events)
        {
            var fields = Common(row.Line,row.ObservedMs,row.GameId,row.Source);
            fields["kind"] = new EvidenceText(row.Kind switch
            {
                TimerLifecycleKind.Freeze => "freeze", TimerLifecycleKind.Boundary => "boundary",
                TimerLifecycleKind.BattleStart => "battle_start", _ => "battle_end",
            });
            if (row.Kind == TimerLifecycleKind.Freeze)
            {
                fields["count"] = Text(row.Count);
                fields["freezeInfos"] = Text(row.FreezeInfos);
            }
            if (row.Kind is TimerLifecycleKind.BattleStart or TimerLifecycleKind.BattleEnd) fields["startMs"] = Text(row.StartMs);
            if (row.Kind == TimerLifecycleKind.BattleEnd)
            {
                fields["endMs"] = Text(row.EndMs);
                fields["packetElapsedMs"] = Text(row.PacketElapsedMs);
            }
            events.Add(new EvidenceObject(fields));
        }
        return new(new Dictionary<string,EvidenceValue>(StringComparer.Ordinal)
        {
            ["version"]=new EvidenceInteger(1), ["start"]=start, ["complete"]=complete,
            ["events"]=new EvidenceArray(events), ["conflicts"]=new EvidenceArray(Conflicts.Select(row => (EvidenceValue)new EvidenceText(row)).ToArray()),
        });
    }
}
