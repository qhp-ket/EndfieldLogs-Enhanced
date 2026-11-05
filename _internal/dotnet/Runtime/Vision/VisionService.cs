using System.Diagnostics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Vision;

public sealed record VisionTargets(IReadOnlyList<long> Windows, long? Foreground);
public sealed class VisionCaptureFrame(VisionPixels pixels, PixelArea client, long frameId, double receivedMono, long window, Action? release = null) : IDisposable
{
    public VisionPixels Pixels { get; } = pixels;
    public PixelArea Client { get; } = client;
    public long FrameId { get; } = frameId;
    public double ReceivedMono { get; } = receivedMono;
    public long Window { get; } = window;
    private Action? dispose = release;
    public void Dispose() => Interlocked.Exchange(ref dispose, null)?.Invoke();
}
public interface IVisionCaptureBackend : IDisposable
{
    VisionTargets Discover(string executable);
    void SetTarget(long? window);
    VisionCaptureFrame? AcquireLatest();
}
public sealed record VisionMember(int Slot, string CharacterKey, string DisplayName, bool IsLeader = false);
public sealed record VisionPreview(byte[] Bgra, int Width, int Height, long Window);

/// <summary>Demand-driven visual worker with one capture owner and one latest result. No UI objects cross this boundary.</summary>
public sealed class VisionService(Func<IVisionCaptureBackend> factory, string executable, EvidenceValue? settings = null) : IAsyncDisposable
{
    private readonly object gate = new();
    private VisionConfiguration config = VisionConfiguration.Normalize(settings);
    private string gameExecutable = executable;
    private bool enabled, previewEnabled, closed;
    private long revision;
    private CancellationTokenSource? stop;
    private Task? worker;
    private string stream = Guid.NewGuid().ToString("N");
    private long sequence;
    private EvidenceObject state = TraceData.Make(("status", "已停止"), ("frame_valid", false), ("slots", new EvidenceArray([])));
    private EvidenceObject? published;
    private Dictionary<int, VisionMember> identity = [];
    private VisionPreview? preview;
    private VisionTargets targets = new([], null);
    public bool Running { get { lock (gate) return worker is { IsCompleted: false }; } }
    public EvidenceObject State { get { lock (gate) return (EvidenceObject)EvidenceJson.Clone(state); } }
    public VisionTargets Targets { get { lock (gate) return new(targets.Windows.ToArray(), targets.Foreground); } }
    public void Configure(EvidenceValue value)
    { lock (gate) { ObjectDisposedException.ThrowIf(closed, this); config = VisionConfiguration.Normalize(value); revision++; preview = null; } }
    public void SetGameExecutable(string path)
    { lock (gate) { if (gameExecutable == path) return; gameExecutable = path; revision++; identity.Clear(); preview = null; targets = new([], null); } }
    public void SetIdentity(IReadOnlyList<VisionMember> members)
    { lock (gate) identity = members.ToDictionary(member => member.Slot, member => member); }
    public void SetPreview(bool value) { lock (gate) { previewEnabled = value; if (!value) preview = null; } }
    public VisionPreview? TakePreview()
    { lock (gate) { var latest = preview; preview = null; return latest; } }

