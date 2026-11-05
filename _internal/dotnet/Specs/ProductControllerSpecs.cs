using System.Diagnostics;
using System.Net.WebSockets;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Capture;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Services;

internal static class ProductControllerSpecs
{
    private static void Until(Func<bool> condition)
    { var watch = Stopwatch.StartNew(); while (!condition()) { if (watch.Elapsed.TotalSeconds > 10) throw new TimeoutException("Product capture did not reach expected state"); Thread.Sleep(10); } }
    public static void Capture(Action<bool, string> check)
    {
        var root = Directory.CreateTempSubdirectory("endfield-product-capture-");
        CaptureController? controller = null;
        try
        {
            ResourceFiles resources = new(Path.Combine(root.FullName, "internal")); SettingsContext context = new(root.FullName); SettingsCodec codec = new(context);
            SettingsStore settings = new(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")), codec);
            List<GameCaptureServiceSpecs.Backend> backends = []; var fail = false; GameCaptureService? active = null;
            controller = new(resources, settings, options => active = new(resources, options with { WebSocketPort = 0 }, () =>
            {
                if (fail) throw new IOException("synthetic startup failure");
                GameCaptureServiceSpecs.Backend backend = new(); lock (backends) backends.Add(backend); return backend;
            }));
            check(!controller.Running && controller.Poll().Status is null, "Application capture allocates no native service before start");
            controller.SetStreams(new HashSet<string> { "analysis_summary", "combo_snapshot" }); controller.Start();
            Until(() => { lock (backends) return backends.Count == 1 && backends[0].Started.Task.IsCompleted; });
            Until(() => controller.Poll().Frames.Any(frame => frame.Type == "analysis_summary"));
            check(controller.Running, "Owner polling subscribes to a running production stream without racing startup");
            Until(() => active?.WebSocketEndpoint is not null);
            using (ClientWebSocket visual = new())
            {
                visual.ConnectAsync(new(active!.WebSocketEndpoint!, "?analysis=none&combo=1"), CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
                LoopbackWebSocketSpecs.Read(visual); Until(() => controller.Poll().ComboRequested);
                var combo = (EvidenceObject)EvidenceJson.Parse("""{"type":"combo_snapshot","schema_version":2,"stream_id":"visual","sequence":0,"snapshot":{"slots":[]}}""");
                controller.PublishCombo(combo);
                check(LoopbackWebSocketSpecs.Read(visual)["type"]!.GetValue<string>() == "combo_snapshot", "Application capture forwards independent vision output to an actual standalone subscriber");
                visual.CloseAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
                Until(() => !controller.Poll().ComboRequested);
                check(!controller.Poll().ComboRequested, "Closing the standalone visual client releases its application demand");
            }
            controller.StopAsync().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
            check(!controller.Running && backends[0].BackendCloses == 1 && backends[0].DeviceCloses == 1,
                "Stopping waits for the real composition and releases native ownership");
            controller.Start(); Until(() => { lock (backends) return backends.Count == 2 && backends[1].Started.Task.IsCompleted; });
            check(controller.Running && controller.Poll().Error is null, "Restart creates an independent one-shot service and clears old error state");
            var rejected = false;
            Task.Run(() => { try { controller.Poll(); } catch (InvalidOperationException) { rejected = true; } }).GetAwaiter().GetResult();
            check(rejected, "Background code cannot drain an owner-thread capture controller");
            controller.StopAsync().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult(); fail = true; controller.Start(); Until(() => !controller.Running);
            check(controller.Poll().Error == "synthetic startup failure", "Resource and native startup failure reaches the application state");
            controller.DisposeAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
            var disposed = false; try { controller.Start(); } catch (ObjectDisposedException) { disposed = true; }
            check(disposed && backends.All(backend => backend.BackendCloses == 1), "Closed application rejects restart and leaves no backend alive");
        }
        finally { controller?.DisposeAsync().AsTask().GetAwaiter().GetResult(); root.Delete(true); }
    }
    public static void Curves(Action<bool, string> check)
    {
        var snapshot = (EvidenceObject)EvidenceJson.Parse("""
            {"battle":{"duration_ms":2500},"participants":[{"character_key":"a"},{"character_key":"b"}],"timeline_events":[
            {"event_type":"damage","ts_ms_from_start":0,"source_character_key":"a","value":100,"rdps_contributions":[{"character_key":"a","value":60},{"character_key":"b","value":40}]},
            {"event_type":"damage","ts_ms_from_start":1000,"source_character_key":"b","value":50,"rdps_contributions":[]},
            {"event_type":"damage","ts_ms_from_start":2500,"source_character_key":"a","value":20,"rdps_contributions":[{"character_key":"b","value":20}]},
            {"event_type":"damage","ts_ms_from_start":-1,"source_character_key":"a","value":9999},
            {"event_type":"damage","ts_ms_from_start":2501,"source_character_key":"a","value":9999}]}
            """);
        var rd = DamageSeries.Build(snapshot); var end = rd.Points[^1];
        check(rd.Metric == "rdmg" && rd.Hits == 3 && rd.Missing == 1 && rd.Points.Count == 4, "Damage plot defaults to cumulative rDMG and counts missing allocations explicitly");
        check(end.TimeMs == 2500 && end.Values["a"] == 60 && end.Values["b"] == 60, "Boundary hit belongs to the final partial second and missing attribution is never assigned to the attacker");
        var dps = DamageSeries.Build(snapshot, "dps").Points[^1];
        check(dps.Values["a"] == 48 && dps.Values["b"] == 20, "DPS uses cumulative damage divided by elapsed seconds");
        var filtered = DamageSeries.Build(snapshot, "rdmg", "b");
        check(filtered.Points.All(point => point.Values.Keys.SequenceEqual(["b"])) && filtered.Points[^1].Values["b"] == 60, "Character filter changes presentation without changing attribution");
        var empty = (EvidenceObject)EvidenceJson.Parse("""{"battle":{"duration_ms":1000},"timeline_events":[{"event_type":"damage","ts_ms_from_start":0,"value":10}]}""");
        check(DamageSeries.Build(empty).Points.Count == 0 && DamageSeries.Build(empty).Missing == 1, "Entirely unknown rDMG produces no fabricated zero curve");
        check(DamageSeries.Build(snapshot, "invalid").Points.Count == 0 && DamageSeries.Build((EvidenceObject)EvidenceJson.Parse("{}")).Points.Count == 0,
            "Missing duration and unsupported metric return an empty series");
        check(PythonSortedJson.Serialize(snapshot).Contains("9999", StringComparison.Ordinal), "Projection leaves out-of-range original evidence intact");
    }
}
