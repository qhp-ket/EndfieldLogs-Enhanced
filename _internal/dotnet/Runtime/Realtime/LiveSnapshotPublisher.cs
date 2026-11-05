using System.Globalization;
using System.Threading.Channels;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Realtime;

public sealed record LiveSnapshotFrame(string Type, string StreamId, long Sequence, long SourceGeneration,
    long SourceRevision, EvidenceObject? Snapshot)
{
    public int SchemaVersion => 1;

    public EvidenceObject ToEvidence() => new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
    {
        ["type"] = new EvidenceText(Type), ["schema_version"] = new EvidenceInteger(SchemaVersion),
        ["stream_id"] = new EvidenceText(StreamId), ["sequence"] = new EvidenceInteger(Sequence),
        ["source_generation"] = new EvidenceInteger(SourceGeneration), ["source_revision"] = new EvidenceInteger(SourceRevision),
        ["snapshot"] = Snapshot is null ? EvidenceNull.Value : EvidenceJson.Clone(Snapshot),
    });
}

/// <summary>Completion-driven publication with an ordered clear frame and one calculator. Owns its session.</summary>
public sealed class LiveSnapshotPublisher : IDisposable
{
    private readonly object gate = new();
    private readonly LiveBattleSession session;
    private readonly TimeProvider time;
    private readonly TimeSpan minimumInterval;
    private readonly SemaphoreSlim publicationGate = new(1, 1);
    private readonly CancellationTokenSource lifetime = new();
    private readonly Channel<bool> changed = Channel.CreateBounded<bool>(new BoundedChannelOptions(1)
        { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = false });
    private LiveSnapshotFrame message;
    private bool clearPending = true, pending, disposed;
    private long generation, revisionBase;
    private long? lastStarted;
    private double lastAnalysisMs;

    public LiveSnapshotPublisher(LiveBattleSession session, TimeSpan? minimumInterval = null,
        TimeProvider? timeProvider = null)
    {
        this.session = session;
        this.time = timeProvider ?? TimeProvider.System;
        this.minimumInterval = minimumInterval ?? TimeSpan.FromMilliseconds(100);
        message = new(session.Summary ? "analysis_summary" : "analysis_snapshot", Guid.NewGuid().ToString(), 0, 0, 0, null);
        revisionBase = session.State.Revision;
    }

    public double LastAnalysisMs { get { lock (gate) return lastAnalysisMs; } }
    public LiveSessionState SessionState => session.State;
    public LiveSnapshotFrame Current { get { lock (gate) return Copy(message); } }
    public bool IsCurrent(LiveSnapshotFrame frame) { lock (gate) return frame.StreamId == message.StreamId && frame.Sequence == message.Sequence; }

