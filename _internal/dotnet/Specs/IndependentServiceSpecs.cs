using System.Collections.Concurrent;
using System.Diagnostics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Runtime.Vision;

internal static class IndependentServiceSpecs
{
    private sealed class Recorder : IInputRecordingService
    {
        public volatile bool Active;
        public bool Running => Active;
        public EvidenceObject Status => TraceData.Make(("status", Active ? "recording" : "stopped"));
        public readonly ConcurrentQueue<string> Commands = new();
        public TaskCompletionSource? StartGate;
        public InputRecordingOptions? Options;
        public bool Disposed;
        public async Task StartAsync(InputRecordingOptions options, bool elevate = true, CancellationToken token = default)
        {
            Options = options; Commands.Enqueue("start");
            if (StartGate is { } waiting) await waiting.Task.WaitAsync(token);
            Active = true;
        }
        public Task SetTraceAsync(string? trace, CancellationToken token = default) { Commands.Enqueue("trace:" + trace); return Task.CompletedTask; }
        public Task StopAsync() { Commands.Enqueue("stop"); Active = false; return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Disposed = true; Active = false; return ValueTask.CompletedTask; }
    }
    private sealed class Capture : IVisionCaptureBackend
    {
        public volatile bool Disposed;
        public VisionTargets Discover(string executable) => new([], null);
        public void SetTarget(long? window) { }
        public VisionCaptureFrame? AcquireLatest() => null;
        public void Dispose() => Disposed = true;
    }
    private static void Until(Func<bool> value)
    { var watch = Stopwatch.StartNew(); while (!value()) { if (watch.Elapsed.TotalSeconds > 8) throw new TimeoutException("Independent services did not reach the expected state"); Thread.Sleep(10); } }
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-independent-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        SettingsContext context = new(root); SettingsCodec codec = new(context); SettingsStore settings = new(codec.Decode(TraceData.Make()), codec);
        Recorder recorder = new(); ConcurrentQueue<Capture> captures = new();
        VisionService vision = new(() => { Capture capture = new(); captures.Enqueue(capture); return capture; }, "missing-game.exe");
        IReadOnlySet<string> streams = new HashSet<string>(); List<string> diagnostics = [];
        IndependentServiceController controller = new(recorder, vision, value => streams = value, settings, Path.Combine(root, "native"), diagnostics.Add);
        try
        {
            check(!vision.Running && captures.IsEmpty && !recorder.Running, "Independent services allocate no worker until requested");
            controller.SetRequirements(["analysis_summary", "combo_snapshot", "unexpected"]);
            Until(() => vision.Running && !captures.IsEmpty);
            check(streams.SetEquals(["analysis_summary"]), "Only analysis subscriptions reach packet capture; combo is independently visual");
            controller.SetPreview(true); controller.SetRequirements([]); Thread.Sleep(60);
            check(vision.Running && streams.Count == 0, "Calibration preview keeps visual capture alive without packet subscriptions");
            controller.SetPreview(false); Until(() => !vision.Running && captures.All(capture => capture.Disposed));
            check(true, "Removing the last visual demand awaits capture release");
            controller.SetPreview(true); Until(() => vision.Running && captures.Count == 2);
            controller.SetSession("session-one"); controller.SetMembers([new(0, "char_1", "角色一")]);
            bool HasIdentity(EvidenceObject? message) => message?.Get("snapshot") is EvidenceObject snapshot
                && TraceData.Rows(snapshot.Get("slots")).Any(row => row.Get("character_key") is EvidenceText { Value: "char_1" });
            Until(() => HasIdentity(controller.Poll().ComboSnapshot));
            controller.SetSession("session-two");
            check(!HasIdentity(controller.Poll().ComboSnapshot), "Changing sessions clears prior squad identity before new evidence arrives");
            var configuration = TraceData.Make(("layout", "keyboard")); controller.ConfigureVision(configuration);
            check(EvidenceJson.PythonEquals(codec.Load().VisionSettings, configuration), "Visual calibration persists through owner-thread settings");
            controller.PreviewVisionSettings(TraceData.Make(("layout", "gamepad"), ("target_hwnd", 456)));
            check(EvidenceJson.PythonEquals(settings.Current.VisionSettings, configuration) && EvidenceJson.PythonEquals(codec.Load().VisionSettings, configuration),
                "Transient calibration changes do not overwrite saved settings before explicit acceptance");
            controller.PreviewVisionSettings(settings.Current.VisionSettings);

            controller.StartInput();
            check(controller.InputEnabled && !recorder.Running && recorder.Commands.IsEmpty,
                "Enabling input persists a preference without opening files while recording is off");
            TaskCompletionSource start = new(TaskCreationOptions.RunContinuationsAsynchronously); recorder.StartGate = start;
            _ = controller.SetRecording(true, Path.Combine(root, "a.log")); Until(() => recorder.Commands.Contains("start"));
            check(controller.InputTransitioning && !recorder.Running && settings.Current.InputRecordingEnabled,
                "Input startup runs off the owner thread after recording starts");
            controller.SetTrace(Path.Combine(root, "b.log")); start.SetResult(); Until(() => !controller.InputTransitioning);
            var state = controller.Poll();
            check(state.InputRunning && codec.Load().StartInputRecordingOnLaunch && recorder.Options?.Trace == Path.Combine(root, "a.log")
                && recorder.Commands.Last() == "trace:" + Path.Combine(root, "b.log"), "Input preference survives reload and trace commands follow startup");
            controller.CaptureStopped(); Until(() => !controller.InputTransitioning);
            check(!recorder.Running && vision.Running && controller.InputEnabled && recorder.Commands.Last() == "stop",
                "Stopping packet capture flushes input while preserving enable preference and independent vision");
            _ = controller.SetRecording(true, Path.Combine(root, "next.log")); Until(() => !controller.InputTransitioning);
            check(recorder.Running && recorder.Options?.Trace == Path.Combine(root, "next.log"), "Restarting recording opens input linked to the new trace");
            controller.ToggleInput(); Until(() => !controller.InputTransitioning); controller.Poll();
            check(!recorder.Running && !controller.InputEnabled && !codec.Load().StartInputRecordingOnLaunch,
                "Disabling input persists the option without changing damage recording");
            var ownerRejected = Task.Run(() => { try { controller.SetRequirements([]); return false; } catch (InvalidOperationException) { return true; } }).GetAwaiter().GetResult();
            check(ownerRejected, "Cross-thread application coordination is rejected");

            recorder.StartGate = new(TaskCreationOptions.RunContinuationsAsynchronously); controller.StartInput();
            Until(() => controller.InputTransitioning);
            controller.DisposeAsync().AsTask().GetAwaiter().GetResult();
            check(recorder.Disposed && !recorder.Running && !vision.Running && captures.All(capture => capture.Disposed) && streams.Count == 0,
                "Asynchronous exit cancels pending startup and releases both independent services");
            controller.StartInput(); controller.SetPreview(true);
            check(!recorder.Running && !vision.Running, "Closed coordination cannot restart workers");
        }
        finally { controller.DisposeAsync().AsTask().GetAwaiter().GetResult(); Directory.Delete(root, true); }
    }
}