    public async Task SetEnabledAsync(bool value)
    {
        Task? stopping;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(closed, this); enabled = value;
            if (value && worker is null) { Start(); return; }
            if (value && worker is { IsCompleted: false } && stop?.IsCancellationRequested == false) return;
            if (value && worker?.IsCompleted == true) { worker = null; stop?.Dispose(); stop = null; Start(); return; }
            stop?.Cancel(); stopping = worker;
            if (stopping is not null) state = TraceData.Make(("status", "正在停止图像捕获"), ("frame_valid", false), ("slots", new EvidenceArray([])));
        }
        if (stopping is not null) await stopping.ConfigureAwait(false);
        lock (gate)
        {
            // A concurrent enable awaits this same worker; only its owner replaces it.
            if (!ReferenceEquals(worker, stopping)) return;
            worker = null; stop?.Dispose(); stop = null; identity.Clear(); preview = null; published = null; targets = new([], null);
            state = TraceData.Make(("status", "已停止"), ("frame_valid", false), ("slots", new EvidenceArray([])));
            if (enabled && !closed) Start();
        }
    }
    private void Start()
    {
        stop = new(); stream = Guid.NewGuid().ToString("N"); sequence = 0; published = null;
        state = TraceData.Make(("status", "寻找游戏窗口"), ("frame_valid", false), ("slots", new EvidenceArray([])));
        var token = stop.Token; worker = Task.Run(() => RunAsync(token), CancellationToken.None);
    }
    private async Task RunAsync(CancellationToken token)
    {
        IVisionCaptureBackend? backend = null; VisionEngine engine = new(); long currentRevision = -1;
        long? window = null, processed = null; double? received = null; var discoveredAt = double.NegativeInfinity; var previewAt = double.NegativeInfinity; var valid = false;
        try
        {
            backend = factory();
            while (!token.IsCancellationRequested)
            {
                VisionConfiguration selected; string game; long version; bool showPreview;
                lock (gate) { selected = config; game = gameExecutable; version = revision; showPreview = previewEnabled; }
                if (currentRevision != version)
                { engine = new(selected); currentRevision = version; discoveredAt = double.NegativeInfinity; processed = null; }
                var now = Mono();
                if (now - discoveredAt >= .5)
                {
                    discoveredAt = now; var discovered = backend.Discover(game);
                    lock (gate) if (version == revision && !token.IsCancellationRequested) targets = new(discovered.Windows.ToArray(), discovered.Foreground);
                    var preferred = selected.TargetWindow <= long.MaxValue && discovered.Windows.Contains((long)selected.TargetWindow) ? (long?)selected.TargetWindow : null;
                    var next = preferred ?? discovered.Foreground ?? (discovered.Windows.Count == 0 ? null : discovered.Windows[0]);
                    if (next != window)
                    {
                        backend.SetTarget(next); window = next; engine = new(selected); processed = null; received = null;
                        lock (gate) if (revision == version) { identity.Clear(); preview = null; }
                    }
                }
                var began = Mono(); EvidenceObject? result = null;
                using (var frame = window is null ? null : backend.AcquireLatest())
                {
                    if (frame is not null && frame.Window == window)
                    {
                        received = frame.ReceivedMono;
                        if (frame.FrameId != processed && now - frame.ReceivedMono <= 1)
                        {
                            processed = frame.FrameId; result = engine.Analyze(frame.Pixels, frame.Client, now, frame.FrameId);
                            if (showPreview && now - previewAt > .25)
                            {
                                previewAt = now;
                                var area = result.Get("game_area") is EvidenceArray { Items.Count: 4 } a ? new PixelArea((int)((EvidenceInteger)a.Items[0]).Value,
                                    (int)((EvidenceInteger)a.Items[1]).Value, (int)((EvidenceInteger)a.Items[2]).Value, (int)((EvidenceInteger)a.Items[3]).Value) : new(0, 0, frame.Pixels.Width, frame.Pixels.Height);
                                var thumbnail = MakePreview(frame.Pixels, area, window.Value);
                                lock (gate) if (version == revision && previewEnabled && !token.IsCancellationRequested) preview = thumbnail;
                            }
                        }
                    }
                }
                if (window is null || received is null || now - received > 1)
                    result = engine.Invalid(now, window is null ? "等待游戏窗口" : "画面未更新");
                if (result is not null)
                {
                    valid = result.Get("frame_valid") is EvidenceBoolean { Value: true };
                    var fields = result.Fields.ToDictionary(); var publishedMono = Mono();
                    fields["published_mono"] = new EvidenceReal(publishedMono); fields["processing_ms"] = new EvidenceReal((publishedMono - began) * 1000);
                    fields["target_hwnd"] = window is null ? EvidenceNull.Value : new EvidenceInteger(window.Value);
                    fields["capture_to_publish_ms"] = received is null ? EvidenceNull.Value : new EvidenceReal((publishedMono - received.Value) * 1000);
                    lock (gate) if (version == revision && !token.IsCancellationRequested) state = new(fields);
                }
                await Task.Delay(window is null ? 500 : valid || showPreview ? 50 : 100, token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception error)
        {
            var value = engine.Invalid(Mono(), "图像捕获不可用：" + error.Message).Fields.ToDictionary(); value["target_hwnd"] = window is null ? EvidenceNull.Value : new EvidenceInteger(window.Value);
            lock (gate) if (!token.IsCancellationRequested) state = new(value);
        }
        finally
        {
            try { backend?.Dispose(); }
            catch (Exception error)
            { lock (gate) state = engine.Invalid(Mono(), "图像捕获资源释放失败：" + error.Message); }
        }
    }
    private static double Mono() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
    private static VisionPreview MakePreview(VisionPixels pixels, PixelArea area, long window)
    {
        var scale = Math.Min(960.0 / area.Width, 540.0 / area.Height); var width = Math.Max(1, (int)Math.Round(area.Width * scale)); var height = Math.Max(1, (int)Math.Round(area.Height * scale));
        byte[] bytes = new byte[checked(width * height * 4)];
        for (var y = 0; y < height; y++) for (var x = 0; x < width; x++)
        {
            // Preview is presentation only; the recognizer always reads the original frame ROI.
            var sx = area.X + Math.Min(area.Width - 1, (int)(x / scale)); var sy = area.Y + Math.Min(area.Height - 1, (int)(y / scale)); var offset = (y * width + x) * 4;
            for (var c = 0; c < 3; c++) bytes[offset + c] = pixels.At(sx, sy, c); bytes[offset + 3] = 255;
        }
        return new(bytes, width, height, window);
    }
    public EvidenceObject? TakeSnapshot()
    {
        lock (gate)
        {
            if (stop?.IsCancellationRequested == true) return null;
            var values = state.Fields.ToDictionary();
            var slots = TraceData.Rows(state.Get("slots")).Select(row =>
            {
                var item = row.Fields.ToDictionary(); var index = (int)(TraceData.Int(row.Get("slot")) ?? -1);
                if (identity.TryGetValue(index, out var member)) { item["character_key"] = new EvidenceText(member.CharacterKey); item["display_name"] = new EvidenceText(member.DisplayName); }
                return new EvidenceObject(item);
            }).ToArray();
            values["slots"] = new EvidenceArray(slots);
            var content = values.Where(pair => pair.Key is not ("published_mono" or "processing_ms" or "capture_to_publish_ms" or "slots" or "diagnostics")).ToDictionary();
            content["slots"] = new EvidenceArray(slots.Select(row =>
            {
                var item = row.Fields.ToDictionary();
                item["progress"] = TraceData.Float(row.Get("progress")) is { } progress ? new EvidenceReal(PythonDecimalRounding.Round(progress, 3)) : EvidenceNull.Value;
                item["estimated_remaining_ms"] = TraceData.Float(row.Get("estimated_remaining_ms")) is { } estimate ? new EvidenceReal(Math.Round(estimate / 100) * 100) : EvidenceNull.Value;
                return new EvidenceObject(item);
            }).ToArray());
            var current = new EvidenceObject(content); if (published is not null && EvidenceJson.PythonEquals(current, published)) return null;
            published = (EvidenceObject)EvidenceJson.Clone(current); values.Remove("diagnostics");
            return TraceData.Make(("type", "combo_snapshot"), ("schema_version", 2), ("stream_id", stream), ("sequence", ++sequence), ("snapshot", new EvidenceObject(values)), ("source", "vision"));
        }
    }
    public async ValueTask DisposeAsync()
    {
        Task? stopping;
        lock (gate) { if (closed) return; closed = true; enabled = false; stop?.Cancel(); stopping = worker; }
        if (stopping is not null) await stopping.ConfigureAwait(false);
        lock (gate)
        {
            worker = null; stop?.Dispose(); stop = null; identity.Clear(); preview = null; published = null; targets = new([], null);
            state = TraceData.Make(("status", "已停止"), ("frame_valid", false), ("slots", new EvidenceArray([])));
        }
    }
}
