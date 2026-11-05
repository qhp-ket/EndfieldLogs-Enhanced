using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Threading.Channels;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

/// <summary>Worker entry used before WPF startup. The parent receives status, never raw input.</summary>
public static class InputWorkerHost
{
    public static EvidenceObject Configuration(InputRecordingOptions options) => TraceData.Make(("command", "configure"), ("game_exe", options.GameExecutable),
        ("log_dir", options.LogDirectory), ("native_dir", options.NativeDirectory), ("trace", options.Trace));
    public static InputRecordingOptions ParseConfiguration(EvidenceObject value)
    {
        if (value.Get("command") is not EvidenceText { Value: "configure" }) throw new InvalidDataException("输入服务初始化命令无效");
        string Required(string key) => value.Get(key) is EvidenceText { Value.Length: > 0 } text ? Path.GetFullPath(text.Value) : throw new InvalidDataException("输入服务配置缺少 " + key);
        return new(Required("game_exe"), Required("log_dir"), Required("native_dir"), value.Get("trace") is EvidenceText { Value.Length: > 0 } trace ? Path.GetFullPath(trace.Value) : null);
    }
    public static async Task<int> ConnectAsync(string name, int parentPid, string secret,
        Func<InputRecordingOptions, IInputForeground>? foregroundFactory = null,
        Func<InputRecordingOptions, Action<string, EvidenceObject>, IReadOnlyList<IInputBackend>>? backendFactory = null)
    {
        using CancellationTokenSource handshake = new(TimeSpan.FromSeconds(30));
        await using NamedPipeClientStream stream = new(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
        await stream.ConnectAsync(handshake.Token).ConfigureAwait(false);
        var key = Convert.FromHexString(secret); if (key.Length != 32) throw new InvalidDataException("输入服务认证参数无效");
        await InputWorkerPipe.AuthenticateClientAsync(stream, key, parentPid, handshake.Token).ConfigureAwait(false);
        Array.Clear(key);
        await using InputWorkerPipe pipe = new(stream);
        var options = ParseConfiguration(await pipe.ReceiveAsync(handshake.Token).ConfigureAwait(false));
        return await Task.Run(() => Run(pipe, options, foregroundFactory, backendFactory)).ConfigureAwait(false);
    }
    private static int Run(InputWorkerPipe pipe, InputRecordingOptions options, Func<InputRecordingOptions, IInputForeground>? foregroundFactory,
        Func<InputRecordingOptions, Action<string, EvidenceObject>, IReadOnlyList<IInputBackend>>? backendFactory)
    {
        // Commands are deliberately a small mailbox. A closed parent always requests shutdown.
        var commands = Channel.CreateBounded<EvidenceObject>(new BoundedChannelOptions(64) { SingleReader = true, SingleWriter = true });
        using CancellationTokenSource communication = new();
        var reader = Task.Run(async () =>
        {
            try
            {
                while (true)
                {
                    var command = await pipe.ReceiveAsync(communication.Token).ConfigureAwait(false);
                    if (command.Get("command") is not EvidenceText { Value: "stop" or "trace" }) throw new InvalidDataException("输入服务命令无效");
                    await commands.Writer.WriteAsync(command, communication.Token).ConfigureAwait(false);
                }
            }
            catch (Exception error) when (error is IOException or OperationCanceledException or FormatException or InvalidDataException) { }
            finally { commands.Writer.TryComplete(); }
        });
        InputRecorder? recorder = null; List<IInputBackend> backends = []; Exception? failure = null;
        try
        {
            var target = foregroundFactory?.Invoke(options) ?? (OperatingSystem.IsWindows() ? new WindowsInputForeground(options.GameExecutable) : throw new PlatformNotSupportedException());
            recorder = new(options, target, OperatingSystem.IsWindows() && IsUserAnAdmin()); recorder.Rotate(options.Trace);
            if (backendFactory is not null) backends.AddRange(backendFactory(options, recorder.Emit));
            else
            {
                if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
                backends.Add(new WindowsInputBackend(options.GameExecutable, recorder.Emit));
                try { backends.Add(new SdlInputBackend(options.NativeDirectory, recorder.Emit)); }
                catch (Exception error) { recorder.Emit("error", TraceData.Make(("message", "手柄记录不可用：" + error.Message))); }
            }
            var checkedAt = long.MinValue; var diagnosedAt = long.MinValue; var sentAt = long.MinValue; string? published = null; var active = true;
            while (active && !commands.Reader.Completion.IsCompleted)
            {
                recorder.CheckFocus();
                while (commands.Reader.TryRead(out var command))
                {
                    if (command.Get("command") is EvidenceText { Value: "stop" }) { active = false; break; }
                    var trace = command.Get("path") is EvidenceText text ? text.Value : null;
                    if (trace != recorder.Trace) recorder.Rotate(trace);
                }
                if (!active) break;
                foreach (var backend in backends) backend.Pump();
                if (recorder.WriterError is { } writerError) throw new IOException("输入日志写入失败", writerError);
                var now = Environment.TickCount64;
                if (diagnosedAt == long.MinValue || now - diagnosedAt >= 5000)
                {
                    diagnosedAt = now; var health = backends.FirstOrDefault()?.Health ?? TraceData.Make(); var fields = health.Fields.ToDictionary();
                    fields["reason"] = new EvidenceText("input_backend_health"); recorder.Emit("diagnostic", new(fields));
                }
                if (checkedAt == long.MinValue || now - checkedAt >= 100)
                {
                    checkedAt = now; var status = recorder.Status(backends.FirstOrDefault()); var json = TraceData.Json(status);
                    if (json != published || sentAt == long.MinValue || now - sentAt >= 5000)
                    { Send(status); published = json; sentAt = now; }
                }
                // No disk/SDL work on message dispatch. The worker wakes at the reference's focus cadence.
                communication.Token.WaitHandle.WaitOne(recorder.Focused ? 8 : 50);
            }
        }
        catch (Exception error)
        {
            failure = error;
            try { recorder?.Emit("error", TraceData.Make(("fatal", true), ("message", error.GetType().Name + ": " + error.Message))); } catch (Exception) { }
        }
        finally
        {
            foreach (var backend in backends.AsEnumerable().Reverse())
                try { backend.Dispose(); } catch (Exception error) { failure ??= error; }
            try { recorder?.Close(failure is null ? "stopped" : "error"); } catch (Exception error) { failure ??= error; }
            try
            {
                var terminal = (recorder?.Status() ?? TraceData.Make()).Fields.ToDictionary();
                terminal["status"] = new EvidenceText(failure is null ? "stopped" : "error");
                if (failure is not null) terminal["error"] = new EvidenceText(failure.Message);
                Send(new(terminal));
            }
            catch (Exception) { }
            communication.Cancel(); try { reader.GetAwaiter().GetResult(); } catch (Exception) { }
        }
        return failure is null ? 0 : 1;
        void Send(EvidenceObject status)
        { using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(2)); pipe.SendAsync(status, timeout.Token).GetAwaiter().GetResult(); }
    }
    [DllImport("shell32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsUserAnAdmin();
}
