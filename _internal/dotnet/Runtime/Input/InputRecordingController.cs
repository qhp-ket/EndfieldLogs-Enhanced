using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Cryptography;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public interface IInputRecordingService : IAsyncDisposable
{
    EvidenceObject Status { get; }
    bool Running { get; }
    Task StartAsync(InputRecordingOptions options, bool elevate = true, CancellationToken token = default);
    Task SetTraceAsync(string? trace, CancellationToken token = default);
    Task StopAsync();
}

/// <summary>Owns just the recorder process and status pipe. No GUI or capture-service dependency.</summary>
public sealed class InputRecordingController(string executable, IReadOnlyList<string>? arguments = null) : IInputRecordingService
{
    private readonly SemaphoreSlim lifecycle = new(1, 1);
    private readonly object gate = new();
    private Process? process;
    private InputWorkerPipe? pipe;
    private Task? reader;
    private CancellationTokenSource? lifetime;
    private EvidenceObject status = TraceData.Make(("status", "stopped"), ("count", 0), ("lost", 0));
    private bool disposed;
    private bool traceSelected;
    private string? selectedTrace;
    private InputRecordingOptions? recordingOptions;
    public EvidenceObject Status { get { lock (gate) return (EvidenceObject)EvidenceJson.Clone(status); } }
    public bool Running { get { lock (gate) return process is { HasExited: false }; } }
    public int? ProcessId { get { lock (gate) return process is { HasExited: false } p ? p.Id : null; } }
    private void Publish(EvidenceObject value) { lock (gate) status = (EvidenceObject)EvidenceJson.Clone(value); }

