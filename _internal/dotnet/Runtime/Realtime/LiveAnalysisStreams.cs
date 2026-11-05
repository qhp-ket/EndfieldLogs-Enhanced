using System.Threading.Channels;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Runtime.Realtime;

/// <summary>A bounded observer mailbox: one ordered clear and the latest result. Reading transfers ownership.</summary>
public sealed class LiveAnalysisSubscription : IDisposable
{
    private readonly object gate = new();
    private readonly Channel<bool> changed = Channel.CreateBounded<bool>(new BoundedChannelOptions(1)
        { FullMode = BoundedChannelFullMode.DropOldest });
    private readonly List<LiveSnapshotFrame> pending = [];
    private readonly Action<LiveAnalysisSubscription> remove;
    private bool disposed;
    private string? streamId;
    private long sequence = -1;
    public bool Summary { get; }

    internal LiveAnalysisSubscription(bool summary, Action<LiveAnalysisSubscription> remove)
    { Summary = summary; this.remove = remove; }

    internal void Offer(LiveSnapshotFrame frame)
    {
        lock (gate)
        {
            if (disposed) return;
            if (streamId == frame.StreamId && frame.Sequence <= sequence) return;
            streamId = frame.StreamId; sequence = frame.Sequence;
            if (frame.Snapshot is null) { pending.Clear(); pending.Add(frame); }
            else if (pending.Count > 0 && pending[^1].Snapshot is not null) pending[^1] = frame;
            else pending.Add(frame);
            changed.Writer.TryWrite(true);
        }
    }

    public bool TryRead(out LiveSnapshotFrame? frame)
    {
        lock (gate)
        {
            frame = null;
            if (pending.Count == 0) return false;
            var next = pending[0]; pending.RemoveAt(0);
            frame = next with { Snapshot = next.Snapshot is null ? null : (EvidenceObject)EvidenceJson.Clone(next.Snapshot) };
            return true;
        }
    }

    public async ValueTask<LiveSnapshotFrame?> ReadAsync(CancellationToken cancellationToken = default)
    {
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (TryRead(out var frame)) return frame;
            if (!await changed.Reader.WaitToReadAsync(cancellationToken).ConfigureAwait(false)) return null;
            while (changed.Reader.TryRead(out _)) { }
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true; pending.Clear(); changed.Writer.TryComplete();
        }
        remove(this);
    }

    internal void Complete()
    {
        lock (gate) { disposed = true; changed.Writer.TryComplete(); }
    }
}

/// <summary>Two independent calculators share ordered input; subscriptions determine which stream does work.</summary>
public sealed class LiveAnalysisStreams : IDisposable
{
    private sealed record Stream(LiveBattleSession Session, LiveSnapshotPublisher Publisher, Channel<bool> Demand);
    private readonly object gate = new();
    private readonly Stream summary, full;
    private readonly HashSet<LiveAnalysisSubscription> subscribers = [];
    private bool running, disposed;

    public LiveAnalysisStreams(Func<bool, LiveBattleSession> createSession, TimeSpan? summaryInterval = null,
        TimeSpan? fullInterval = null)
    {
        Stream Create(bool compact, TimeSpan interval)
        {
            var session = createSession(compact);
            return new(session, new(session, interval), Channel.CreateBounded<bool>(new BoundedChannelOptions(1)
                { FullMode = BoundedChannelFullMode.DropOldest }));
        }
        summary = Create(true, summaryInterval ?? TimeSpan.FromMilliseconds(100));
        try { full = Create(false, fullInterval ?? TimeSpan.FromSeconds(1)); }
        catch { summary.Publisher.Dispose(); throw; }
    }

    public static LiveAnalysisStreams Create(ResourceFiles files, DateOnly referenceDate, TimeZoneInfo? timeZone = null)
    {
        LiveBattleEngine Engine()
        {
            // Resource loading and parser construction occur on the calculator task, only when demanded.
            var resources = BattleIngestionResources.Load(files);
            var analysis = BattleReportAnalysis.Load(files, timeZone);
            return new(resources, analysis, referenceDate, timeZone);
        }
        return new(compact => new LiveBattleSession(() => Engine().Snapshot, new(Summary: compact),
            eventCalculatorFactory: () => Engine().SnapshotEvents));
    }

