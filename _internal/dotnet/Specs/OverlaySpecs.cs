using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Overlays;
using EndfieldLogs.Runtime.Realtime;

internal static class OverlaySpecs
{
    private static EvidenceObject Object(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static EvidenceObject Message(string stream, int sequence, int value) => Object("{\"type\":\"analysis_summary\",\"schema_version\":1,\"stream_id\":\"" + stream + "\",\"sequence\":" + sequence + ",\"snapshot\":{\"value\":" + value + "}}");
    public static void Run(Action<bool, string> check)
    {
        OverlaySnapshotGate gate = new();
        check(gate.Accept(Message("a", 1, 1), "analysis_summary", 1) && !gate.Accept(Message("a", 1, 2), "analysis_summary", 1)
            && !gate.Accept(Message("a", 0, 3), "analysis_summary", 1), "Duplicate and reversed frames cannot replace a newer snapshot");
        check(gate.Accept(Message("b", 0, 2), "analysis_summary", 1) && !gate.Accept(Message("a", 2, 9), "analysis_summary", 1), "A retired stream cannot revive after a publisher reset");
        check(!gate.Accept(Object("""{"type":"analysis_summary","schema_version":1,"stream_id":"b","sequence":true,"snapshot":{}}"""), "analysis_summary", 1)
            && !gate.Accept(Object("""{"type":"analysis_summary","schema_version":1,"stream_id":"b","sequence":1,"snapshot":[]}"""), "analysis_summary", 1), "Malformed sequence and snapshot envelopes are rejected before advancing the stream");
        OverlayFeed feed = new(); var notifications = 0; feed.Changed += (_, _) => notifications++;
        feed.Receive(Message("live", 0, 1)); feed.ShowHistory(Object("{\"value\":5}"), "history"); feed.Receive(Message("live", 1, 2));
        check((feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("value") is EvidenceInteger { Value: var v } && v == 5 && notifications == 2,
            "Live updates remain private while a historical report is presented");
        var historical = feed.Damage;
        check(feed.Receive(Object("""{"type":"recording_state","recording":true}""")) && feed.Recording
            && ReferenceEquals(feed.Damage, historical), "Recording status changes immediately while keeping the historical snapshot");
        check(!feed.Receive(Object("""{"type":"recording_state","recording":true}""")), "Unchanged recording state does not repaint");
        feed.ReturnLive();
        check((feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("value") is EvidenceInteger { Value: var current } && current == 2,
            "Returning to live presents the newest accepted compact result");
        feed.ClearLive();
        check(feed.Damage?.Get("snapshot") is EvidenceNull && !feed.Historical, "Capture stop clears live presentation without reviving an older report");
        feed.Receive(Object("""{"type":"combo_snapshot","schema_version":2,"stream_id":"vision","sequence":0,"snapshot":{"slots":[]}}"""));
        check(feed.Combo is not null && !feed.Receive(Object("""{"type":"combo_snapshot","schema_version":2,"stream_id":"vision","sequence":1,"snapshot":null}""")), "Visual snapshots require their own schema and slot array");
        VerifySnapshotOwnership(check);
        TransportAsync(check).GetAwaiter().GetResult();
    }
    private static void VerifySnapshotOwnership(Action<bool, string> check)
    {
        var producer = Object("""{"type":"analysis_summary","schema_version":1,"stream_id":"owned","sequence":0,"snapshot":{"rows":[{"value":3}]},"error":{"detail":"original"}}""");
        OverlayFeed feed = new(); EvidenceObject? delivered = null;
        feed.Changed += (_, message) => delivered = message;
        feed.Receive(producer);
        var first = feed.Damage!; var captured = (EvidenceObject)first.Get("snapshot");
        var rows = (EvidenceArray)captured.Get("rows");
        var sourceRows = (EvidenceArray)((EvidenceObject)producer.Get("snapshot")).Get("rows");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)sourceRows.Items[0]).Fields)["value"] = new EvidenceInteger(999);
        ((List<EvidenceValue>)sourceRows.Items).Clear();
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)producer.Get("error")).Fields)["detail"] = new EvidenceText("changed");
        check(ReferenceEquals(delivered, first) && rows.Items.Count == 1
            && ((EvidenceObject)rows.Items[0]).Get("value") is EvidenceInteger { Value: var value } && value == 3
            && ((EvidenceObject)first.Get("error")).Get("detail") is EvidenceText { Value: "original" },
            "A single mailbox capture isolates nested producer mutations for every window");
        bool Rejects(Action change)
        {
            try { change(); return false; } catch (NotSupportedException) { return true; }
        }
        check(Rejects(() => ((IDictionary<string, EvidenceValue>)first.Fields).Clear())
            && Rejects(() => ((IList<EvidenceValue>)rows.Items).Clear())
            && Rejects(() => ((IDictionary<string, EvidenceValue>)((EvidenceObject)rows.Items[0]).Fields).Clear())
            && Rejects(() => ((IDictionary<string, EvidenceValue>)((EvidenceObject)first.Get("source")).Fields).Clear()),
            "Subscribers cannot mutate shared envelopes, nested snapshots or source metadata");
        var history = Object("""{"rows":[{"value":7}]}""");
        feed.ShowHistory(history, "历史");
        ((List<EvidenceValue>)((EvidenceArray)history.Get("rows")).Items).Clear();
        check(((EvidenceArray)((EvidenceObject)feed.Damage!.Get("snapshot")).Get("rows")).Items.Count == 1,
            "Historical producers retain ownership of their original report");
        feed.ReturnLive();
        check(ReferenceEquals(feed.Damage!.Get("snapshot"), captured) && rows.Items.Count == 1,
            "Returning to live reuses the isolated snapshot without copying it again");
        feed.Receive(Message("owned", 1, 12)); feed.ClearLive();
        check(rows.Items.Count == 1 && ReferenceEquals(first.Get("snapshot"), captured),
            "New snapshots and clear do not change a previously delivered frame");
    }
    private static async Task TransportAsync(Action<bool, string> check)
    {
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(12)); var token = timeout.Token;
        using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start(); var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        TaskCompletionSource releaseFirst = new(TaskCreationOptions.RunContinuationsAsynchronously);
        TaskCompletionSource secondSent = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var attempts = 0; var compactRequests = 0;
        var server = Task.Run(async () =>
        {
            for (var connection = 0; connection < 2; connection++)
            {
                using var tcp = await listener.AcceptTcpClientAsync(token); Interlocked.Increment(ref attempts); using var network = tcp.GetStream();
                List<byte> header = []; byte[] one = new byte[1];
                while (header.Count < 16384)
                {
                    if (await network.ReadAsync(one, token) == 0) throw new IOException("Native client closed during handshake"); header.Add(one[0]);
                    if (header.Count >= 4 && header.TakeLast(4).SequenceEqual(new byte[] { 13, 10, 13, 10 })) break;
                }
                var request = LoopbackWebSocketRequest.Parse(Encoding.ASCII.GetString(header.ToArray()), new string('x', 43), out var status);
                if (request is null || status != 101) throw new IOException("Native client sent an invalid handshake");
                if (request.Summary) Interlocked.Increment(ref compactRequests);
                await network.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + request.Accept + "\r\n\r\n"), token);
                using var socket = WebSocket.CreateFromStream(network, true, null, Timeout.InfiniteTimeSpan);
                async Task Send(EvidenceObject message) => await socket.SendAsync(Encoding.UTF8.GetBytes(PythonSortedJson.Serialize(message)), WebSocketMessageType.Text, true, token);
                if (connection == 0)
                {
                    await Send(Message("network", 1, 10)); await Send(Message("network", 0, 999));
                    await releaseFirst.Task.WaitAsync(token); await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "reconnect", token);
                }
                else
                {
                    await Send(Message("network", 2, 20));
                    await Send(Object("""{"type":"combo_snapshot","schema_version":2,"stream_id":"visual","sequence":0,"snapshot":{"slots":[]}}"""));
                    await Send(Message("network", 1, 999)); secondSent.SetResult();
                    var buffer = new byte[32]; try { await socket.ReceiveAsync(buffer, token); } catch (WebSocketException) { }
                }
            }
        }, token);
        await using OverlaySocketClient client = new(port, reconnectDelay: TimeSpan.FromMilliseconds(30)); client.Start(); client.Start();
        async Task<EvidenceObject> WaitMessage(string kind)
        {
            var watch = Stopwatch.StartNew();
            while (watch.Elapsed.TotalSeconds < 5)
            {
                var state = client.Poll(); var found = state.Messages.FirstOrDefault(message => message.Get("type") is EvidenceText text && text.Value == kind);
                if (found is not null) return found;
                if (server.IsFaulted) await server; await Task.Delay(5, token);
            }
            throw new TimeoutException($"Overlay transport timed out: attempts={attempts}, state={client.Poll().Status}, server={server.Status}");
        }
        var first = await WaitMessage("analysis_summary");
        check((first.Get("snapshot") as EvidenceObject)?.Get("value") is EvidenceInteger { Value: var firstValue } && firstValue == 10, "The real socket mailbox rejects out-of-order frames before coalescing");
        releaseFirst.SetResult(); await secondSent.Task.WaitAsync(token);
        Dictionary<string, EvidenceObject> received = []; var watch = Stopwatch.StartNew();
        while (received.Count < 2 && watch.Elapsed.TotalSeconds < 5)
        {
            foreach (var message in client.Poll().Messages) received[((EvidenceText)message.Get("type")).Value] = message;
            if (server.IsFaulted) await server; if (received.Count < 2) await Task.Delay(5, token);
        }
        check(attempts == 2 && compactRequests == 2 && received.Count == 2 && (received["analysis_summary"].Get("snapshot") as EvidenceObject)?.Get("value") is EvidenceInteger { Value: var last } && last == 20,
            "An explicit close reconnects once and delivers both compact and visual topics without requesting a full report");
        watch.Restart(); await client.DisposeAsync(); await server;
        check(watch.Elapsed.TotalSeconds < 2 && client.Poll() is { Status: "已停止", Messages.Count: 0 }, "Stop cancels an active receive and joins the actual socket worker");
        await client.DisposeAsync();
    }
}
