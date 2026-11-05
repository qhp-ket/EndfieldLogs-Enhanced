using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Realtime;

public sealed record LiveEngineDiagnostics(long Generation, long IngestedLines, long TraceReplays, long ReportBuilds, long CachedReads,
    LiveAllocationDiagnostics? Allocation = null, long ClockProjections = 0, long? SourceGeneration = null,
    long EventRevision = 0, int ConsumedEvents = 0, long ProjectedHits = 0, long ReusedHitProjections = 0,
    long ProjectedBuffs = 0, long ReusedBuffProjections = 0, long BuffProjectionStructureResets = 0);

/// <summary>Serialized live ingestion and allocation owner. Changed prefixes replay independently of published snapshots.</summary>
public sealed partial class LiveBattleEngine(BattleIngestionResources resources, BattleReportAnalysis analysis, DateOnly referenceDate, TimeZoneInfo? timeZone = null)
{
    private readonly object gate = new();
    private BattleIngestionStream? stream;
    private LiveAllocationCache allocation = new();
    private LiveHitProjectionCache hitProjections = new();
    private LiveBuffProjectionCache buffProjections = new();
    private string[] accepted = [];
    private EvidenceObject? cached;
    private string? cachedText, cachedTimer;
    private bool cachedSummary, hasCache;
    private long generation, ingestedLines, replays, reportBuilds, cachedReads, clockProjections;

    public static LiveBattleEngine Load(ResourceFiles files, DateOnly referenceDate, TimeZoneInfo? timeZone = null) =>
        new(BattleIngestionResources.Load(files), BattleReportAnalysis.Load(files, timeZone), referenceDate, timeZone);

    public LiveEngineDiagnostics Diagnostics
    {
        get { lock (gate) return new(generation, ingestedLines, replays, reportBuilds, cachedReads, allocation.Diagnostics, clockProjections,
            sourceGeneration, eventRevision, consumedEvents, hitProjections.ProjectedHits, hitProjections.ReusedHits,
            buffProjections.ProjectedRecords, buffProjections.ReusedRecords, buffProjections.StructureResets); }
    }

    public void Reset()
    {
        lock (gate) Restart(replay: false);
    }

    private void Restart(bool replay)
    {
        stream = null;
        allocation = new();
        hitProjections = new();
        buffProjections = new();
        accepted = [];
        cached = null;
        cachedText = cachedTimer = null;
        hasCache = false;
        ResetEvents();
        generation++;
        if (replay) replays++;
    }

    /// <param name="lines">Cumulative original chunks, retaining their original separators.</param>
    /// <param name="timerLine">Ephemeral observer clock; never fed back into persistent evidence.</param>
    public EvidenceObject? Snapshot(IReadOnlyList<string> lines, string? timerLine = null, bool summary = false,
        CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (sourceGeneration is not null) Restart(replay: false);
            var text = string.Concat(lines);
            if (hasCache && cachedText == text && cachedTimer == timerLine && cachedSummary == summary)
            {
                cachedReads++;
                return cached is null ? null : (EvidenceObject)BuffEvidence.Clone(cached);
            }
            if (hasCache && cachedText == text && cachedSummary && summary && cached is not null && stream is not null
                && LiveClockProjection.TryAdvance(cached, stream.Timers.OfficialStartMs, LiveClockProjection.SemanticTimes(stream),
                    referenceDate, timerLine, timeZone) is { } clocked)
            {
                cancellationToken.ThrowIfCancellationRequested();
                cached = clocked; cachedTimer = timerLine; clockProjections++;
                return (EvidenceObject)BuffEvidence.Clone(clocked);
            }
            var normalized = PythonTextLines.Split(text).ToArray();
            if (normalized.Length < accepted.Length || !normalized.Take(accepted.Length).SequenceEqual(accepted, StringComparer.Ordinal))
                Restart(replay: true);
            stream ??= new(resources);
            try
            {
                for (var index = accepted.Length; index < normalized.Length; index++)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    stream.Accept(index + 1, normalized[index]);
                    ingestedLines++;
                }
                accepted = normalized;
                var input = BattleReportInput.CaptureLive(stream, hitProjections, buffProjections, referenceDate, summary);
                if (!string.IsNullOrEmpty(timerLine))
                {
                    var elapsed = TraceFields.OptionalInteger(TraceFields.Extract(timerLine).GetValueOrDefault("elapsedMs")) ?? BigInteger.Zero;
                    BigInteger? stamp = TraceFields.PrefixedTimestampMs(timerLine);
                    if (stamp is { } clock && stream.TimestampClockOrigin is { } origin)
                    {
                        var relative = (clock - origin) % 86_400_000;
                        stamp = origin + (relative < 0 ? relative + 86_400_000 : relative);
                        var observed = new Dictionary<int, long>(input.Timing.ObservedTimes ?? new Dictionary<int, long>())
                            { [normalized.Length + 1] = checked((long)stamp.Value) };
                        input = input with { Timing = input.Timing with { ObservedTimes = observed },
                            Metadata = input.Metadata! with { LastContextMs = stamp } };
                    }
                    if (elapsed > 0) input = input with { Timing = input.Timing with { LiveElapsedMs = elapsed,
                        GameEndMs = stamp, GameElapsedMs = elapsed, GameWindowElapsedMs = elapsed } };
                }
                reportBuilds++;
                var result = analysis.BuildOwnedSnapshot(input, text + timerLine, summary, cancellationToken, allocation);
                cancellationToken.ThrowIfCancellationRequested();
                cached = result;
                cachedText = text;
                cachedTimer = timerLine;
                cachedSummary = summary;
                hasCache = true;
                return result is null ? null : (EvidenceObject)BuffEvidence.Clone(result);
            }
            catch
            {
                // Ingestion may already have consumed part of a canceled/failed batch. Recreate it on the next request.
                Restart(replay: true);
                throw;
            }
        }
    }
}
