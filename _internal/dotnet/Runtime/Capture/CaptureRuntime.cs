using System.Runtime.ExceptionServices;
using System.Threading.Channels;
using EndfieldLogs.Capture;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Capture;

public sealed record CaptureRuntimeSnapshot(bool Running, CaptureFlowSnapshot Flow, long PacketsSeen, long QueueDrops,
    CaptureStatistics Statistics, string? Error, string? ErrorType = null, string? ErrorTask = null);

/// <summary>Single-use capture task. Native callbacks enqueue; business events, flow switches and shutdown have one owner.</summary>
public sealed class CaptureRuntime
{
    private abstract record Input;
    private sealed record Packet(CapturedPacket Value) : Input;
    private sealed record Observation(GameProcessObservation Value) : Input;
    private sealed record Rotation(TaskCompletionSource<CaptureRecordingPaths> Completion) : Input;
    private sealed record RecordingChange(bool Active, TaskCompletionSource<CaptureRecordingPaths?> Completion) : Input;
    private readonly Channel<Input> queue;
    private readonly CaptureFlowSession flow;
    private readonly TraceRecording recording;
    private readonly Func<GameProcessObservation> observeGame;
    private readonly Func<Action<CapturedPacket>, Action<string, Exception?>, ICaptureDevices> openCapture;
    private readonly Action<CaptureRuntimeSnapshot>? onStatus;
    private readonly Action<string, Exception?>? onDiagnostic;
    private readonly Func<CaptureRecordingPaths>? rotateRecording;
    private readonly Func<bool, CaptureRecordingPaths?>? setRecording;
    private readonly TimeSpan monitorInterval, statisticsInterval;
    private readonly object gate = new();
    private CaptureStatistics statistics = new(0, 0, 0);
    private CaptureFlowSnapshot flowState;
    private long seen, dropped;
    private bool started, running;
    private Exception? failure;

    public CaptureRuntime(CaptureFlowSession flow, TraceRecording recording, Func<GameProcessObservation> observeGame,
        Func<Action<CapturedPacket>, Action<string, Exception?>, ICaptureDevices> openCapture,
        Action<CaptureRuntimeSnapshot>? onStatus = null, int queueCapacity = 20_000,
        TimeSpan? monitorInterval = null, TimeSpan? statisticsInterval = null, Action<string, Exception?>? onDiagnostic = null,
        Func<CaptureRecordingPaths>? rotateRecording = null, Func<bool, CaptureRecordingPaths?>? setRecording = null)
    {
        this.flow = flow; this.recording = recording; this.observeGame = observeGame; this.openCapture = openCapture;
        this.onStatus = onStatus; this.monitorInterval = monitorInterval ?? TimeSpan.FromMilliseconds(500);
        this.onDiagnostic = onDiagnostic;
        this.rotateRecording = rotateRecording;
        this.setRecording = setRecording;
        this.statisticsInterval = statisticsInterval ?? TimeSpan.FromSeconds(5); flowState = flow.Snapshot;
        queue = Channel.CreateBounded<Input>(new BoundedChannelOptions(queueCapacity) { FullMode = BoundedChannelFullMode.Wait, SingleReader = true });
    }

    public CaptureRuntimeSnapshot Snapshot
    {
        get { lock (gate) return new(running, flowState, Interlocked.Read(ref seen), Interlocked.Read(ref dropped), statistics,
            failure?.Message, failure?.GetType().Name, failure is null ? null : "capture"); }
    }

