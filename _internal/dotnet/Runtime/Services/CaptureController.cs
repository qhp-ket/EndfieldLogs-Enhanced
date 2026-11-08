using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Capture;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Runtime.Services;

public sealed record CaptureApplicationState(bool Running, bool Stopping, CaptureRuntimeSnapshot? Status, string? Error,
    string? TracePath, IReadOnlyList<VisionMember> Members, IReadOnlyList<LiveSnapshotFrame> Frames, IReadOnlyList<string> Diagnostics, bool ComboRequested = false, bool Recording = false);

/// <summary>Restartable application capture owner. Observers are demand-driven and workers never call a view.</summary>
public sealed class CaptureController(ResourceFiles resources, SettingsStore settings,
    Func<GameCaptureOptions, GameCaptureService>? factory = null) : IAsyncDisposable
{
    private readonly int owner = Environment.CurrentManagedThreadId;
    private readonly object gate = new();
    private readonly Queue<string> diagnostics = new();
    private readonly Dictionary<string, LiveAnalysisSubscription> subscriptions = new(StringComparer.Ordinal);
    private HashSet<string> required = new(StringComparer.Ordinal);
    private GameCaptureService? service;
    private Task run = Task.CompletedTask;
    private Task? shutdown;
    private CancellationTokenSource? cancellation;
    private long generation;
    private bool closed;
    private string? error, memberSession;
    private VisionMember[] members = [];
    public bool Running => !run.IsCompleted;
    private void Owner()
    { if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("采集服务只能由所属线程协调"); }
    public void SetStreams(IReadOnlySet<string> streams)
    {
        Owner(); if (closed) return;
        required = streams.Where(value => value is "analysis_summary" or "analysis_snapshot").ToHashSet(StringComparer.Ordinal);
        foreach (var key in subscriptions.Keys.Except(required).ToArray()) { subscriptions[key].Dispose(); subscriptions.Remove(key); }
    }
    public void Start()
    {
        Owner(); ObjectDisposedException.ThrowIf(closed, this); if (Running) return;
        DropSubscriptions(); cancellation?.Dispose(); cancellation = new();
        var request = ++generation; var options = settings.Current.Service.ToCaptureOptions() with { RecordingOnStart = true };
        lock (gate) { error = null; memberSession = null; members = []; diagnostics.Clear(); }
        // Construction is cheap; all fallible resource/native setup happens in GameCaptureService.RunAsync.
        var current = factory?.Invoke(options) ?? new(resources, options); service = current;
        run = ObserveAsync(current, request, cancellation.Token);
    }
    private async Task ObserveAsync(GameCaptureService current, long request, CancellationToken token)
    {
        try
        {
            await current.RunAsync(onEvent: value => OnEvent(request, value), diagnostic: (message, exception) =>
            {
                lock (gate) if (request == generation)
                {
                    if (diagnostics.Count == 64) diagnostics.Dequeue();
                    diagnostics.Enqueue(exception is null ? message : message + "：" + exception);
                }
            }, cancellationToken: token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception exception) { lock (gate) if (request == generation) error = exception.Message; }
    }
    private void OnEvent(long request, BattleLogEvent value)
    {
        if (value.EventType != "SC_SELF_SCENE_INFO") return;
        var payload = TraceData.Obj(TraceData.Value(value.Payload));
        var squad = TraceData.Rows(payload.Get("char_list")).Select(row =>
        {
            var slot = TraceData.Int(row.Get("squad_index"));
            return slot is { } index && index >= 0 && index < 4 ? new VisionMember((int)index, TraceData.Text(row.Get("templateid")), TraceData.Text(row.Get("display_name")), row.Get("is_leader") is EvidenceBoolean { Value: true }) : null;
        }).OfType<VisionMember>().GroupBy(member => member.Slot).Select(group => group.Last()).ToArray();
        lock (gate) if (request == generation) { memberSession = value.SessionId; members = squad; }
    }
    public CaptureApplicationState Poll()
    {
        Owner(); var current = service; List<LiveSnapshotFrame> frames = [];
        if (!closed && Running && current is not null)
            foreach (var type in required)
                if (!subscriptions.ContainsKey(type) && current.TrySubscribe(type == "analysis_summary") is { } next) subscriptions[type] = next;
        foreach (var subscription in subscriptions.Values)
            while (subscription.TryRead(out var value)) frames.Add(value!);
        var status = current?.Status; var path = current?.ActiveTracePath;
        lock (gate)
        {
            var messages = diagnostics.ToArray(); diagnostics.Clear();
            return new(Running, Running && cancellation?.IsCancellationRequested == true, status, error ?? status?.Error,
                path, status?.Flow.SessionId == memberSession ? members.ToArray() : [], frames, messages, current?.HasComboSubscribers == true, Running && current?.Recording == true);
        }
    }
    public bool IsWriting(string path) => service?.IsWriting(path) == true;
    public Task<CaptureRecordingPaths> RotateRecordingAsync()
    {
        Owner(); ObjectDisposedException.ThrowIf(closed, this);
        return service?.RotateRecordingAsync(cancellation?.Token ?? default)
            ?? throw new InvalidOperationException("抓包服务尚未运行");
    }
    public Task<CaptureRecordingPaths?> SetRecordingAsync(bool active)
    {
        Owner(); ObjectDisposedException.ThrowIf(closed, this);
        return service?.SetRecordingAsync(active, cancellation?.Token ?? default)
            ?? throw new InvalidOperationException("抓包服务尚未运行");
    }
    public void PublishCombo(EvidenceObject message) { Owner(); if (!closed) service?.PublishCombo(message); }
    public Task StopAsync()
    { Owner(); cancellation?.Cancel(); DropSubscriptions(); return run; }
    private void DropSubscriptions()
    { foreach (var value in subscriptions.Values) value.Dispose(); subscriptions.Clear(); }
    public ValueTask DisposeAsync()
    {
        Owner(); if (shutdown is not null) return new(shutdown);
        closed = true; var finishing = StopAsync(); shutdown = FinishAsync(finishing); return new(shutdown);
    }
    private async Task FinishAsync(Task finishing)
    { await finishing.ConfigureAwait(false); cancellation?.Dispose(); }
}
