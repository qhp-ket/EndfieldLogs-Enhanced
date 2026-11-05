using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Realtime;

public delegate EvidenceObject? LiveEventCalculation(LiveEventBatch batch, LiveObserverClock? observer,
    bool summary, CancellationToken cancellationToken);

public sealed partial class LiveBattleSession
{
    private readonly Func<LiveEventCalculation>? eventCalculatorFactory;
    private readonly Func<long> eventWallClockMs;
    private readonly List<TraceEvent> events = [];
    private LiveEventCalculation? eventCalculator;
    private bool structuredInput;
    // Owned by calculatorGate, including capture of the next suffix while gate is held.
    private int consumedEvents;
    private sealed record EventRequest(LiveEventBatch Batch, LiveObserverClock? Observer);

    public void FeedEvent(TraceEvent item)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (eventCalculatorFactory is null) throw new InvalidOperationException("This live session has no event calculator");
            if (lines.Count > 0) throw new InvalidOperationException("Reset before switching live input formats");
            if (item.Type == "battle_timer" && Phase(item) == "reset")
            {
                ResetState(); structuredInput = true; return;
            }
            // Detach only newly appended evidence. No serialization or copy of the retained prefix is involved.
            item = CaptureEvent(item);
            structuredInput = true;
            Feed(new(item.CapturedAtMs, item.Type == "damage", EventContext(item),
                item.Type == "official_timer" && Phase(item) == "start", item.Type == "official_timer" && Phase(item) == "end",
                item.Type == "battle_timer" && Phase(item) == "start", item.Type == "battle_timer" && Phase(item) == "end",
                item.Type == "skill_cast" && Phase(item) == "start", item.Type == "clock_tick",
                (item.Data.Get("game_id") as EvidenceText)?.Value ?? ""), null, item);
        }
    }

    public void FeedEvents(IEnumerable<TraceEvent> source)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            foreach (var item in source) FeedEvent(item);
        }
    }

    private static string? Phase(TraceEvent item) => (item.Data.Get("phase") as EvidenceText)?.Value;
    private static bool EventContext(TraceEvent item) => item.Type is "dungeon" or "battle_result" or "squad" or "entity_stats"
        or "loadout_group" or "loadout_slot" or "loadout_stats" or "buff_start" or "buff_blackboard"
        or "legacy_attribute_modifier" or "legacy_damage_modifier";
    private static bool EventBoundary(TraceEvent item) => item.Type == "battle_timer" && Phase(item) is "start" or "end" or "reset"
        || item.Type == "official_timer" && Phase(item) == "end";

    private void PreserveEventContext()
    {
        var boundary = events.FindLastIndex(EventBoundary);
        var kept = events.Skip(boundary + 1).Where(EventContext).ToArray();
        events.Clear(); events.AddRange(kept);
    }

    public IReadOnlyList<TraceEvent> HistoryEventContext()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (lines.Count > 0) throw new InvalidOperationException("Legacy live input has line history context");
            var boundary = officialActive ? -1 : events.FindLastIndex(EventBoundary);
            return events.Skip(boundary + 1).Where(item => item.Type != "damage" && (officialActive || EventContext(item))).ToArray();
        }
    }

    private LiveObserverClock? ObserverClock(long? observerMs)
    {
        if (!officialActive || officialStartAbsMs is not { } start || hitCount <= 0 || closed) return null;
        var stamp = observerMs ?? (options.AlignToDataWatermark || !liveClockEnabled ? lastClockMs : eventWallClockMs());
        if (stamp is not { } clock) return null;
        if (observerMs is null && lastClockMs is { } latest && Math.Abs(clock - latest) > 300_000) clock = latest;
        var absolute = Math.Max(clock, lastHitAbsMs ?? long.MinValue);
        return new(absolute, Math.Max(absolute - start, 1));
    }

    private EventRequest CaptureEvents(LiveObserverClock? observer)
    {
        var after = eventCalculator is not null && calculatorGeneration == generation ? consumedEvents : 0;
        var suffix = new TraceEvent[events.Count - after];
        events.CopyTo(after, suffix, 0, suffix.Length);
        return new(new(generation, revision, after, suffix), observer);
    }

    private EvidenceObject? CalculateEvents(EventRequest request, CancellationToken token)
    {
        var batch = request.Batch;
        if (eventCalculator is null || calculatorGeneration != batch.Generation)
        {
            eventCalculator = eventCalculatorFactory!();
            calculatorGeneration = batch.Generation; consumedEvents = 0;
        }
        try
        {
            var result = eventCalculator(batch, request.Observer, options.Summary, token);
            consumedEvents = batch.AfterEvidenceIndex + batch.Events.Count;
            return result;
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            eventCalculator = null; consumedEvents = 0; throw;
        }
        catch
        {
            eventCalculator = null; consumedEvents = 0;
            // Replay is reserved for calculation failure. Capture exactly this request's prefix, not later arrivals.
            TraceEvent[] replay;
            lock (gate)
            {
                if (generation != batch.Generation || disposed) throw;
                replay = new TraceEvent[batch.AfterEvidenceIndex + batch.Events.Count];
                events.CopyTo(0, replay, 0, replay.Length);
            }
            var fallback = eventCalculatorFactory!();
            var result = fallback(batch with { AfterEvidenceIndex = 0, Events = replay }, request.Observer, options.Summary, token);
            eventCalculator = fallback; calculatorGeneration = batch.Generation; consumedEvents = replay.Length;
            return result;
        }
    }

    // The streams detach one business event before offering it to their independent sessions.
    // Core recognizes parser-owned containers too; arbitrary read-only wrappers still require a copy.
    internal static TraceEvent CaptureEvent(TraceEvent item) => TraceEventSnapshot.Capture(item);
}
