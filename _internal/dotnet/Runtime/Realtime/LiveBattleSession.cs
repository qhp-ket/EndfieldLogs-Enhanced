using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Realtime;

public sealed record LiveSessionOptions(long IdleSplitMs = 30_000, bool Summary = true,
    bool AlignToDataWatermark = true, double MinReparseIntervalMs = 0);

public sealed record LiveSessionState(long Generation, long Revision, long SourceRevision, int LineCount,
    long HitCount, bool Dirty, bool OfficialTimerActive, bool ClosedByTimerEnd, bool ClosedByOfficialTimerEnd,
    long Calculations, long DiscardedResults, string? LastError, bool StructuredInput = false);

public delegate EvidenceObject? LiveBattleCalculation(IReadOnlyList<string> lines, string? timerLine,
    bool summary, CancellationToken cancellationToken);

/// <summary>Owns one ordered battle and its completed publication; calculation never holds the state lock.</summary>
public sealed partial class LiveBattleSession : IDisposable
{
    private const long DayMs = 86_400_000;
    private readonly object gate = new();
    private readonly SemaphoreSlim calculatorGate = new(1, 1);
    private readonly CancellationTokenSource lifetime = new();
    private readonly LiveSessionOptions options;
    private readonly Func<LiveBattleCalculation> calculatorFactory;
    private readonly Func<long> wallClockMs;
    private readonly Func<double> monotonicMs;
    private readonly List<string> lines = [];
    private LiveBattleCalculation? calculator;
    private long calculatorGeneration = -1;
    private EvidenceObject? snapshot;
    private long generation, revision, sourceRevision, dayOffsetMs, hitCount, calculations, discardedResults;
    private long? lastClockMs, lastHitAbsMs, officialStartAbsMs, failedRevision;
    private string officialGameId = "";
    private string? lastError;
    private bool officialActive, closed, officiallyClosed, dirty, forceReparse, fromExplicitClock, disposed;
    private bool liveClockEnabled = true;
    private double? lastParseMs;

    [GeneratedRegex(@"\bHP_V2\s+#\d+\b")]
    private static partial Regex Hit();
    [GeneratedRegex(@"(?:\b(?:DUNGEON_CONTEXT|BATTLE_RESULT|SQUAD|ENTITY_STATS|LOADOUT(?:_STATS)?|BUFF_START|ATTR_MOD|DMG_MOD)\b|\bBB\[\d+\](?=:))")]
    private static partial Regex Context();
    [GeneratedRegex(@"\b(?:GAME_TIMER_START|GAME_TIMER_END|GAME_TIMER_RESET|OFFICIAL_TIMER_END)\b")]
    private static partial Regex Boundary();
    [GeneratedRegex(@"^\[[\d:.]+\] (?:GAME_CLOCK_TICK|GAME_TIMER_TICK|HEARTBEAT)(?:\s|$)")]
    private static partial Regex Heartbeat();

