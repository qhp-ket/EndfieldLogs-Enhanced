using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Realtime;

/// <summary>The caller supplies only the suffix after its acknowledged watermark, within one generation.</summary>
public sealed record LiveEventBatch(long Generation, long Revision, int AfterEvidenceIndex, IReadOnlyList<TraceEvent> Events);
public sealed record LiveObserverClock(long TimestampMs, BigInteger ElapsedMs);

public sealed partial class LiveBattleEngine
{
    private long? sourceGeneration;
    private long eventRevision = -1, cachedEventRevision = -1;
    private int consumedEvents;
    private LiveObserverClock? cachedObserver;

    private void ResetEvents()
    {
        sourceGeneration = null;
        eventRevision = cachedEventRevision = -1;
        consumedEvents = 0;
        cachedObserver = null;
    }

    /// <summary>Direct event ingestion. No accumulated trace string, prefix scan or legacy rendering is involved.</summary>
    public EvidenceObject? SnapshotEvents(LiveEventBatch batch, LiveObserverClock? observer = null, bool summary = false,
        CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var sameGeneration = sourceGeneration == batch.Generation;
            if (sourceGeneration is { } previous && batch.Generation < previous)
                throw new InvalidOperationException("Stale live event generation");
            if (batch.AfterEvidenceIndex != (sameGeneration ? consumedEvents : 0))
                throw new InvalidOperationException("Live event batch does not begin at the consumed watermark");
            if (sameGeneration && (batch.Revision < eventRevision || batch.Events.Count > 0 && batch.Revision <= eventRevision))
                throw new InvalidOperationException("Stale live event revision");
            _ = checked(batch.AfterEvidenceIndex + batch.Events.Count);
            if (!sameGeneration)
            {
                Restart(replay: false);
                sourceGeneration = batch.Generation;
            }
            stream ??= new(resources);
            try
            {
                foreach (var item in batch.Events)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    // Preserve the event's Unix clock. Report coordinates retain the legacy local-day/modulo rule.
                    var local = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs), timeZone ?? TimeZoneInfo.Local);
                    var stamp = local.TimeOfDay.Ticks / TimeSpan.TicksPerMillisecond;
                    if (stream.TimestampClockOrigin is { } origin)
                    {
                        var relative = (stamp - origin) % 86_400_000;
                        stamp = origin + (relative < 0 ? relative + 86_400_000 : relative);
                    }
                    stream.Accept(++consumedEvents, item with { CapturedAtMs = stamp });
                    ingestedLines++;
                }
                eventRevision = batch.Revision;
                if (hasCache && cachedEventRevision == eventRevision && cachedSummary == summary)
                {
                    if (cachedObserver == observer)
                    {
                        cachedReads++;
                        return CopySnapshot();
                    }
                    if (summary && cached is not null && observer is not null && LiveClockProjection.TryAdvance(cached,
                        stream.Timers.OfficialStartMs, LiveClockProjection.SemanticTimes(stream), referenceDate, observer.ElapsedMs, timeZone) is { } clocked)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        cached = clocked; cachedObserver = observer; clockProjections++;
                        return CopySnapshot();
                    }
                }
                var input = BattleReportInput.CaptureLive(stream, hitProjections, buffProjections, referenceDate, summary);
                if (observer is not null)
                {
                    var lastContext = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds(observer.TimestampMs), timeZone ?? TimeZoneInfo.Local)
                        .TimeOfDay.Ticks / TimeSpan.TicksPerMillisecond;
                    if (stream.TimestampClockOrigin is { } origin)
                    {
                        var relative = (lastContext - origin) % 86_400_000;
                        lastContext = origin + (relative < 0 ? relative + 86_400_000 : relative);
                    }
                    input = input with { Metadata = input.Metadata! with { LastContextMs = lastContext } };
                    if (observer.ElapsedMs > 0) input = input with { Timing = input.Timing with
                    {
                        LiveElapsedMs = observer.ElapsedMs, GameEndMs = lastContext,
                        GameElapsedMs = observer.ElapsedMs, GameWindowElapsedMs = observer.ElapsedMs,
                    } };
                }
                reportBuilds++;
                var result = analysis.BuildOwnedSnapshot(input, "", summary, cancellationToken, allocation);
                cancellationToken.ThrowIfCancellationRequested();
                cached = result; cachedEventRevision = eventRevision; cachedObserver = observer;
                cachedSummary = summary; hasCache = true;
                return CopySnapshot();
            }
            catch
            {
                // The caller must replay from zero after a partly consumed or failed batch, never continue uncertain state.
                Restart(replay: true);
                throw;
            }
        }
    }

    private EvidenceObject? CopySnapshot() => cached is null ? null : (EvidenceObject)BuffEvidence.Clone(cached);
}
