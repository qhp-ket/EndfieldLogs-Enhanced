using System.Diagnostics;
using System.Buffers.Binary;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Native.Input;
using EndfieldLogs.Runtime.Input;

internal static class InputRecordingSpecs
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(15);
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static string Text(EvidenceObject value, string key) => value.Get(key) is EvidenceText text ? text.Value : "";
    private static void Wait(Task task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static T Wait<T>(Task<T> task) => task.WaitAsync(Timeout).GetAwaiter().GetResult();
    private static void Until(Func<bool> predicate)
    { var started = Stopwatch.GetTimestamp(); while (!predicate()) { if (Stopwatch.GetElapsedTime(started) > Timeout) throw new TimeoutException("Input recorder condition timed out"); Thread.Sleep(10); } }
    private static EvidenceObject[] Read(string path) => File.ReadAllLines(path).Select(line => (EvidenceObject)EvidenceJson.Parse(line)).ToArray();
    private sealed class Foreground : IInputForeground
    { public bool Active { get; set; } = true; public IReadOnlyList<string> HeldKeys() => ["K:ALT"]; }
    private sealed class GateStream : MemoryStream
    {
        public bool Block;
        public readonly ManualResetEventSlim Entered = new(), Released = new();
        public override void Write(byte[] buffer, int offset, int count)
        { if (Block) { Entered.Set(); if (!Released.Wait(Timeout)) throw new TimeoutException("Test storage was not released"); } base.Write(buffer, offset, count); }
        public override void Write(ReadOnlySpan<byte> buffer)
        { if (Block) { Entered.Set(); if (!Released.Wait(Timeout)) throw new TimeoutException("Test storage was not released"); } base.Write(buffer); }
    }
    private sealed class FailingStream : MemoryStream
    {
        public bool Fail;
        public override void Flush() { if (Fail) throw new IOException("synthetic storage failure"); base.Flush(); }
    }
    public static void Writer(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-input-writer-");
        try
        {
            var trace = Path.Combine(root.FullName, "trace.log"); var path = InputLogWriter.Companion(trace); File.WriteAllText(trace, "synthetic trace\r\n", new UTF8Encoding(false));
            long tick = 0; InputTimestamp Clock() => new(1793188800000000000 + Interlocked.Increment(ref tick), tick * 1_000_000);
            using (InputLogWriter writer = new(path, trace, clock: Clock))
            {
                var fields = Obj("""{"device":"raw:1","kind":"key","code":"K:69","phase":"down","value":1,"raw":{"vk":69},"wall_ns":1793188800001000000,"mono_ns":1000000}""");
                check(writer.Put("input", fields), "Input callbacks enqueue without waiting for storage");
                ((Dictionary<string, EvidenceValue>)((EvidenceObject)fields.Get("raw")).Fields)["vk"] = new EvidenceInteger(0);
                writer.Put("input", Obj("""{"device":"raw:1","kind":"key","code":"K:69","phase":"up","value":0,"wall_ns":1793188800002000000,"mono_ns":2000000}"""));
                Until(() =>
                {
                    using FileStream source = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                    using StreamReader reader = new(source); return reader.ReadToEnd().Contains("\"seq\":2", StringComparison.Ordinal);
                });
                check(writer.Count == 2 && writer.Lost == 0, "Continuous recordings become readable within the flush interval");
            }
            var rows = Read(path);
            check(rows.Length == 5 && Text(rows[0], "type") == "session" && rows[0].Get("schema_version") is EvidenceInteger { Value: var schema } && schema == 1
                && !File.ReadAllBytes(path).AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }), "Sidecars retain schema-v1, exclusive creation, UTF8 without BOM and a terminal record");
            check(((EvidenceObject)rows[1].Get("raw")).Get("vk") is EvidenceInteger { Value: var vk } && vk == 69, "Queued event fields are owned copies");
            var archive = new InputArchive(path); var valid = archive.VerifyTrace(trace);
            check(archive.Actions.Count == 1 && archive.Actions[0].Action == "combo" && valid.Length > 0 && archive.Warnings.Count == 0,
                "Actual writer output feeds the production archive/interpreter and exact trace-prefix verification");
            File.AppendAllText(trace, "new trace content\n"); archive.VerifyTrace(trace);
            check(Text(rows[^1], "scope") == "prefix" && rows[^1].Get("bytes") is EvidenceInteger { Value: var covered } && covered == Encoding.UTF8.GetByteCount("synthetic trace\r\n"),
                "Trace growth does not invalidate the recording's explicitly sized prefix");
            var refused = false; try { using InputLogWriter duplicate = new(path); } catch (IOException) { refused = true; }
            check(refused, "Starting another recording never overwrites an existing session");

            using GateStream storage = new(); InputLogWriter bounded = new(Path.Combine(root.FullName, "buffer"), null, 2, "bounded", Clock, storage);
            try
            {
                storage.Block = true;
                bounded.Put("diagnostic", new(new Dictionary<string, EvidenceValue> { ["payload"] = new EvidenceText(new string('x', 400000)) }));
                check(storage.Entered.Wait(Timeout), "Backpressure test holds the real storage writer rather than relying on scheduling");
                bounded.Put("input", Obj("{}")); bounded.Put("input", Obj("{}"));
                var started = Stopwatch.GetTimestamp(); var first = bounded.Put("input", Obj("""{"wall_ns":100,"mono_ns":200}""")); var second = bounded.Put("input", Obj("""{"wall_ns":300,"mono_ns":400}"""));
                check(!first && !second && bounded.Count == 3 && bounded.Lost == 2 && Stopwatch.GetElapsedTime(started).TotalSeconds < 1,
                    "A full queue drops explicitly and keeps input producers responsive");
                storage.Released.Set(); bounded.Close(); var output = Encoding.UTF8.GetString(storage.ToArray()).Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(Obj).ToArray();
                var gap = output.Single(row => Text(row, "type") == "gap");
                check(gap.Get("seq") is EvidenceInteger { Value: var seq } && seq == 4 && gap.Get("count") is EvidenceInteger { Value: var lost } && lost == 2
                    && gap.Get("start_wall_ns") is EvidenceInteger { Value: var start } && start == 100 && gap.Get("end_mono_ns") is EvidenceInteger { Value: var end } && end == 400,
                    "Close drains the pending loss interval before end with its original sequence and clocks");
                check(Text(output[^1], "type") == "end" && !output[^1].Fields.ContainsKey("seq"), "Control end markers keep the original non-input sequence contract");
            }
            finally { storage.Released.Set(); bounded.Close(); }

            using GateStream stalled = new(); InputLogWriter closing = new(Path.Combine(root.FullName, "stalled"), null, 1, null, Clock, stalled);
            try
            {
                stalled.Block = true; closing.Put("diagnostic", new(new Dictionary<string, EvidenceValue> { ["payload"] = new EvidenceText(new string('y', 400000)) }));
                if (!stalled.Entered.Wait(Timeout)) throw new TimeoutException("Storage did not stall");
                closing.Put("input", Obj("{}")); closing.Put("input", Obj("{}"));
                var stopped = Stopwatch.GetTimestamp(); var expired = false;
                try { closing.Close(timeout: TimeSpan.FromMilliseconds(100)); } catch (IOException) { expired = true; }
                check(expired && Stopwatch.GetElapsedTime(stopped).TotalSeconds < 2, "A full stalled queue bounds the entire close operation, including final loss markers");
            }
            finally { stalled.Released.Set(); closing.Close(); }
            using FailingStream broken = new(); InputLogWriter failed = new(Path.Combine(root.FullName, "failed"), null, 2, null, Clock, broken);
            broken.Fail = true; failed.Put("input", Obj("{}")); Until(() => failed.Completed);
            var surfaced = false; try { failed.Close(); } catch (IOException) { surfaced = true; }
            check(surfaced && failed.Error is IOException, "Storage flush failure reaches the recorder instead of leaving a healthy recording status");
        }
        finally { root.Delete(true); }
    }
    public static void Recorder(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-input-recorder-");
        try
        {
            var trace = Path.Combine(root.FullName, "trace.log"); File.WriteAllText(trace, "synthetic\n"); Foreground focus = new() { Active = false };
            using InputRecorder recorder = new(new("missing-game.exe", root.FullName, root.FullName), focus);
            recorder.Rotate(trace); var original = recorder.Path!;
            recorder.Emit("device", Obj("""{"device":"raw:1","backend":"raw_input","name":"keyboard"}"""));
            recorder.Emit("input", Obj("""{"device":"raw:1","backend":"raw_input","kind":"key","code":"K:49","phase":"down","value":1}"""));
            focus.Active = true; recorder.CheckFocus();
            recorder.Emit("input", Obj("""{"device":"raw:1","backend":"raw_input","kind":"key","code":"K:49","phase":"up","value":0}"""));
            recorder.Emit("input", Obj("""{"device":"raw:1","backend":"raw_input","kind":"key","code":"K:49","phase":"down","value":1}"""));
            recorder.Emit("input", Obj("""{"device":"windows:keyboard","backend":"windows_hook","kind":"key","code":"K:69","phase":"down","value":1}"""));
            recorder.Emit("device_change", Obj("""{"device":"windows:keyboard","connected":false}"""));
            recorder.Emit("backend_baseline", Obj("""{"device":"sdl:1","values":{"P:RB":1,"J:AXIS0":123}}"""));
            recorder.Emit("gap", Obj("""{"count":1,"missing_events":7}"""));
            var status = recorder.Status();
            check(Text(status, "status") == "recording" && ((EvidenceObject)status.Get("input_filtered")).Get("key") is EvidenceInteger { Value: var count } && count == 1,
                "Unfocused events update source diagnostics but are filtered from the input sidecar");
            check(status.Get("lost") is EvidenceInteger { Value: var lost } && lost == 7, "Backend and writer losses share the recording status counter");
            recorder.Rotate(trace); var fragment = recorder.Path!; recorder.Close();
            var rows = Read(original); var next = Read(fragment);
            check(fragment != original && Path.GetFileName(fragment).Contains(".part-", StringComparison.Ordinal) && Text(next[0], "trace_name") == "trace.log",
                "Reopening a trace creates a discoverable fragment instead of appending or overwriting");
            check(rows.Count(row => Text(row, "type") == "input") == 3 && rows.Any(row => Text(row, "reason") == "input_backend_changed")
                && rows.Any(row => Text(row, "reason") == "device_disconnected"), "Route changes and device removal interrupt prior intentions explicitly");
            var baseline = next.Single(row => Text(row, "type") == "baseline");
            check(((EvidenceObject)baseline.Get("states")).Get("sdl:1") is EvidenceObject values && values.Get("J:AXIS0") is EvidenceInteger { Value: var axis } && axis == 123,
                "Device state is retained across trace rotation as baseline, never fabricated button-down events");
            check(rows.Any(row => Text(row, "reason") == "recording_boundary") && Text(rows.Single(row => Text(row, "type") == "end"), "reason") == "rotation"
                && Text(next.Single(row => Text(row, "type") == "end"), "reason") == "stopped", "Rotation and stop close each recording with their distinct boundary reasons");
        }
        finally { root.Delete(true); }
    }
    private sealed class SyntheticBackend(Action<string, EvidenceObject> emit) : IInputBackend
    {
        private int pumped;
        public void Pump()
        {
            if (pumped++ == 0) emit("device", Obj("""{"device":"synthetic","backend":"test","name":"synthetic input"}"""));
            if (pumped is 1 or 2) emit("input", Obj($$"""{"device":"synthetic","kind":"key","code":"K:69","phase":"{{(pumped == 1 ? "down" : "up")}}","value":{{(pumped == 1 ? 1 : 0)}}}"""));
        }
        public EvidenceObject Health => Obj("{}"); public EvidenceObject Received => Obj("{}"); public IReadOnlyList<string> FallbackDevices => []; public void Dispose() { }
    }
    public static Task<int> Worker(string name, int pid, string secret) => InputWorkerHost.ConnectAsync(name, pid, secret,
        _ => new Foreground(), (_, emit) => [new SyntheticBackend(emit)]);
    private static ProcessStartInfo StartInfo(string name, string key, int parent)
    {
        ProcessStartInfo info = new(Environment.ProcessPath!) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true };
        info.ArgumentList.Add(typeof(InputRecordingSpecs).Assembly.Location); info.ArgumentList.Add("--input-worker"); info.ArgumentList.Add(name); info.ArgumentList.Add(parent.ToString()); info.ArgumentList.Add(key); return info;
    }
    public static void Process(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-input-process-");
        try
        {
            var first = Path.Combine(root.FullName, "first.log"); var second = Path.Combine(root.FullName, "second.log"); File.WriteAllText(first, "synthetic\n"); File.WriteAllText(second, "next\n");
            InputRecordingOptions options = new(Path.Combine(root.FullName, "missing.exe"), root.FullName, root.FullName, first);
            var controller = new InputRecordingController(Environment.ProcessPath!, [typeof(InputRecordingSpecs).Assembly.Location]);
            try
            {
                Wait(controller.StartAsync(options, elevate: false)); var pid = controller.ProcessId;
                Until(() => controller.Status.Get("input_received") is EvidenceObject input && input.Get("key") is EvidenceInteger { Value: var count } && count >= 2);
                check(controller.Running && pid.HasValue && Text(controller.Status, "status") == "recording", "A real child authenticates its owned pipe and publishes status after recording synthetic inputs");
                var copied = controller.Status; ((Dictionary<string, EvidenceValue>)copied.Fields)["status"] = new EvidenceText("changed");
                check(Text(controller.Status, "status") == "recording", "Parent status snapshots cannot mutate the running recorder");
                Wait(controller.SetTraceAsync(second)); Until(() => Text(controller.Status, "path") == InputLogWriter.Companion(second));
                Wait(controller.StopAsync());
                check(!controller.Running && Text(controller.Status, "status") == "stopped", "Stop waits for the actual recorder process and preserves its terminal state");
                var archive = new InputArchive(InputLogWriter.Companion(first));
                check(archive.Actions.Count == 1 && archive.Actions[0].Action == "combo" && archive.VerifyTrace(first).Length > 0
                    && Read(InputLogWriter.Companion(second)).Any(row => Text(row, "type") == "end"), "Process rotation and shutdown produce valid, closed, production-readable sidecars");
                Wait(controller.StartAsync(options, elevate: false)); Until(() => Text(controller.Status, "status") == "recording");
                check(controller.ProcessId != pid, "Recording can restart with a new owned process after the previous pipe and worker finish");
                check(Text(controller.Status, "path").StartsWith(InputLogWriter.Companion(second)[..^".input.jsonl".Length], StringComparison.Ordinal),
                    "Trace association selected before restart is retained for the next recorder session");
                Wait(controller.StopAsync());
            }
            finally { Wait(controller.DisposeAsync().AsTask()); }

            var pipeName = "EndfieldInputSpec_" + Guid.NewGuid().ToString("N"); var key = RandomNumberGenerator.GetBytes(32);
            using NamedPipeServerStream server = new(pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            using var child = System.Diagnostics.Process.Start(StartInfo(pipeName, Convert.ToHexString(key), Environment.ProcessId))!;
            var stderr = child.StandardError.ReadToEndAsync();
            Wait(server.WaitForConnectionAsync()); using CancellationTokenSource handshake = new(Timeout);
            Wait(InputWorkerPipe.AuthenticateServerAsync(server, key, child.Id, handshake.Token));
            var channel = new InputWorkerPipe(server); var orphanTrace = Path.Combine(root.FullName, "parent-eof.log"); File.WriteAllText(orphanTrace, "prefix\n");
            Wait(channel.SendAsync(InputWorkerHost.Configuration(options with { Trace = orphanTrace })));
            UntilStatus(channel, "recording"); Wait(channel.DisposeAsync().AsTask()); Wait(child.WaitForExitAsync()); Wait(stderr);
            check(child.ExitCode == 0 && Read(InputLogWriter.Companion(orphanTrace)).Any(row => Text(row, "type") == "end"), "Parent pipe EOF stops the child and closes its recording without leaving an orphan");
            if (OperatingSystem.IsWindows())
            {
                List<NativeInputReport> reports = [];
                using (WindowsInputSource native = new(Path.Combine(root.FullName, "missing.exe"), reports.Add))
                { native.Pump(); Thread.Sleep(30); native.Pump(); check(native.Health["message_thread_alive"] is true, "Real Windows message window, raw registration and passive hooks initialize without a game"); }
                check(reports.All(report => report.Type != "input"), "A nonexistent target executable never retains another application's input");
            }
        }
        finally { root.Delete(true); }
    }
    private static void UntilStatus(InputWorkerPipe pipe, string status)
    {
        using CancellationTokenSource timeout = new(Timeout);
        while (Text(Wait(pipe.ReceiveAsync(timeout.Token)), "status") != status) { }
    }
    public static void Pipe(Action<bool, string> check)
    {
        foreach (var length in new[] { -1, 0, InputWorkerPipe.Limit + 1 })
        {
            byte[] header = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(header, length);
            var pipe = new InputWorkerPipe(new MemoryStream(header)); var refused = false;
            try { Wait(pipe.ReceiveAsync()); } catch (InvalidDataException) { refused = true; }
            finally { Wait(pipe.DisposeAsync().AsTask()); }
            check(refused, "Invalid frame length is rejected before allocating the payload: " + length);
        }
        var invalid = false; try { InputWorkerHost.ParseConfiguration(Obj("""{"command":"shell","game_exe":"x"}""")); } catch (InvalidDataException) { invalid = true; }
        check(invalid, "Worker initialization accepts a configuration object rather than executable commands");
        foreach (var mode in new[] { "valid", "wrong-key", "wrong-child", "wrong-parent" })
        {
            var result = Wait(Handshake(mode));
            check(mode == "valid" ? result.Server is null && result.Client is null : result.Server is UnauthorizedAccessException || result.Client is UnauthorizedAccessException,
                "Real local pipe authentication enforces owned peer identities and a per-launch secret: " + mode);
        }
    }
    private static async Task<(Exception? Server, Exception? Client)> Handshake(string mode)
    {
        var name = "EndfieldInputAuth_" + Guid.NewGuid().ToString("N"); var key = RandomNumberGenerator.GetBytes(32);
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(3));
        var serverWork = Task.Run(async () =>
        {
            await using NamedPipeServerStream server = new(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            try
            {
                await server.WaitForConnectionAsync(timeout.Token);
                await InputWorkerPipe.AuthenticateServerAsync(server, key, mode == "wrong-child" ? int.MaxValue : Environment.ProcessId, timeout.Token);
                await using InputWorkerPipe pipe = new(server);
                await pipe.SendAsync(Obj("""{"command":"configure"}"""), timeout.Token);
                await pipe.ReceiveAsync(timeout.Token); return (Exception?)null;
            }
            catch (Exception error) { return error; }
        });
        var clientWork = Task.Run(async () =>
        {
            await using NamedPipeClientStream client = new(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
            try
            {
                await client.ConnectAsync(timeout.Token);
                await InputWorkerPipe.AuthenticateClientAsync(client, mode == "wrong-key" ? RandomNumberGenerator.GetBytes(32) : key,
                    mode == "wrong-parent" ? int.MaxValue : Environment.ProcessId, timeout.Token);
                await using InputWorkerPipe pipe = new(client);
                await pipe.ReceiveAsync(timeout.Token); await pipe.SendAsync(Obj("""{"status":"stopped"}"""), timeout.Token); return (Exception?)null;
            }
            catch (Exception error) { return error; }
        });
        await Task.WhenAll(serverWork, clientWork); return (serverWork.Result, clientWork.Result);
    }
}
