using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Threading.Channels;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Runtime.Realtime;

/// <summary>Loopback WebSocket transport with per-client bounded delivery and no external HTTP runtime.</summary>
public sealed class LoopbackWebSocketServer(int port, string browserToken, Func<bool, LiveAnalysisSubscription> subscribe,
    Func<Dictionary<string, object?>> hello, Action? onBatch = null)
{
    private sealed class Client
    {
        public readonly Channel<string> Messages = Channel.CreateBounded<string>(new BoundedChannelOptions(1024) { SingleReader = true });
        public readonly CancellationTokenSource Stop = new();
        public readonly Channel<string> Visual = Channel.CreateBounded<string>(new BoundedChannelOptions(1) { FullMode = BoundedChannelFullMode.DropOldest });
        public bool Combo;
        public bool ReceiveCombo;
    }
    private readonly object gate = new(), eventGate = new();
    private readonly HashSet<Client> clients = [];
    private readonly List<BattleLogEvent> batch = [];
    private bool started;
    private readonly OverlaySnapshotGate comboGate = new();
    private string? latestCombo;
    public bool HasComboSubscribers { get { lock (gate) return clients.Any(client => client.Combo); } }
    public Uri? Endpoint { get; private set; }

    public void BroadcastHello() => Broadcast(JsonContract.Serialize(hello()));
    public void PublishCombo(EvidenceObject message)
    {
        lock (gate)
        {
            if (message.Get("snapshot") is not EvidenceObject snapshot || snapshot.Get("slots") is not EvidenceArray || !comboGate.Accept(message, "combo_snapshot", 2)) return;
            latestCombo = TraceData.Json(message);
            foreach (var client in clients.Where(client => client.ReceiveCombo)) client.Visual.Writer.TryWrite(latestCombo);
        }
    }

    private void Broadcast(string message)
    {
        lock (gate)
            foreach (var client in clients)
                if (!client.Messages.Writer.TryWrite(message)) client.Stop.Cancel();
    }

    public void PublishEvent(BattleLogEvent value)
    {
        lock (eventGate)
        {
            batch.Add(value);
            if (batch.Count >= 128) FlushEvents();
        }
    }

    private void FlushEvents()
    {
        lock (eventGate)
        {
            if (batch.Count == 0) return;
            var payload = TraceData.Make(("type", "event_batch"), ("session_id", batch[^1].SessionId),
                ("sent_at_ms", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), ("events", batch.Select(value => value.ToPayload()).ToArray()));
            Broadcast(TraceData.Json(payload)); batch.Clear(); onBatch?.Invoke();
        }
    }

    public async Task RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate) { if (started) throw new InvalidOperationException("WebSocket server can only run once"); started = true; }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        using TcpListener listener = new(IPAddress.Loopback, port);
        List<Task> handlers = [];
        async Task FlushLoop()
        {
            try { while (true) { await Task.Delay(100, lifetime.Token).ConfigureAwait(false); FlushEvents(); } }
            catch { lifetime.Cancel(); throw; }
        }
        Task? flush = null;
        try
        {
            listener.Start(); Endpoint = new("ws://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/");
            flush = FlushLoop();
            while (true)
            {
                var client = await listener.AcceptTcpClientAsync(lifetime.Token).ConfigureAwait(false);
                handlers.RemoveAll(task => task.IsCompleted);
                if (handlers.Count >= 64) { client.Dispose(); continue; }
                handlers.Add(HandleAsync(client, lifetime.Token));
            }
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
        finally
        {
            lifetime.Cancel(); listener.Stop();
            await Task.WhenAll(handlers).ConfigureAwait(false);
            if (flush is not null)
                try { await flush.ConfigureAwait(false); } catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            FlushEvents();
        }
    }

    private async Task HandleAsync(TcpClient tcp, CancellationToken cancellationToken)
    {
        using (tcp)
        using (var handshake = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken))
        {
            Client client = new();
            try
            {
                tcp.NoDelay = true; handshake.CancelAfter(TimeSpan.FromSeconds(5));
                var network = tcp.GetStream();
                List<byte> header = []; byte[] one = new byte[1];
                // Read through CRLFCRLF exactly; an eager client may already have queued its first WebSocket frame.
                while (header.Count < 16_384)
                {
                    if (await network.ReadAsync(one, handshake.Token).ConfigureAwait(false) == 0) return;
                    header.Add(one[0]);
                    if (header.Count >= 4 && header[^4] == 13 && header[^3] == 10 && header[^2] == 13 && header[^1] == 10) break;
                }
                var request = LoopbackWebSocketRequest.Parse(Encoding.Latin1.GetString(header.ToArray()), browserToken, out var status);
                if (header.Count == 16_384 || request is null)
                {
                    if (header.Count == 16_384) status = 400;
                    var reason = status == 403 ? "Forbidden" : "Bad Request";
                    await network.WriteAsync(Encoding.ASCII.GetBytes($"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"), handshake.Token).ConfigureAwait(false);
                    return;
                }
                using var subscription = request.Analysis ? subscribe(request.Summary) : null;
                await network.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "
                    + request.Accept + "\r\n\r\n"), handshake.Token).ConfigureAwait(false);
                using var socket = WebSocket.CreateFromStream(network, isServer: true, subProtocol: null, keepAliveInterval: Timeout.InfiniteTimeSpan);
                using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, client.Stop.Token);
                using SemaphoreSlim sendGate = new(1, 1);
                lock (gate)
                {
                    client.Combo = request.Combo; client.ReceiveCombo = request.ReceiveCombo; clients.Add(client);
                    if (request.ReceiveCombo && latestCombo is not null) client.Visual.Writer.TryWrite(latestCombo);
                }
                async ValueTask Send(string message)
                {
                    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                    timeout.CancelAfter(TimeSpan.FromSeconds(1));
                    await sendGate.WaitAsync(timeout.Token).ConfigureAwait(false);
                    try { await socket.SendAsync(Encoding.UTF8.GetBytes(message), WebSocketMessageType.Text, true, timeout.Token).ConfigureAwait(false); }
                    finally { sendGate.Release(); }
                }
                async Task WriteLoop()
                {
                    await Send(JsonContract.Serialize(hello())).ConfigureAwait(false);
                    static async Task<LiveSnapshotFrame?> NoAnalysis(CancellationToken token) { await Task.Delay(Timeout.InfiniteTimeSpan, token).ConfigureAwait(false); return null; }
                    while (true)
                    {
                        using var wake = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                        var analysis = subscription?.ReadAsync(wake.Token).AsTask() ?? NoAnalysis(wake.Token);
                        var control = client.Messages.Reader.WaitToReadAsync(wake.Token).AsTask();
                        var visual = client.Visual.Reader.WaitToReadAsync(wake.Token).AsTask();
                        await Task.WhenAny(analysis, control, visual).ConfigureAwait(false);
                        wake.Cancel();
                        try { await Task.WhenAll(analysis, control, visual).ConfigureAwait(false); }
                        catch (OperationCanceledException) when (!lifetime.IsCancellationRequested) { }
                        lifetime.Token.ThrowIfCancellationRequested();
                        if (analysis.IsCompletedSuccessfully)
                        {
                            if (analysis.Result is null) return;
                            await Send(PythonSortedJson.Serialize(analysis.Result.ToEvidence(), compact: true)).ConfigureAwait(false);
                        }
                        while (client.Messages.Reader.TryRead(out var message)) await Send(message).ConfigureAwait(false);
                        while (client.Visual.Reader.TryRead(out var message)) await Send(message).ConfigureAwait(false);
                    }
                }
                async Task ReadLoop()
                {
                    byte[] buffer = new byte[4096]; var size = 0;
                    while (true)
                    {
                        var result = await socket.ReceiveAsync(buffer, lifetime.Token).ConfigureAwait(false);
                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token); timeout.CancelAfter(1000);
                            await sendGate.WaitAsync(timeout.Token).ConfigureAwait(false);
                            try { await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", timeout.Token).ConfigureAwait(false); }
                            finally { sendGate.Release(); }
                            return;
                        }
                        size += result.Count;
                        if (size > 65_536) throw new IOException("WebSocket client message exceeds service limit");
                        if (result.EndOfMessage) size = 0;
                    }
                }
                var send = WriteLoop(); var receive = ReadLoop();
                try { await Task.WhenAny(send, receive).ConfigureAwait(false); }
                finally
                {
                    lifetime.Cancel();
                    try { await Task.WhenAll(send, receive).ConfigureAwait(false); }
                    catch (Exception error) when (error is OperationCanceledException or WebSocketException or IOException) { }
                }
            }
            catch (Exception error) when (error is OperationCanceledException or IOException or WebSocketException or InvalidOperationException) { }
            finally
            {
                lock (gate) clients.Remove(client);
                client.Stop.Dispose();
            }
        }
    }
}
