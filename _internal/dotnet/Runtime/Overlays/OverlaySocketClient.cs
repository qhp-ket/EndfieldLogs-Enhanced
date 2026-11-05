using System.Net.WebSockets;
using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.Overlays;

public sealed record OverlayTransportState(string Status, string? Error, IReadOnlyList<EvidenceObject> Messages);

/// <summary>Loopback-only native transport with bounded per-topic mailboxes and cancellation through connect/receive/backoff.</summary>
public sealed class OverlaySocketClient : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly Uri endpoint;
    private readonly CancellationTokenSource lifetime = new();
    private readonly Dictionary<string, EvidenceObject> pending = new(StringComparer.Ordinal);
    private readonly OverlaySnapshotGate summary = new(), combo = new();
    private readonly TimeSpan reconnectDelay;
    private Task? worker;
    private Task? shutdown;
    private bool closed;
    private string status = "未连接";
    private string? error;
    public OverlaySocketClient(int port, string token = "", TimeSpan? reconnectDelay = null, IReadOnlySet<string>? subscriptions = null)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(port, 1); ArgumentOutOfRangeException.ThrowIfGreaterThan(port, 65535);
        subscriptions ??= new HashSet<string>(["analysis_summary", "combo_snapshot"], StringComparer.Ordinal);
        endpoint = new($"ws://127.0.0.1:{port}/ws?analysis=" + (subscriptions.Contains("analysis_summary") ? "summary" : "none")
            + (subscriptions.Contains("combo_snapshot") ? "&combo=1" : "&combo=0") + (token.Length > 0 ? "&access_token=" + Uri.EscapeDataString(token) : ""));
        this.reconnectDelay = reconnectDelay ?? TimeSpan.FromSeconds(1.5);
    }
    public void Start() { lock (gate) { ObjectDisposedException.ThrowIf(closed, this); worker ??= Task.Run(RunAsync); } }
    public OverlayTransportState Poll()
    {
        lock (gate)
        {
            var messages = pending.Values.ToArray(); pending.Clear();
            return new(status, error, messages);
        }
    }
    private void State(string value, string? detail = null) { lock (gate) { status = value; error = detail; } }
    private void Post(EvidenceObject message)
    {
        var type = (message.Get("type") as EvidenceText)?.Value;
        if (type == "hello")
        { message = new(new Dictionary<string, EvidenceValue> { ["type"] = new EvidenceText("recording_state"), ["recording"] = message.Get("recording") }); type = "recording_state"; }
        if (!(type == "recording_state" || type == "analysis_summary" && summary.Accept(message, type, 1) || type == "combo_snapshot" && combo.Accept(message, type, 2))) return;
        lock (gate) if (!lifetime.IsCancellationRequested) pending[type!] = message;
    }
    private async Task RunAsync()
    {
        var token = lifetime.Token;
        try
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    State("正在连接"); using ClientWebSocket socket = new(); socket.Options.Proxy = null;
                    using (var connect = CancellationTokenSource.CreateLinkedTokenSource(token))
                    { connect.CancelAfter(TimeSpan.FromSeconds(2)); await socket.ConnectAsync(endpoint, connect.Token).ConfigureAwait(false); }
                    State("已连接"); byte[] buffer = new byte[8192];
                    while (socket.State == WebSocketState.Open)
                    {
                        using MemoryStream content = new(); WebSocketReceiveResult part;
                        do
                        {
                            part = await socket.ReceiveAsync(buffer, token).ConfigureAwait(false);
                            if (part.MessageType == WebSocketMessageType.Close) break;
                            if (content.Length + part.Count > 1024 * 1024) throw new InvalidDataException("浮窗快照超过 1 MiB");
                            content.Write(buffer, 0, part.Count);
                        } while (!part.EndOfMessage);
                        if (part.MessageType == WebSocketMessageType.Close) break;
                        if (part.MessageType == WebSocketMessageType.Text && EvidenceJson.Parse(new UTF8Encoding(false, true).GetString(content.ToArray())) is EvidenceObject message) Post(message);
                    }
                    State("连接断开");
                }
                catch (Exception failure) when (!token.IsCancellationRequested && failure is WebSocketException or IOException or OperationCanceledException or FormatException or DecoderFallbackException)
                { State("连接断开", failure.Message); }
                await Task.Delay(reconnectDelay, token).ConfigureAwait(false);
            }
        }
        catch (Exception failure) when (token.IsCancellationRequested && failure is OperationCanceledException or WebSocketException or IOException) { }
        finally { State("已停止"); }
    }
    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            if (shutdown is not null) return new(shutdown);
            closed = true; lifetime.Cancel(); shutdown = FinishAsync(worker); return new(shutdown);
        }
    }
    private async Task FinishAsync(Task? running)
    { try { if (running is not null) await running.ConfigureAwait(false); } finally { lock (gate) { pending.Clear(); status = "已停止"; } lifetime.Dispose(); } }
}
