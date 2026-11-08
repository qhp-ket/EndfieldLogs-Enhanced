using System.Runtime.ExceptionServices;
using EndfieldLogs.Capture;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Sessions;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Capture;

public sealed record GameCaptureOptions(string GameExecutable, string NativeGameDirectory, string RsaKeyPath,
    string? LogDirectory = null, string NpcapDevice = "auto", bool MergeMultiPhaseEnemyBattles = false,
    bool RotationClockTrace = true, string? DebugDirectory = null, int? WebSocketPort = 29325, string BrowserToken = "",
    string? NameIndexPath = null, string TraceFormat = "jsonl", bool RecordingOnStart = true);

/// <summary>Native capture/crypto → ordered business → shared trace → demand-driven live publications.</summary>
public sealed class GameCaptureService(ResourceFiles resources, GameCaptureOptions options,
    Func<ICaptureBackend>? backendFactory = null)
{
    private readonly object gate = new();
    private TraceRecording? activeRecording;
    private CaptureArtifacts? activeArtifacts;
    private LiveAnalysisStreams? activeStreams;
    private LoopbackWebSocketServer? activeSocket;
    private CaptureRuntime? activeRuntime;
    private CaptureRuntimeSnapshot? status;
    private bool started;
    public CaptureRuntimeSnapshot? Status { get { lock (gate) return status; } }
    public Uri? WebSocketEndpoint { get { lock (gate) return activeSocket?.Endpoint; } }
    public bool HasComboSubscribers { get { lock (gate) return activeSocket?.HasComboSubscribers == true; } }
    public void PublishCombo(EvidenceObject message) { LoopbackWebSocketServer? socket; lock (gate) socket = activeSocket; socket?.PublishCombo(message); }
    public string? ActiveTracePath { get { lock (gate) return activeArtifacts?.TraceFilePath; } }
    public bool Recording { get { lock (gate) return activeArtifacts?.Recording == true; } }
    public Task<CaptureRecordingPaths?> SetRecordingAsync(bool active, CancellationToken cancellationToken = default)
    {
        CaptureRuntime runtime;
        lock (gate) runtime = activeRuntime ?? throw new InvalidOperationException("抓包服务尚未运行");
        return runtime.SetRecordingAsync(active, cancellationToken);
    }
    public bool IsWriting(string path) { lock (gate) return activeRecording?.IsWriting(path) == true || activeArtifacts?.IsWriting(path) == true; }
    public Task<CaptureRecordingPaths> RotateRecordingAsync(CancellationToken cancellationToken = default)
    {
        CaptureRuntime runtime;
        lock (gate) runtime = activeRuntime ?? throw new InvalidOperationException("抓包服务尚未运行");
        return runtime.RotateRecordingAsync(cancellationToken);
    }
    public LiveAnalysisSubscription Subscribe(bool summary = true)
    {
        lock (gate) return activeStreams?.Subscribe(summary) ?? throw new InvalidOperationException("Capture analysis is not running");
    }
    public LiveAnalysisSubscription? TrySubscribe(bool summary = true)
    { lock (gate) return activeStreams?.Subscribe(summary); }

    // Resource loading, process discovery and native calls run away from the caller's UI thread.
    public Task RunAsync(Func<LiveSnapshotFrame, CancellationToken, ValueTask>? deliver = null,
        Action<CaptureRuntimeSnapshot>? onStatus = null, Action<BattleLogEvent>? onEvent = null,
        Action<string, Exception?>? diagnostic = null, CancellationToken cancellationToken = default)
    {
        lock (gate) { if (started) throw new InvalidOperationException("A game capture service can only run once"); started = true; }
        return Task.Run(() => RunCoreAsync(deliver, onStatus, onEvent, diagnostic, cancellationToken), CancellationToken.None);
    }

    private async Task RunCoreAsync(Func<LiveSnapshotFrame, CancellationToken, ValueTask>? deliver,
        Action<CaptureRuntimeSnapshot>? onStatus, Action<BattleLogEvent>? onEvent, Action<string, Exception?>? diagnostic,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (options.TraceFormat is not ("legacy" or "jsonl"))
            throw new ArgumentException("Unsupported trace recording format", nameof(options));
        using var backend = CreateBackend();
        SkillResourceCatalog identities = new(resources);
        LoadoutDisplayCatalog loadouts = new(resources);
        var header = options.TraceFormat == "jsonl" ? TraceRecording.CreateHeader(resources) : null;
        var zone = header is null ? TimeZoneInfo.Local : TimeZoneInfo.CreateCustomTimeZone(header.TimeZoneId,
            TimeSpan.FromMinutes(header.TimeZoneOffsetMinutes), header.TimeZoneId, header.TimeZoneId);
        using var analysis = LiveAnalysisStreams.Create(resources, DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(DateTimeOffset.Now, zone).DateTime), zone);
        using var subscription = deliver is null ? null : analysis.Subscribe();
        CaptureArtifacts? destination = null;
        using var recording = header is null ? new TraceRecording(line => { destination?.WriteTraceLine(line); analysis.FeedLine(line); }, null, identities)
            : TraceRecording.CreateStructured(events => { destination?.WriteTraceEvents(events); analysis.FeedEvents(events); }, header, null, identities);
        using var artifacts = new CaptureArtifacts(recording, options.GameExecutable, options.LogDirectory,
            options.DebugDirectory, diagnostic);
        destination = artifacts;
        if (options.RecordingOnStart && options.LogDirectory is not null) artifacts.SetRecording(true);
        RuntimeMetrics metrics = new();
        IReadOnlyList<DeviceInfo> devices = [];
        Dictionary<string, object?> Hello() => new()
        {
            ["type"] = "hello", ["schema_version"] = 2,
            ["service_version"] = typeof(GameCaptureService).Assembly.GetName().Version?.ToString(3),
            ["state"] = Status?.Flow.State ?? ServiceState.WaitingGame, ["session_id"] = Status?.Flow.SessionId, ["metrics"] = metrics,
            ["recording"] = artifacts.Recording,
        };
        LoopbackWebSocketServer? sockets = options.WebSocketPort is { } port
            ? new(port, options.BrowserToken, analysis.Subscribe, Hello, () => metrics.WsBatchesSent++) : null;
        ServiceState? lastState = null;
        long nextDiagnostic = 0;
        bool? lastRecording = null;
        string? shutdownStatusPath = null;
        lock (gate) { activeRecording = recording; activeArtifacts = artifacts; activeStreams = analysis; activeSocket = sockets; }
        try
        {
            var names = ReadNames(); var dungeons = ReadMap(resources.ReadRelative("jsondata/Dungeon.json"));
            CaptureFlowSession flow = new((selected, output) =>
            {
                var id = Guid.NewGuid().ToString("N"); artifacts.BeginSession(id);
                return new GameSessionPipeline(selected, id, backend.Registry, backend.DecryptLogin, backend.DecryptKey,
                    output, metrics, options.DebugDirectory is null ? null : artifacts.WriteMessage,
                    options.DebugDirectory is null ? null : artifacts.WriteDebugRecord,
                    rotationClockTrace: options.RotationClockTrace, names: names, multiPhaseDungeons: dungeons,
                    mergeMultiPhaseEnemyBattles: options.MergeMultiPhaseEnemyBattles, loadoutCatalog: loadouts);
            }, recording, () => analysis.Reset(), value => { artifacts.WriteEvent(value); sockets?.PublishEvent(value); onEvent?.Invoke(value); },
                onSessionClosed: artifacts.CloseSession);
            CaptureRuntime runtime = new(flow, recording, backend.ObserveGame,
                (packet, observe) => { var captureDevices = backend.OpenCapture(packet, observe); devices = captureDevices.Devices; return captureDevices; }, snapshot =>
                {
                    lock (gate) status = snapshot;
                    var finalPath = !snapshot.Running ? artifacts.StatusFilePath : null;
                    if (finalPath is not null) shutdownStatusPath = finalPath;
                    if (!snapshot.Running) artifacts.SetRecording(false);
                    artifacts.WriteStatus(snapshot, metrics, devices, finalPath);
                    if (lastState != snapshot.Flow.State || lastRecording != artifacts.Recording)
                    { lastState = snapshot.Flow.State; lastRecording = artifacts.Recording; sockets?.BroadcastHello(); }
                    var now = Environment.TickCount64;
                    if (diagnostic is not null && (now >= nextDiagnostic || !snapshot.Running))
                    {
                        nextDiagnostic = now + 5000;
                        diagnostic($"抓包统计 state={snapshot.Flow.State} packets={snapshot.PacketsSeen} queue_drop={snapshot.QueueDrops} " +
                            $"pcap_drop={snapshot.Statistics.Dropped} frames={metrics.FramesDecoded} messages={metrics.MessagesDecoded} " +
                            $"events={metrics.OutboundEventsEmitted} protobuf_errors={metrics.ProtobufDecodeErrors} decompress_errors={metrics.DecompressionErrors}", null);
                    }
                    onStatus?.Invoke(snapshot);
                }, onDiagnostic: diagnostic, rotateRecording: () =>
                {
                    lock (gate)
                    {
                        if (flow.SessionId is null) throw new InvalidOperationException("请等待抓包会话开始后新建记录");
                        return artifacts.RotateRecording();
                    }
                }, setRecording: active =>
                {
                    lock (gate)
                    {
                        var finalPath = !active ? artifacts.StatusFilePath : null;
                        var paths = artifacts.SetRecording(active);
                        if (finalPath is not null && status is { } snapshot) artifacts.WriteStatus(snapshot, metrics, devices, finalPath);
                        return paths;
                    }
                });
            lock (gate) activeRuntime = runtime;
            using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            using CancellationTokenSource networkLifetime = new();
            var network = sockets?.RunAsync(networkLifetime.Token) ?? Task.Delay(Timeout.Infinite, networkLifetime.Token);
            var capture = runtime.RunAsync(lifetime.Token);
            var publication = analysis.RunAsync(lifetime.Token);
            async Task DeliverAsync()
            {
                if (subscription is null || deliver is null) { await Task.Delay(Timeout.Infinite, lifetime.Token).ConfigureAwait(false); return; }
                while (await subscription.ReadAsync(lifetime.Token).ConfigureAwait(false) is { } frame)
                    await deliver(frame, lifetime.Token).ConfigureAwait(false);
            }
            var delivery = DeliverAsync();
            Exception? failure = null;
            try { await Task.WhenAny(capture, publication, delivery, network).ConfigureAwait(false); }
            finally
            {
                lifetime.Cancel();
                try { await Task.WhenAll(capture, publication, delivery).ConfigureAwait(false); }
                catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
                catch (Exception error) { failure = error; }
                // Reset in capture shutdown leaves one explicit clear frame for consumers still listening.
                using var finishing = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                try
                {
                    analysis.Reset();
                    await analysis.FlushPendingAsync(finishing.Token).ConfigureAwait(false);
                    if (subscription is not null && deliver is not null)
                        while (subscription.TryRead(out var clear))
                            await deliver(clear!, finishing.Token).AsTask().WaitAsync(finishing.Token).ConfigureAwait(false);
                }
                catch (Exception error) { failure ??= error; }
                networkLifetime.Cancel();
                try { await network.ConfigureAwait(false); }
                catch (OperationCanceledException) when (networkLifetime.IsCancellationRequested) { }
                catch (Exception error) { failure ??= error; }
            }
            if (failure is not null)
            {
                CaptureRuntimeSnapshot failed = runtime.Snapshot with { Error = failure.Message, ErrorType = failure.GetType().Name,
                    ErrorTask = network.IsFaulted ? "websocket" : publication.IsFaulted ? "analysis" : delivery.IsFaulted ? "observer" : "capture" };
                lock (gate) status = failed;
                artifacts.WriteStatus(failed, metrics, devices, shutdownStatusPath);
                try { onStatus?.Invoke(failed); } catch { /* Preserve the primary service failure for its caller. */ }
                ExceptionDispatchInfo.Capture(failure).Throw();
            }
        }
        finally { lock (gate) { activeRuntime = null; activeRecording = null; activeArtifacts = null; activeStreams = null; activeSocket = null; } }
    }

    private ICaptureBackend CreateBackend()
    {
        if (backendFactory is not null) return backendFactory();
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Game capture requires Windows");
        return new WindowsCaptureBackend(resources, options);
    }

    private static Dictionary<string, string> ReadMap(EvidenceValue? value) =>
        value is EvidenceObject map ? map.Fields.Where(pair => pair.Value is EvidenceText { Value.Length: > 0 })
            .ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal) : new(StringComparer.Ordinal);

    private Dictionary<string, string> ReadNames()
    {
        var result = ReadMap(options.NameIndexPath is { } path ? resources.Read(path) : resources.ReadRelative("jsondata/CharacterNameIndex.json"));
        if (resources.ReadRelative("data/local_tables/character/manifest.json") is EvidenceObject manifest
            && manifest.Get("entries") is EvidenceArray entries)
            foreach (var row in entries.Items.OfType<EvidenceObject>())
            {
                var id = TraceData.Text(row.Get("charId"), TraceData.Text(row.Get("id"))).Trim();
                var name = TraceData.Text(row.Get("name")).Trim();
                if (id.Length > 0 && name.Length > 0) result[id] = name;
            }
        return result;
    }
}