    public async Task<CaptureRecordingPaths> RotateRecordingAsync(CancellationToken cancellationToken = default)
    {
        lock (gate) if (!running) throw new InvalidOperationException("抓包服务尚未运行");
        TaskCompletionSource<CaptureRecordingPaths> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await queue.Writer.WriteAsync(new Rotation(completion), cancellationToken).ConfigureAwait(false);
        return await completion.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
    }
    public async Task<CaptureRecordingPaths?> SetRecordingAsync(bool active, CancellationToken cancellationToken = default)
    {
        lock (gate) if (!running) throw new InvalidOperationException("抓包服务尚未运行");
        TaskCompletionSource<CaptureRecordingPaths?> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await queue.Writer.WriteAsync(new RecordingChange(active, completion), cancellationToken).ConfigureAwait(false);
        return await completion.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate) { if (started) throw new InvalidOperationException("A capture runtime can only run once"); started = true; }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        ICaptureDevices? devices = null;
        Task[] tasks = [];
        var callbacksClosed = false;
        void Fail(Exception error)
        {
            lock (gate)
            {
                if (callbacksClosed) return;
                failure ??= error; lifetime.Cancel();
            }
        }
        void Enqueue(CapturedPacket packet)
        {
            if (lifetime.IsCancellationRequested) return;
            Interlocked.Increment(ref seen);
            if (!queue.Writer.TryWrite(new Packet(packet with { Payload = packet.Payload.ToArray() }))) Interlocked.Increment(ref dropped);
        }
        async Task Guard(Func<Task> work)
        {
            try { await work().ConfigureAwait(false); }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            catch (Exception error) { Fail(error); }
        }
        void PublishStatus(bool force = true)
        {
            lock (gate) if (!force && flowState.State == flow.State && flowState.SessionId == flow.SessionId) return;
            lock (gate) flowState = flow.Snapshot;
            onStatus?.Invoke(Snapshot);
        }
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            // All fallible recording/resource setup occurs before opening native capture.
            flow.Initialize(observeGame());
            devices = openCapture(Enqueue, (message, error) =>
            {
                // A single adapter may fail to open while others work. Worker failures are authoritative in Statistics().
                try { onDiagnostic?.Invoke(message, error); } catch (Exception observerError) { Fail(observerError); }
            });
            devices.Start();
            lock (gate) running = true;
            PublishStatus();
            tasks = [
                Guard(async () =>
                {
                    await foreach (var input in queue.Reader.ReadAllAsync(lifetime.Token).ConfigureAwait(false))
                    {
                        lifetime.Token.ThrowIfCancellationRequested();
                        if (input is Packet packet) flow.Process(packet.Value);
                        else if (input is Observation observation) flow.Observe(observation.Value);
                        else if (input is Rotation rotation)
                        {
                            try { rotation.Completion.TrySetResult(rotateRecording?.Invoke()
                                ?? throw new InvalidOperationException("当前服务不支持连续记录")); }
                            catch (InvalidOperationException error) { rotation.Completion.TrySetException(error); }
                            catch (Exception error) { rotation.Completion.TrySetException(error); throw; }
                        }
                        else if (input is RecordingChange change)
                        {
                            try
                            {
                                if (setRecording is null) throw new InvalidOperationException("当前服务不支持记录启停");
                                change.Completion.TrySetResult(setRecording(change.Active));
                            }
                            catch (InvalidOperationException error) { change.Completion.TrySetException(error); }
                            catch (Exception error) { change.Completion.TrySetException(error); throw; }
                        }
                        PublishStatus(force: input is Observation or Rotation or RecordingChange);
                        await Task.Yield();
                    }
                }),
                Guard(async () =>
                {
                    while (true)
                    {
                        await Task.Delay(this.monitorInterval, lifetime.Token).ConfigureAwait(false);
                        await queue.Writer.WriteAsync(new Observation(observeGame()), lifetime.Token).ConfigureAwait(false);
                    }
                }),
                Guard(async () =>
                {
                    while (true)
                    {
                        await Task.Delay(this.statisticsInterval, lifetime.Token).ConfigureAwait(false);
                        var stats = devices.Statistics(); lock (gate) statistics = stats;
                    }
                }),
            ];
            try { await Task.Delay(Timeout.InfiniteTimeSpan, lifetime.Token).ConfigureAwait(false); }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception error) { Fail(error); }
        finally
        {
            lifetime.Cancel(); queue.Writer.TryComplete();
            await Task.WhenAll(tasks).ConfigureAwait(false);
            while (queue.Reader.TryRead(out var pending))
                if (pending is Rotation rotation) rotation.Completion.TrySetException(new InvalidOperationException("抓包服务已停止"));
                else if (pending is RecordingChange change) change.Completion.TrySetException(new InvalidOperationException("抓包服务已停止"));
            try { devices?.Dispose(); } catch (Exception error) { lock (gate) failure ??= error; }
            try { flow.Reset(); } catch (Exception error) { lock (gate) failure ??= error; }
            try { recording.Dispose(); } catch (Exception error) { lock (gate) failure ??= error; }
            lock (gate) { running = false; flowState = flow.Snapshot; callbacksClosed = true; }
            try { onStatus?.Invoke(Snapshot); } catch (Exception error) { lock (gate) failure ??= error; }
        }
        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
    }
}