    public void FeedLine(string line)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (Regex.IsMatch(line, @"\bGAME_TIMER_RESET\b")) ResetCore(false);
            else
            {
                session.FeedLine(line);
                pending = true;
            }
            changed.Writer.TryWrite(true);
        }
    }

    public void FeedEvent(TraceEvent item)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (item.Type == "battle_timer" && item.Data.Get("phase") is EvidenceText { Value: "reset" }) ResetCore(false);
            else { session.FeedEvent(item); pending = true; }
            changed.Writer.TryWrite(true);
        }
    }

    /// <summary>Publish only after a complete business group has entered the session.</summary>
    public void FeedEvents(IReadOnlyList<TraceEvent> items)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var start = 0;
            for (var index = 0; index < items.Count; index++)
            {
                var item = items[index];
                if (item.Type != "battle_timer" || item.Data.Get("phase") is not EvidenceText { Value: "reset" }) continue;
                if (index > start) session.FeedEvents(Segment(start, index));
                ResetCore(false); start = index + 1;
            }
            if (start < items.Count) { session.FeedEvents(Segment(start, items.Count)); pending = true; }
            if (items.Count > 0) changed.Writer.TryWrite(true);
        }

        IEnumerable<TraceEvent> Segment(int start, int end)
        { for (var index = start; index < end; index++) yield return items[index]; }
    }

    public void Reset(bool newStream = false)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            ResetCore(newStream);
            changed.Writer.TryWrite(true);
        }
    }

    private void ResetCore(bool newStream)
    {
        session.Reset();
        revisionBase = session.State.Revision;
        generation++;
        pending = false;
        clearPending = true;
        message = new(message.Type, newStream ? Guid.NewGuid().ToString() : message.StreamId,
            newStream ? 0 : message.Sequence + 1, generation, 0, null);
    }

    public void RequestCurrent()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            pending = true;
            changed.Writer.TryWrite(true);
        }
    }

    public async Task WaitForPendingAsync(CancellationToken cancellationToken = default)
    {
        using var linked = Link(cancellationToken);
        while (true)
        {
            lock (gate)
            {
                linked.Token.ThrowIfCancellationRequested();
                if (clearPending || pending) return;
            }
            if (!await changed.Reader.WaitToReadAsync(linked.Token).ConfigureAwait(false)) return;
            while (changed.Reader.TryRead(out _)) { }
        }
    }

    public async Task<LiveSnapshotFrame?> PublishPendingAsync(CancellationToken cancellationToken = default)
    {
        using var linked = Link(cancellationToken);
        await publicationGate.WaitAsync(linked.Token).ConfigureAwait(false);
        long capturedGeneration = -1;
        try
        {
            TimeSpan delay;
            lock (gate)
            {
                linked.Token.ThrowIfCancellationRequested();
                if (clearPending) { clearPending = false; return Copy(message); }
                if (!pending) return null;
                delay = lastStarted is { } started ? minimumInterval - time.GetElapsedTime(started) : TimeSpan.Zero;
            }
            if (delay > TimeSpan.Zero) await Task.Delay(delay, time, linked.Token).ConfigureAwait(false);
            long startedAt;
            lock (gate)
            {
                linked.Token.ThrowIfCancellationRequested();
                if (clearPending) { clearPending = false; return Copy(message); }
                pending = false;
                capturedGeneration = generation;
                lastStarted = startedAt = time.GetTimestamp();
            }
            var result = await session.SnapshotAsync(cancellationToken: linked.Token).ConfigureAwait(false);
            var snapshot = result is null ? null : (EvidenceObject)TransportCopy(result);
            var source = session.State.SourceRevision;
            lock (gate)
            {
                linked.Token.ThrowIfCancellationRequested();
                if (capturedGeneration != generation) return null;
                lastAnalysisMs = time.GetElapsedTime(startedAt).TotalMilliseconds;
                source = Math.Max(source - revisionBase, 0);
                if ((snapshot is null && message.Snapshot is null)
                    || (snapshot is not null && message.Snapshot is not null
                        && source == message.SourceRevision && EvidenceJson.PythonEquals(snapshot, message.Snapshot))) return null;
                message = new(message.Type, message.StreamId, message.Sequence + 1, generation, source, snapshot);
                return Copy(message);
            }
        }
        catch (OperationCanceledException) when (linked.IsCancellationRequested)
        {
            lock (gate)
                if (!disposed && capturedGeneration == generation) { pending = true; changed.Writer.TryWrite(true); }
            throw;
        }
        finally { publicationGate.Release(); }
    }

    /// <summary>The sink chooses its own UI/transport dispatch. Awaiting delivery prevents an unbounded observer queue.</summary>
    public async Task RunAsync(Func<LiveSnapshotFrame, CancellationToken, ValueTask> deliver, CancellationToken cancellationToken = default)
    {
        using var linked = Link(cancellationToken);
        try
        {
            while (true)
            {
                await WaitForPendingAsync(linked.Token).ConfigureAwait(false);
                var frame = await PublishPendingAsync(linked.Token).ConfigureAwait(false);
                if (frame is not null) await deliver(frame, linked.Token).ConfigureAwait(false);
            }
        }
        catch (ObjectDisposedException) when (linked.IsCancellationRequested) { throw new OperationCanceledException(linked.Token); }
    }

    private CancellationTokenSource Link(CancellationToken token)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            return CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token, token);
        }
    }

    private static LiveSnapshotFrame Copy(LiveSnapshotFrame frame) => frame with
        { Snapshot = frame.Snapshot is null ? null : (EvidenceObject)EvidenceJson.Clone(frame.Snapshot) };

    public static EvidenceValue TransportCopy(EvidenceValue value) => value switch
    {
        EvidenceInteger number when number.Value < -9_007_199_254_740_991L || number.Value > 9_007_199_254_740_991L
            => new EvidenceText(number.Value.ToString(CultureInfo.InvariantCulture)),
        EvidenceReal number when !double.IsFinite(number.Value) => EvidenceNull.Value,
        EvidenceArray array => new EvidenceArray(array.Items.Select(TransportCopy).ToArray()),
        EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => TransportCopy(pair.Value), StringComparer.Ordinal)),
        _ => value,
    };

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            generation++;
            pending = clearPending = false;
            message = message with { Snapshot = null };
        }
        lifetime.Cancel();
        session.Dispose();
        changed.Writer.TryComplete();
        lifetime.Dispose();
    }
}
