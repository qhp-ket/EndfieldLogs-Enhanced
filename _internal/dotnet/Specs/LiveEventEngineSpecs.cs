using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class LiveEventEngineSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static TraceEvent Event(long sequence, long timestamp, string type, EvidenceObject data)
    {
        var captured = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)captured.Value).Fields.ToDictionary(); fields["legacy_layout"] = captured.Layout;
        return new(sequence, timestamp, type, new(fields), Obj("{}"));
    }
    private static TraceEvent Damage(int sequence, long timestamp)
    {
        var data = Obj("""
        {"hit_seq":1,"actors":{"attacker":"chr_0001_test","target":"eny_0001_test"},
         "action":{"skill":"chr_0001_test_normal_skill"},"amounts":{"value":-100,"current_hp":900},
         "blackboards":{"dynamic":[],"calculation":[]},"evidence":{"presence":{}}}
        """);
        ((Dictionary<string, EvidenceValue>)data.Fields)["hit_seq"] = new EvidenceInteger(sequence);
        return Event(sequence, timestamp, "damage", data);
    }
    private static EvidenceObject Battle(EvidenceObject report) => (EvidenceObject)report.Get("battle");
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-event-engine-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ResourceFiles files = new(root);
            var zone = TimeZoneInfo.CreateCustomTimeZone("synthetic-offset", TimeSpan.FromMinutes(330), "synthetic-offset", "synthetic-offset");
            var start = new DateTimeOffset(2026, 10, 29, 23, 59, 59, zone.BaseUtcOffset).ToUnixTimeMilliseconds();
            TraceEvent[] events = [Event(1, start, "official_timer", Obj("""{"phase":"start","source":"SC_GAME_MECHANICS_SYNC_CHALLENGE_START","game_id":"challenge","challenge_start_ts":7}""")),
                Damage(2, start + 100), Damage(3, start + 1100)];
            var lines = events.SelectMany(item => item.Type == "damage" ? DamageLegacyExporter.Lines(item, 330) : TimerLegacyExporter.Lines(item, 330)).ToArray();
            var engine = LiveBattleEngine.Load(files, new(2026, 10, 29), zone);
            var legacy = LiveBattleEngine.Load(files, new(2026, 10, 29), zone);
            foreach (var length in new[] { 2, 3 })
            {
                var suffix = events.Skip(engine.Diagnostics.ConsumedEvents).Take(length - engine.Diagnostics.ConsumedEvents).ToArray();
                var full = engine.SnapshotEvents(new(1, length, engine.Diagnostics.ConsumedEvents, suffix))!;
                var expected = legacy.Snapshot(lines.Take(length).ToArray())!;
                check(EvidenceJson.PythonEquals(full, expected),
                    "Appending direct events matches the independent legacy export report across local midnight");
                var compact = engine.SnapshotEvents(new(1, length, length, []), summary: true)!;
                check(EvidenceJson.PythonEquals(compact, legacy.Snapshot(lines.Take(length).ToArray(), summary: true)!),
                    "Direct event summaries preserve timing, quality, contributions and roster");
            }
            check(engine.Diagnostics is { ConsumedEvents: 3, IngestedLines: 3, SourceGeneration: 1, EventRevision: 3, TraceReplays: 0 }
                && events[1].CapturedAtMs == start + 100,
                "The event watermark advances exactly once while original Unix clocks remain untouched");
            var builds = engine.Diagnostics.ReportBuilds;
            var repeated = engine.SnapshotEvents(new(1, 3, 3, []), summary: true)!;
            ((Dictionary<string, EvidenceValue>)Battle(repeated).Fields)["total_damage"] = new EvidenceInteger(-1);
            var clean = engine.SnapshotEvents(new(1, 3, 3, []), summary: true)!;
            check(engine.Diagnostics.ReportBuilds == builds && engine.Diagnostics.CachedReads == 2
                && Battle(clean).Get("total_damage") is EvidenceInteger { Value: var total } && total == 200,
                "Unchanged event reads use the completed cache without exposing mutable result state");
            foreach (var invalid in new[] { new LiveEventBatch(1, 4, 2, []), new(1, 2, 3, []), new(0, 4, 0, []) })
            {
                var before = engine.Diagnostics;
                try { engine.SnapshotEvents(invalid); throw new Exception("Invalid watermark accepted"); }
                catch (InvalidOperationException) { check(engine.Diagnostics == before, "Stale generation, revision and missing suffixes cannot mutate a completed live analysis"); }
            }
            var fresh = engine.SnapshotEvents(new(2, 1, 0, [events[1]]), summary: true)!;
            check(engine.Diagnostics.ConsumedEvents == 1 && Battle(fresh).Get("total_damage") is EvidenceInteger { Value: var next } && next == 100,
                "A new source generation retracts previous events before accepting its first batch");
            engine.Reset();
            var clock = new LiveObserverClock(start + 1000, 1000);
            var clocked = engine.SnapshotEvents(new(3, 2, 0, events.Take(2).ToArray()), clock, summary: true)!;
            var clockLegacy = legacy.Snapshot(lines.Take(2).ToArray(), "[00:00:00.000] LIVE_TIMER_TICK elapsedMs=1000\n", summary: true)!;
            check(EvidenceJson.PythonEquals(clocked, clockLegacy), "The structured observer clock uses the same timer and midnight coordinates as legacy reports");
            builds = engine.Diagnostics.ReportBuilds;
            var advanced = engine.SnapshotEvents(new(3, 2, 2, []), new(start + 1500, 1500), summary: true)!;
            check(engine.Diagnostics.ReportBuilds == builds && engine.Diagnostics.ClockProjections == 1
                && Battle(advanced).Get("total_dps") is EvidenceReal { Value: 66.67 },
                "Clock-only event reads advance the compact report without re-entering allocation or fabricating a legacy timer line");
            using CancellationTokenSource canceled = new(); canceled.Cancel();
            var previous = engine.Diagnostics;
            try { engine.SnapshotEvents(new(3, 3, 2, [events[2]]), cancellationToken: canceled.Token); throw new Exception("Canceled batch accepted"); }
            catch (OperationCanceledException) { check(engine.Diagnostics == previous, "A pre-canceled append does not consume or publish events"); }
            try { engine.SnapshotEvents(new(3, 4, 2, [events[2], events[2] with { Type = "future_event" }])); throw new Exception("Unsupported event accepted"); }
            catch (NotSupportedException) { check(engine.Diagnostics.ConsumedEvents == 0 && engine.Diagnostics.TraceReplays == 1, "A partly failed batch requires explicit replay from zero"); }
            var recovered = engine.SnapshotEvents(new(3, 4, 0, events), summary: true)!;
            check(Battle(recovered).Get("total_damage") is EvidenceInteger { Value: var recoveredTotal } && recoveredTotal == 200,
                "Replaying a failed event generation cannot double count its consumed prefix");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