    public async Task StartAsync(InputRecordingOptions options, bool elevate = true, CancellationToken token = default)
    {
        await lifecycle.WaitAsync(token).ConfigureAwait(false);
        try
        {
            ObjectDisposedException.ThrowIf(disposed, this); if (Running) return;
            await CleanupAsync().ConfigureAwait(false);
            if (traceSelected) options = options with { Trace = selectedTrace };
            recordingOptions = options;
            Publish(TraceData.Make(("status", "starting"), ("count", 0), ("lost", 0)));
            PrepareDirectory(options, options.Trace);
            var name = "EndfieldInput_" + Guid.NewGuid().ToString("N"); var secret = RandomNumberGenerator.GetBytes(32);
            NamedPipeServerStream server = new(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            InputWorkerPipe channel = new(server); Process? owned = null;
            lifetime = new();
            try
            {
                ProcessStartInfo start = new(Path.GetFullPath(executable)) { UseShellExecute = elevate, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                if (elevate) start.Verb = "runas";
                foreach (var argument in arguments ?? []) start.ArgumentList.Add(argument);
                start.ArgumentList.Add("--input-worker"); start.ArgumentList.Add(name); start.ArgumentList.Add(Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture));
                start.ArgumentList.Add(Convert.ToHexStringLower(secret));
                owned = Process.Start(start) ?? throw new IOException("输入记录进程未能启动");
                lock (gate) { process = owned; pipe = channel; }
                using var handshake = CancellationTokenSource.CreateLinkedTokenSource(token, lifetime.Token); handshake.CancelAfter(TimeSpan.FromSeconds(30));
                var connected = server.WaitForConnectionAsync(handshake.Token); var exited = owned.WaitForExitAsync(handshake.Token);
                if (await Task.WhenAny(connected, exited).ConfigureAwait(false) != connected) throw new IOException("输入记录进程在连接前退出");
                await connected.ConfigureAwait(false);
                await InputWorkerPipe.AuthenticateServerAsync(server, secret, owned.Id, handshake.Token).ConfigureAwait(false);
                await channel.SendAsync(InputWorkerHost.Configuration(options), handshake.Token).ConfigureAwait(false);
                // Cancel the unused process-exit observation after the handshake; the reader owns it next.
                handshake.Cancel();
                reader = ReadAsync(owned, channel, lifetime.Token);
            }
            catch (Exception error)
            {
                Publish(TraceData.Make(("status", "error"), ("count", 0), ("lost", 0), ("error", error.Message)));
                if (owned is not null) await StopOwnedAsync(owned, TimeSpan.FromSeconds(1)).ConfigureAwait(false);
                await channel.DisposeAsync().ConfigureAwait(false); owned?.Dispose(); lock (gate) { process = null; pipe = null; }
                lifetime.Dispose(); lifetime = null; throw;
            }
            finally { Array.Clear(secret); }
        }
        finally { lifecycle.Release(); }
    }
    private async Task ReadAsync(Process owned, InputWorkerPipe channel, CancellationToken token)
    {
        try
        {
            while (true)
            {
                var message = await channel.ReceiveAsync(token).ConfigureAwait(false);
                if (message.Get("status") is not EvidenceText { Value: "recording" or "waiting_game" or "stopped" or "error" }) throw new InvalidDataException("输入服务状态无效");
                lock (gate) if (ReferenceEquals(process, owned)) status = (EvidenceObject)EvidenceJson.Clone(message);
            }
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or FormatException or InvalidDataException)
        {
            // Closing the connection also stops the worker; never leave a private recorder detached.
            await channel.DisposeAsync().ConfigureAwait(false);
            await StopOwnedAsync(owned, TimeSpan.FromSeconds(5)).ConfigureAwait(false);
            lock (gate)
            {
                if (!ReferenceEquals(process, owned)) return;
                if (status.Get("status") is not EvidenceText { Value: "error" })
                {
                    var fields = status.Fields.ToDictionary(); fields["status"] = new EvidenceText(owned.HasExited && owned.ExitCode == 0 ? "stopped" : "error");
                    if (owned.HasExited && owned.ExitCode != 0) fields["error"] = new EvidenceText($"输入记录进程异常退出（{owned.ExitCode}）");
                    status = new(fields);
                }
            }
        }
    }
    public async Task SetTraceAsync(string? trace, CancellationToken token = default)
    {
        await lifecycle.WaitAsync(token).ConfigureAwait(false);
        try
        {
            selectedTrace = trace is null ? null : Path.GetFullPath(trace); traceSelected = true;
            if (pipe is null || !Running) return;
            if (recordingOptions is not null) PrepareDirectory(recordingOptions, selectedTrace);
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token); timeout.CancelAfter(TimeSpan.FromSeconds(2));
            await pipe.SendAsync(TraceData.Make(("command", "trace"), ("path", selectedTrace)), timeout.Token).ConfigureAwait(false);
        }
        finally { lifecycle.Release(); }
    }
    public async Task StopAsync()
    {
        await lifecycle.WaitAsync().ConfigureAwait(false);
        try
        {
            if (pipe is not null && Running)
                try { using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(1)); await pipe.SendAsync(TraceData.Make(("command", "stop")), timeout.Token).ConfigureAwait(false); }
                catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
            if (process is { } owned) await StopOwnedAsync(owned, TimeSpan.FromSeconds(8)).ConfigureAwait(false);
            await CleanupAsync().ConfigureAwait(false);
        }
        finally { lifecycle.Release(); }
    }
    private async Task CleanupAsync()
    {
        lifetime?.Cancel();
        if (reader is not null) await reader.ConfigureAwait(false);
        else if (pipe is not null) await pipe.DisposeAsync().ConfigureAwait(false);
        lock (gate) { process?.Dispose(); process = null; pipe = null; } reader = null; lifetime?.Dispose(); lifetime = null;
    }
    private static async Task StopOwnedAsync(Process process, TimeSpan grace)
    {
        try
        {
            if (process.HasExited) return;
            try { await process.WaitForExitAsync().WaitAsync(grace).ConfigureAwait(false); return; } catch (TimeoutException) { }
            process.Kill(); await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(3)).ConfigureAwait(false);
        }
        catch (Exception error) when (error is InvalidOperationException or System.ComponentModel.Win32Exception or TimeoutException) { }
    }
    private static void PrepareDirectory(InputRecordingOptions options, string? trace)
        => Directory.CreateDirectory(trace is null ? Path.Combine(options.LogDirectory, DateTime.Now.ToString("yyyyMMdd")) : Path.GetDirectoryName(Path.GetFullPath(trace))!);
    public async ValueTask DisposeAsync() { if (disposed) return; disposed = true; await StopAsync().ConfigureAwait(false); lifecycle.Dispose(); }
}