    public LiveBattleSession(Func<LiveBattleCalculation> calculatorFactory, LiveSessionOptions? options = null,
        Func<long>? wallClockMs = null, Func<double>? monotonicMs = null,
        Func<LiveEventCalculation>? eventCalculatorFactory = null)
    {
        this.calculatorFactory = calculatorFactory;
        this.options = options ?? new();
        this.wallClockMs = wallClockMs ?? (() => (long)DateTime.Now.TimeOfDay.TotalMilliseconds);
        this.monotonicMs = monotonicMs ?? (() => Stopwatch.GetTimestamp() * 1000.0 / Stopwatch.Frequency);
        this.eventCalculatorFactory = eventCalculatorFactory;
        eventWallClockMs = wallClockMs ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    public static LiveBattleSession Create(ResourceFiles files, DateOnly referenceDate, LiveSessionOptions? options = null,
        TimeZoneInfo? timeZone = null)
    {
        var resources = BattleIngestionResources.Load(files);
        var analysis = BattleReportAnalysis.Load(files, timeZone);
        return new(() => new LiveBattleEngine(resources, analysis, referenceDate, timeZone).Snapshot, options,
            eventCalculatorFactory: () => new LiveBattleEngine(resources, analysis, referenceDate, timeZone).SnapshotEvents);
    }

    public LiveSessionState State
    {
        get { lock (gate) return new(generation, revision, sourceRevision, structuredInput ? events.Count : lines.Count, hitCount, dirty,
            officialActive, closed, officiallyClosed, calculations, discardedResults, lastError, structuredInput); }
    }

    public bool Summary => options.Summary;

    /// <summary>Release allocation/ingestion caches while retaining trace context and the last completed snapshot.</summary>
    public async Task ReleaseCalculatorAsync(CancellationToken cancellationToken = default)
    {
        await calculatorGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try { calculator = null; eventCalculator = null; calculatorGeneration = -1; consumedEvents = 0; }
        finally { calculatorGate.Release(); }
    }

    /// <summary>UI reads only a detached, already completed result.</summary>
    public EvidenceObject? ReadSnapshot()
    {
        lock (gate) return Copy(snapshot);
    }

    public void Reset()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            ResetState();
        }
    }

    private void ResetState()
    {
        revision++; generation++;
        lines.Clear();
        events.Clear(); structuredInput = false;
        lastClockMs = lastHitAbsMs = officialStartAbsMs = null;
        dayOffsetMs = hitCount = 0;
        officialGameId = "";
        officialActive = closed = officiallyClosed = dirty = forceReparse = fromExplicitClock = false;
        snapshot = null;
        lastParseMs = null;
        failedRevision = null;
        lastError = null;
    }

    public void SetLiveClockEnabled(bool enabled)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (enabled == liveClockEnabled) return;
            liveClockEnabled = enabled;
            revision++;
            dirty = forceReparse = true;
        }
    }

    public void FeedLines(IEnumerable<string> source)
    {
        foreach (var line in source) FeedLine(line);
    }

    public void FeedLine(string line)
    {
        var raw = line.EndsWith('\n') ? line : line + '\n';
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (structuredInput) throw new InvalidOperationException("Reset before switching live input formats");
            if (Has(raw, "GAME_TIMER_RESET")) { ResetState(); return; }
            Feed(new(TraceFields.PrefixedTimestampMs(raw), Hit().IsMatch(raw), Context().IsMatch(raw),
                Has(raw, "OFFICIAL_TIMER_START"), Has(raw, "OFFICIAL_TIMER_END"), Has(raw, "GAME_TIMER_START"), Has(raw, "GAME_TIMER_END"),
                Has(raw, "SKILL_CAST_START"), Heartbeat().IsMatch(raw), TraceFields.Token(raw, "gameId") ?? ""), raw, null);
        }
    }

    private readonly record struct Observation(long? Clock, bool Hit, bool Context, bool OfficialStart, bool OfficialEnd,
        bool TimerStart, bool TimerEnd, bool SkillStart, bool Heartbeat, string GameId);

    // Both adapters classify their observed fields; battle boundaries and publication state share this mutation path.
    private void Feed(Observation observation, string? raw, TraceEvent? item)
    {
            var clock = observation.Clock;
            long? absolute = null;
            var hit = observation.Hit;
            var context = observation.Context;
            var officialStart = observation.OfficialStart;
            var officialEnd = observation.OfficialEnd;
            var start = officialStart || (observation.TimerStart && !officialActive);
            var end = officialEnd || observation.TimerEnd;
            revision++;
            if (clock is { } timestamp)
            {
                if (!structuredInput && lastClockMs is { } previous && timestamp + 300_000 < previous) dayOffsetMs += DayMs;
                lastClockMs = timestamp;
                absolute = timestamp + dayOffsetMs;
                if (!hit && !officialActive && !closed && lastHitAbsMs is { } last && absolute - last > options.IdleSplitMs)
                {
                    PreserveContext();
                    generation++;
                    lastHitAbsMs = null;
                    hitCount = 0;
                }
            }
            if (start)
            {
                PreserveContext();
                generation++;
                lastHitAbsMs = null;
                officialActive = officialStart;
                officialStartAbsMs = officialStart ? absolute : null;
                officialGameId = officialStart ? observation.GameId : "";
                hitCount = 0;
                snapshot = null;
                closed = officiallyClosed = false;
            }
            if (hit && absolute is { } hitTime)
            {
                if (closed && !officiallyClosed)
                {
                    PreserveContext();
                    generation++;
                    lastHitAbsMs = null;
                    officialActive = false;
                    hitCount = 0;
                    snapshot = null;
                    closed = officiallyClosed = false;
                }
                if (!closed)
                {
                    if (!officialActive && lastHitAbsMs is { } last && hitTime - last > options.IdleSplitMs)
                    {
                        PreserveContext();
                        generation++;
                        officialActive = false;
                        hitCount = 0;
                        snapshot = null;
                    }
                    lastHitAbsMs = hitTime;
                    hitCount++;
                }
            }
            if (item is not null) events.Add(item); else lines.Add(raw!);
            var endedHeartbeat = officiallyClosed && observation.Heartbeat;
            dirty |= (hitCount > 0 && !endedHeartbeat) || context || observation.SkillStart || start || end;
            if (end)
            {
                if (officialEnd)
                {
                    officialActive = false;
                    officialStartAbsMs = null;
                    officialGameId = "";
                    closed = officiallyClosed = forceReparse = true;
                }
                else if (!officialActive) closed = forceReparse = true;
            }
    }

    private void PreserveContext()
    {
        if (structuredInput) { PreserveEventContext(); return; }
        var boundary = lines.FindLastIndex(line => Boundary().IsMatch(line));
        var kept = lines.Skip(boundary + 1).Where(line => Context().IsMatch(line)).ToArray();
        lines.Clear();
        lines.AddRange(kept);
    }

    /// <summary>Read-only prefix context for bounded historical replay; an active official timer remains evidence.</summary>
    public IReadOnlyList<string> HistoryContext()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (structuredInput) throw new InvalidOperationException("Structured live input has event history context");
            var boundary = officialActive ? -1 : lines.FindLastIndex(line => Boundary().IsMatch(line));
            return lines.Skip(boundary + 1).Where(line => !Hit().IsMatch(line) && (officialActive || Context().IsMatch(line))).ToArray();
        }
    }

    private string? TimerLine(long? observerMs)
    {
        if (!officialActive || officialStartAbsMs is not { } start || hitCount <= 0 || closed) return null;
        long clock;
        if (observerMs is null && (options.AlignToDataWatermark || !liveClockEnabled))
        {
            if (lastClockMs is not { } latest) return null;
            clock = latest;
        }
        else if (observerMs is null)
        {
            clock = wallClockMs();
            if (lastClockMs is { } latest)
            {
                var delta = Math.Abs(clock - latest) % DayMs;
                if (Math.Min(delta, DayMs - delta) > 300_000) clock = latest;
            }
        }
        else clock = ((observerMs.Value % DayMs) + DayMs) % DayMs;
        var offset = dayOffsetMs;
        if (lastClockMs is { } previous && clock + 300_000 < previous) offset += DayMs;
        var absolute = Math.Max(clock + offset, lastHitAbsMs ?? long.MinValue);
        var elapsed = Math.Max(absolute - start, 1);
        var game = officialGameId.Length > 0 ? $" gameId={officialGameId}" : "";
        return string.Create(CultureInfo.InvariantCulture,
            $"[{TraceFields.MillisecondTimeText(absolute)}] LIVE_TIMER_TICK source=LIVE_TIMER_TICK{game} elapsedMs={elapsed}\n");
    }

    /// <summary>Serializes calculators before capturing input, and rejects completions from replaced generations.</summary>
    public async Task<EvidenceObject?> SnapshotAsync(long? observerMs = null, bool refresh = true,
        CancellationToken cancellationToken = default)
    {
        if (!refresh) return ReadSnapshot();
        CancellationTokenSource linked;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            linked = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token, cancellationToken);
        }
        using (linked)
        {
            await calculatorGate.WaitAsync(linked.Token).ConfigureAwait(false);
            try
            {
                string[]? captured = null;
                string? timer;
                EventRequest? eventRequest;
                long requestRevision, requestGeneration;
                lock (gate)
                {
                    linked.Token.ThrowIfCancellationRequested();
                    if (failedRevision == revision) return Copy(snapshot);
                    if (options.AlignToDataWatermark && observerMs is null && !dirty && !fromExplicitClock) return Copy(snapshot);
                    timer = structuredInput ? null : TimerLine(observerMs);
                    var observer = structuredInput ? ObserverClock(observerMs) : null;
                    if (!dirty && timer is null && observer is null) return Copy(snapshot);
                    if (options.MinReparseIntervalMs > 0 && !forceReparse
                        && !(options.AlignToDataWatermark && observerMs is null && fromExplicitClock)
                        && snapshot is not null && lastParseMs is { } parsed
                        && monotonicMs() - parsed < options.MinReparseIntervalMs) return Copy(snapshot);
                    eventRequest = structuredInput ? CaptureEvents(observer) : null;
                    if (!structuredInput) captured = lines.ToArray();
                    requestRevision = revision;
                    requestGeneration = generation;
                    calculations++;
                }
                EvidenceObject? result = null;
                Exception? failure = null;
                try
                {
                    result = await Task.Run(() => eventRequest is null ? Calculate(captured!, timer, requestGeneration, linked.Token)
                        : CalculateEvents(eventRequest, linked.Token), linked.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (linked.IsCancellationRequested) { throw; }
                catch (Exception error) { failure = error; }
                lock (gate)
                {
                    linked.Token.ThrowIfCancellationRequested();
                    if (disposed || generation != requestGeneration)
                    {
                        discardedResults++;
                        return Copy(snapshot);
                    }
                    snapshot = Copy(result);
                    fromExplicitClock = failure is null && observerMs is not null;
                    lastError = failure?.ToString();
                    failedRevision = failure is null ? null : requestRevision;
                    if (failure is null) sourceRevision = requestRevision;
                    if (revision == requestRevision) dirty = forceReparse = false;
                    lastParseMs = monotonicMs();
                    return Copy(snapshot);
                }
            }
            finally { calculatorGate.Release(); }
        }
    }

    private EvidenceObject? Calculate(string[] captured, string? timer, long requestGeneration, CancellationToken token)
    {
        if (calculator is null || calculatorGeneration != requestGeneration)
        {
            calculator = calculatorFactory();
            calculatorGeneration = requestGeneration;
        }
        try { return calculator(captured, timer, options.Summary, token); }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
        catch
        {
            // Retry with an independent stream, matching the reference facade's full replay fallback.
            calculator = null;
            var fallback = calculatorFactory();
            return fallback(captured, timer, options.Summary, token);
        }
    }

    private static bool Has(string line, string name) => Regex.IsMatch(line, @"\b" + name + @"\b");
    private static EvidenceObject? Copy(EvidenceObject? value) => value is null ? null : (EvidenceObject)EvidenceJson.Clone(value);

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            generation++;
            snapshot = null;
            lines.Clear();
            events.Clear();
        }
        // Pending calculations observe cancellation; callers do not wait for CPU work during UI shutdown.
        lifetime.Cancel();
        lifetime.Dispose();
    }
}
