using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Runtime.Realtime;

internal static class LoopbackWebSocketSpecs
{
    private const string Token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private const string Hit = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    private static void Wait(Task task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
    internal static JsonNode Read(WebSocket client)
    {
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        using MemoryStream result = new(); byte[] buffer = new byte[4096];
        while (true)
        {
            var received = client.ReceiveAsync(buffer, timeout.Token).GetAwaiter().GetResult();
            if (received.MessageType == WebSocketMessageType.Close) throw new IOException("WebSocket closed before expected JSON");
            result.Write(buffer, 0, received.Count);
            if (result.Length > 2 * 1024 * 1024) throw new IOException("Unexpectedly large spec message");
            if (received.EndOfMessage) return JsonNode.Parse(result.ToArray())!;
        }
    }
    private static JsonNode ReadSnapshot(WebSocket client, string type)
    {
        for (var index = 0; index < 10; index++)
        {
            var value = Read(client);
            if (value["type"]?.GetValue<string>() == type && value["snapshot"] is not null) return value;
        }
        throw new IOException("No completed analysis after expected protocol messages");
    }
    private static string Request(string target = "/", string extra = "") =>
        "GET " + target + " HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n" + extra + "\r\n";

    public static void Run(Action<bool, string> check)
    {
        var native = LoopbackWebSocketRequest.Parse(Request(), Token, out var status);
        check(status == 101 && native is { Summary: false, Accept: "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" },
            "The loopback upgrade accepts native clients and matches the RFC 6455 handshake example");
        check(LoopbackWebSocketRequest.Parse(Request("/?analysis=summary", "Origin: https://example.invalid\r\n"), Token, out status) is null && status == 403,
            "An Origin-bearing request requires its explicit capability before upgrade");
        var browser = Request("/?analysis=summary&access_token=" + Token, "Origin: https://example.invalid\r\n");
        check(LoopbackWebSocketRequest.Parse(browser, Token, out status) is { Summary: true } && status == 101,
            "A valid capability allows the compact browser stream");
        check(LoopbackWebSocketRequest.Parse(browser.Replace("\r\n\r\n", "\r\nOrigin: https://second.invalid\r\n\r\n", StringComparison.Ordinal), Token, out status) is null
            && LoopbackWebSocketRequest.Parse(Request("/?access_token=" + Token + "&access_token=" + Token, "Origin: x\r\n"), Token, out _) is null,
            "Duplicate Origins and duplicate capability parameters fail closed");
        check(LoopbackWebSocketRequest.Parse(Request(extra: "Content-Length: 1\r\n"), Token, out status) is null && status == 400
            && LoopbackWebSocketRequest.Parse(Request().Replace("Sec-WebSocket-Version: 13", "Sec-WebSocket-Version: 12", StringComparison.Ordinal), Token, out _) is null,
            "The restricted upgrade rejects HTTP request bodies and incompatible protocol versions");

        var compactCalls = 0; var fullCalls = 0;
        using LiveAnalysisStreams streams = new(compact => new(() => (_, _, _, _) =>
        {
            if (compact) Interlocked.Increment(ref compactCalls); else Interlocked.Increment(ref fullCalls);
            return new(new Dictionary<string, EvidenceValue> { ["value"] = new EvidenceInteger(100) });
        }, new(Summary: compact)), TimeSpan.Zero, TimeSpan.Zero);
        var subscriptionCalls = 0;
        LoopbackWebSocketServer server = new(0, Token, compact => { Interlocked.Increment(ref subscriptionCalls); return streams.Subscribe(compact); },
            () => new() { ["type"] = "hello", ["schema_version"] = 2, ["state"] = "live" });
        using CancellationTokenSource stop = new();
        var analyses = streams.RunAsync(stop.Token); var transport = server.RunAsync(stop.Token);
        try
        {
            var endpoint = server.Endpoint!;
            check(endpoint.Host == "127.0.0.1" && endpoint.Port > 0, "The real transport binds IPv4 loopback without URL ACLs or an HTTP framework");
            using ClientWebSocket client = new(); Wait(client.ConnectAsync(new(endpoint, "?analysis=summary"), stop.Token));
            check(Read(client)["type"]!.GetValue<string>() == "hello" && Read(client)["type"]!.GetValue<string>() == "analysis_summary",
                "A real .NET WebSocket client receives hello before the selected analysis stream");
            streams.FeedLine(Hit);
            var frame = ReadSnapshot(client, "analysis_summary");
            check(frame["snapshot"]!["value"]!.GetValue<int>() == 100 && Volatile.Read(ref fullCalls) == 0,
                "Loopback transport consumes the production mailbox and does not request full analysis for compact clients");
            server.PublishEvent(new("synthetic", 1234, "probe", new Dictionary<string, object?> { ["number"] = 9 }));
            var events = Read(client);
            check(events["type"]!.GetValue<string>() == "event_batch" && events["events"]![0]!["number"]!.GetValue<int>() == 9,
                "Public event batches share the connection without interleaving JSON frames");

            using ClientWebSocket denied = new(); denied.Options.SetRequestHeader("Origin", "https://example.invalid");
            try { Wait(denied.ConnectAsync(endpoint, stop.Token)); throw new InvalidOperationException("Browser access was allowed without a token"); }
            catch (WebSocketException) { check(true, "The actual HTTP upgrade rejects unauthorized browser-origin clients"); }
            using ClientWebSocket allowed = new(); allowed.Options.SetRequestHeader("Origin", "https://example.invalid");
            Wait(allowed.ConnectAsync(new(endpoint, "?analysis=summary&access_token=" + Token), stop.Token));
            check(Read(allowed)["type"]!.GetValue<string>() == "hello" && ReadSnapshot(allowed, "analysis_summary")["snapshot"] is not null,
                "Authorized browser-origin clients receive the retained compact result");

            using ClientWebSocket full = new(); Wait(full.ConnectAsync(endpoint, stop.Token));
            check(Read(full)["type"]!.GetValue<string>() == "hello" && ReadSnapshot(full, "analysis_snapshot")["snapshot"] is not null
                && Volatile.Read(ref fullCalls) == 1, "A full-report connection activates an independent calculator using retained trace context");
            Wait(client.CloseAsync(WebSocketCloseStatus.NormalClosure, "", stop.Token));
            using ClientWebSocket reconnected = new(); Wait(reconnected.ConnectAsync(new(endpoint, "?analysis=summary"), stop.Token));
            Read(reconnected);
            check(ReadSnapshot(reconnected, "analysis_summary")["stream_id"]!.GetValue<string>() == frame["stream_id"]!.GetValue<string>(),
                "Reconnection receives the current stream without resetting the underlying capture or evidence");
            var beforeVisual = Volatile.Read(ref subscriptionCalls);
            using ClientWebSocket visual = new(); Wait(visual.ConnectAsync(new(endpoint, "?analysis=none&combo=1"), stop.Token));
            check(Read(visual)["type"]!.GetValue<string>() == "hello" && server.HasComboSubscribers && Volatile.Read(ref subscriptionCalls) == beforeVisual,
                "A visual-only native client declares demand without activating either analysis calculator");
            var combo = (EvidenceObject)EvidenceJson.Parse("""{"type":"combo_snapshot","schema_version":2,"stream_id":"vision","sequence":1,"snapshot":{"slots":[]}}""");
            server.PublishCombo(combo);
            check(Read(visual)["type"]!.GetValue<string>() == "combo_snapshot", "Actual visual publications pass through the bounded socket mailbox");
            Wait(visual.CloseAsync(WebSocketCloseStatus.NormalClosure, "", stop.Token));
            using ClientWebSocket visualAgain = new(); Wait(visualAgain.ConnectAsync(new(endpoint, "?analysis=none&combo=1"), stop.Token));
            Read(visualAgain);
            check(Read(visualAgain)["sequence"]!.GetValue<int>() == 1 && Volatile.Read(ref subscriptionCalls) == beforeVisual,
                "A reconnecting visual client immediately receives the retained snapshot with no full report subscription");
            Wait(visualAgain.CloseAsync(WebSocketCloseStatus.NormalClosure, "", stop.Token));
        }
        finally
        {
            stop.Cancel(); Wait(transport);
            try { Wait(analyses); } catch (OperationCanceledException) { }
        }
    }
}
