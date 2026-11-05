namespace EndfieldLogs.Core.Ingestion;

/// <summary>The final lifecycle stage: preserve pending-BUFF semantics across accepted and rejected HP rows.</summary>
public sealed class HitBuffLifecycleObservations
{
    private readonly HitObservationState hits;
    private readonly BuffInstanceState buffs;

    public HitBuffLifecycleObservations(HitObservationState hits, BuffInstanceState buffs)
    {
        if (!ReferenceEquals(hits.Party, buffs.Party)) throw new ArgumentException("Hit and BUFF handlers must share party observations.");
        this.hits = hits;
        this.buffs = buffs;
    }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        if (!line.Contains(" HP_V2 ", StringComparison.Ordinal)) return buffs.ObserveLifecycle(line, lineNumber, timestampMs);
        buffs.ObserveModifiers(line, TraceFields.Extract(line));
        var earlyReturn = hits.Observe(line, lineNumber, timestampMs);
        if (!earlyReturn) buffs.PendingRecord = null;
        return earlyReturn;
    }

    public bool Observe(DamageObservation observation, int lineNumber, long timestampMs)
    {
        var earlyReturn = hits.Observe(observation, lineNumber, timestampMs);
        if (!earlyReturn) buffs.PendingRecord = null;
        return earlyReturn;
    }

    internal bool ObserveOwned(DamageObservation observation, int lineNumber, long timestampMs)
    {
        var earlyReturn = hits.ObserveOwned(observation, lineNumber, timestampMs);
        if (!earlyReturn) buffs.PendingRecord = null;
        return earlyReturn;
    }
}