    private Stream Select(bool compact) => compact ? summary : full;
    public LiveSessionState State(bool compact = true) => Select(compact).Session.State;
    public LiveSnapshotFrame Current(bool compact = true) => Select(compact).Publisher.Current;

    public LiveAnalysisSubscription Subscribe(bool compact = true)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var stream = Select(compact);
            LiveAnalysisSubscription subscription = new(compact, Remove);
            subscribers.Add(subscription);
            subscription.Offer(stream.Publisher.Current);
            stream.Publisher.RequestCurrent(); stream.Demand.Writer.TryWrite(true);
            return subscription;
        }
    }

    private void Remove(LiveAnalysisSubscription subscription)
    {
        lock (gate)
        {
            subscribers.Remove(subscription);
            Select(subscription.Summary).Demand.Writer.TryWrite(true);
        }
    }

    public void FeedLine(string line)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            summary.Publisher.FeedLine(line); full.Publisher.FeedLine(line);
        }
    }

    public void FeedEvent(TraceEvent item)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            item = LiveBattleSession.CaptureEvent(item);
            summary.Publisher.FeedEvent(item); full.Publisher.FeedEvent(item);
        }
    }

    public void FeedEvents(IReadOnlyList<TraceEvent> items)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var captured = items.Select(LiveBattleSession.CaptureEvent).ToArray();
            summary.Publisher.FeedEvents(captured); full.Publisher.FeedEvents(captured);
        }
    }

    public void Reset(bool newStream = false)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            summary.Publisher.Reset(newStream); full.Publisher.Reset(newStream);
        }
    }

    private bool Required(bool compact) { lock (gate) return subscribers.Any(subscriber => subscriber.Summary == compact); }

    private void Distribute(Stream stream, LiveSnapshotFrame? frame, bool compact)
    {
        if (frame is null) return;
        lock (gate)
        {
            if (!stream.Publisher.IsCurrent(frame)) return;
            foreach (var subscription in subscribers.Where(subscriber => subscriber.Summary == compact)) subscription.Offer(frame);
        }
    }

    public async Task RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (running) throw new InvalidOperationException("Analysis streams can only run once");
            running = true;
        }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        async Task Pump(Stream stream, bool compact)
        {
            try
            {
                while (true)
                {
                    while (!Required(compact))
                    {
                        await stream.Session.ReleaseCalculatorAsync(lifetime.Token).ConfigureAwait(false);
                        await stream.Demand.Reader.ReadAsync(lifetime.Token).ConfigureAwait(false);
                    }
                    // Demand changes must wake this wait too, to release an idle calculator after the last observer leaves.
                    using var wake = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                    var pending = stream.Publisher.WaitForPendingAsync(wake.Token);
                    var demand = stream.Demand.Reader.ReadAsync(wake.Token).AsTask();
                    await Task.WhenAny(pending, demand).ConfigureAwait(false);
                    wake.Cancel();
                    try { await Task.WhenAll(pending, demand).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (!lifetime.IsCancellationRequested) { }
                    lifetime.Token.ThrowIfCancellationRequested();
                    if (Required(compact))
                        Distribute(stream, await stream.Publisher.PublishPendingAsync(lifetime.Token).ConfigureAwait(false), compact);
                }
            }
            catch { lifetime.Cancel(); throw; }
        }
        await Task.WhenAll(Pump(summary, true), Pump(full, false)).ConfigureAwait(false);
    }

    public async Task FlushPendingAsync(CancellationToken cancellationToken = default)
    {
        foreach (var (stream, compact) in new[] { (summary, true), (full, false) })
            if (Required(compact)) Distribute(stream, await stream.Publisher.PublishPendingAsync(cancellationToken).ConfigureAwait(false), compact);
    }

    public void Dispose()
    {
        lock (gate)
        {
            if (disposed) return;
            disposed = true;
            foreach (var subscription in subscribers) subscription.Complete();
            subscribers.Clear();
            summary.Publisher.Dispose(); full.Publisher.Dispose();
            summary.Demand.Writer.TryComplete(); full.Demand.Writer.TryComplete();
        }
    }
}
