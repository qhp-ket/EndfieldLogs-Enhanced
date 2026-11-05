using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.History;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Tracing;

internal static class TraceEventHistorySpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static TraceEvent Event(long seq, long stamp, string type, string json)
    {
        var projection = TraceValueProjection.Capture(Obj(json));
        var fields = ((EvidenceObject)projection.Value).Fields.ToDictionary(); fields["legacy_layout"] = projection.Layout;
        return new(seq, stamp, type, new(fields), Obj("{}"));
    }
    private static TraceEvent Damage(long seq, long stamp) => Event(seq, stamp, "damage", $$$$"""
        {"hit_seq":{{{{seq}}}},"actors":{"attacker":"chr_0001_test","target":"eny_0001_test"},
         "action":{"skill":"chr_0001_test_normal_skill"},"amounts":{"value":-100,"current_hp":900},
         "blackboards":{"dynamic":[],"calculation":[]},"evidence":{"presence":{}}}
        """);
    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-event-history-");
        try
        {
            MidnightSelections(check, folder.FullName);
            var start = new DateTimeOffset(2026, 10, 31, 23, 59, 59, TimeSpan.FromHours(8)).ToUnixTimeMilliseconds();
            TraceEvent[] events = [
                Event(1, start - 500, "dungeon", """{"dungeon_id":"synthetic","source":"packet"}"""),
                Event(2, start, "official_timer", """{"phase":"start","source":"synthetic","game_id":"synthetic","challenge_start_ts":12}"""),
                Damage(3, start + 100),
                Event(4, start + 500, "official_timer", """{"phase":"start","source":"synthetic","game_id":"synthetic","challenge_start_ts":12}"""),
                Event(5, start + 550, "battle_timer", """{"phase":"start","source":"PacketBattleState","start_ms":550,"official":true}"""),
                Damage(6, start + 1100),
                Event(7, start + 2000, "official_timer", """{"phase":"end","source":"synthetic","game_id":"synthetic","pass_time":1800,"is_pass":true}"""),
                Event(8, start + 40000, "battle_timer", """{"phase":"start","source":"PacketBattleState","start_ms":40000,"official":true}"""),
                Damage(9, start + 40100),
                Event(10, start + 41000, "battle_timer", """{"phase":"end","source":"PacketBattleState","elapsed_ms":900,"packet_elapsed_ms":900,"start_ms":40000,"end_ms":40900,"sane":true,"official":true}""")
            ];
            var bounds = TraceBattleSplitter.FindEventBounds(events, 480);
            var oldLines = events.SelectMany(item => TraceLegacyExporter.Lines(item, 480)).ToArray();
            var oldBounds = TraceBattleSplitter.FindBounds(oldLines);
            check(bounds.Count == 2 && oldBounds.Count == 2 && bounds[0].Bounds.FirstHitHint == oldBounds[0].FirstHitHint
                && bounds[1].Bounds.FirstHitHint == oldBounds[1].FirstHitHint && bounds[0].FirstHitCapturedAtMs == start + 100,
                "Structured history shares duplicate-official/packet-start selection and preserves the true midnight-spanning capture date");
            var path = Path.Combine(folder.FullName, "trace_synthetic.jsonl");
            TraceHeader header = new("synthetic-boundaries", 1, null, "csharp", "test", "Asia/Shanghai", 480, new Dictionary<string, string>());
            using (TraceJsonlWriter writer = new(File.Create(path), header)) foreach (var item in events) writer.Write(item);
            HistoryIndex index = new(Path.Combine(folder.FullName, "index"));
            var records = index.Records(path, trace: true);
            check(records.Count == 2 && records[0].ReferenceDate == "2026-10-31" && records[1].ReferenceDate == "2026-11-01"
                && records[0].StartedAtMs == start + 100 && records[1].StartedAtMs == start + 40100,
                "History rows retain exact Unix identity and each battle's original local date");
            HistoryAnalyzer analyzer = new(new ResourceFiles(folder.FullName), TimeZoneInfo.Utc);
            var first = analyzer.Analyze(records[0]); var second = analyzer.Analyze(records[1]);
            var firstBattle = (EvidenceObject)first.Get("battle"); var secondBattle = (EvidenceObject)second.Get("battle");
            check(EvidenceJson.PythonEquals(firstBattle.Get("total_damage"), new EvidenceInteger(200))
                && EvidenceJson.PythonEquals(firstBattle.Get("duration_ms"), new EvidenceInteger(1800))
                && firstBattle.Get("official_timer_end_seen") is EvidenceBoolean { Value: true },
                "Selected structured official battle keeps both hits and server duration across midnight: "
                    + PythonSortedJson.Serialize(firstBattle.Get("total_damage")) + " / " + PythonSortedJson.Serialize(firstBattle.Get("duration_ms"))
                    + " / " + PythonSortedJson.Serialize(firstBattle.Get("timer_evidence")));
            check(EvidenceJson.PythonEquals(secondBattle.Get("total_damage"), new EvidenceInteger(100))
                && EvidenceJson.PythonEquals(secondBattle.Get("duration_ms"), new EvidenceInteger(900)),
                "The next packet battle excludes previous hits and earlier official completion");
            check(firstBattle.Get("battle_start_at") is EvidenceText stamp && stamp.Value.StartsWith("2026-10-31", StringComparison.Ordinal)
                && stamp.Value.EndsWith("+08:00", StringComparison.Ordinal), "Historical report uses the recording timezone rather than the current machine timezone");
            foreach (var record in records)
            {
                var exported = Path.Combine(folder.FullName, $"selected-{record.RecordIndex}.log");
                TraceExportService.ExportBattle(record, exported);
                var integrity = TraceExportService.LoadIntegrity(exported);
                var exportedRecords = new HistoryCatalog().Read(exported, true);
                var expected = (EvidenceObject)analyzer.Analyze(record).Get("battle");
                var actual = (EvidenceObject)analyzer.Analyze(exportedRecords.Single()).Get("battle");
                check(integrity.Verified && exportedRecords.Count == 1
                    && EvidenceJson.PythonEquals(expected.Get("total_damage"), actual.Get("total_damage"))
                    && EvidenceJson.PythonEquals(expected.Get("duration_ms"), actual.Get("duration_ms")),
                    "Compatible structured export contains exactly the selected battle with original damage, timer and valid proof");
            }
            File.AppendAllText(path, TraceJsonl.Serialize(Event(11, start + 41100, "clock_tick", """{"source":"CS_BATTLE_OP","tick_ms":41100}""")), new UTF8Encoding(false));
            check(!HistoryCatalog.SourcesUnchanged(records[0]), "Appending to any recorded volume invalidates retained historical source metadata");
            try { analyzer.Analyze(records[0]); throw new InvalidOperationException("Stale structured history accepted"); }
            catch (InvalidDataException) { check(true, "Stale structured ranges cannot be silently recalculated against changed files"); }
            check(index.Records(path, trace: true).Select(row => row.Key).SequenceEqual(records.Select(row => row.Key)),
                "Rebuilding an appended structured index preserves existing stable battle keys");
        }
        finally { folder.Delete(recursive: true); }
    }

    private static void MidnightSelections(Action<bool, string> check, string root)
    {
        foreach (var offset in new[] { 480, -300 })
        foreach (var structured in new[] { true, false })
        foreach (var afterMidnight in new[] { false, true })
        {
            var origin = afterMidnight
                ? new DateTimeOffset(2026, 11, 6, 0, 0, 30, TimeSpan.FromMinutes(offset))
                : new DateTimeOffset(2026, 11, 5, 23, 59, 59, TimeSpan.FromMinutes(offset));
            var stamp = origin.ToUnixTimeMilliseconds();
            var path = Path.Combine(root, $"trace_20261105-midnight-{offset}-{structured}-{afterMidnight}" + (structured ? ".jsonl" : ".ndjson"));
            if (structured)
            {
                TraceEvent[] events = [
                    Event(1, stamp - 40000, "official_timer", """{"phase":"start","source":"synthetic","game_id":"old","challenge_start_ts":1}"""),
                    Damage(2, stamp - 39000),
                    Event(3, stamp - 38000, "official_timer", """{"phase":"end","source":"synthetic","game_id":"old","pass_time":2000,"is_pass":true}"""),
                    Event(4, stamp, "official_timer", """{"phase":"start","source":"synthetic","game_id":"new","challenge_start_ts":2}"""),
                    Damage(5, stamp + 1100),
                    Event(6, stamp + 2000, "official_timer", """{"phase":"end","source":"synthetic","game_id":"new","pass_time":2000,"is_pass":true}"""),
                ];
                TraceHeader header = new($"midnight-{offset}-{afterMidnight}", 1, null, "csharp", "test", "recorded", offset, new Dictionary<string, string>());
                using TraceJsonlWriter writer = new(File.Create(path), header);
                foreach (var item in events) writer.Write(item);
            }
            else
            {
                string Start(long time, string id) => $$"""{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_START","timestamp_ms":{{time}},"game_id":"{{id}}","challenge_start_ts":123}""";
                string End(long time, string id) => $$"""{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE","timestamp_ms":{{time}},"game_id":"{{id}}","is_pass":true,"pass_time":2000}""";
                string Hit(long time) => $$$$"""{"type":"BattleOpTriggerAction","timestamp_ms":{{{{time}}}},"owner_id":11,"inst_id":77,"action":{"action_type":"BattleActionDamage","damage_action":{"attacker_id":11,"details":[{"target_id":33,"value":-100,"cur_hp":900}]}}}""";
                string[] rows = [
                    $$"""{"type":"session_volume","schema_version":1,"recording_id":"midnight-{{offset}}-{{afterMidnight}}","session_id":"test","trace_recording_id":"trace","volume":1,"trace_volume":1,"event_offset":0,"timezone_offset_minutes":{{offset}},"previous_volume":null}""",
                    $$"""{"type":"SC_SELF_SCENE_INFO","timestamp_ms":{{stamp - 41000}},"char_list":[{"id":101,"battle_inst_id":11,"templateid":"chr_0001_test"}]}""",
                    $$"""{"type":"SC_OBJECT_ENTER_VIEW","timestamp_ms":{{stamp - 41000}},"objects":[{"battle_inst_id":33,"templateid":"eny_0001_test"}]}""",
                    $$"""{"type":"BattleOpSkillAttach","timestamp_ms":{{stamp - 41000}},"skill_inst_id":77,"src_inst_id":11,"template_str_id":"chr_0001_test_normal_skill"}""",
                    Start(stamp - 40000, "old"), Hit(stamp - 39000), End(stamp - 38000, "old"),
                    Start(stamp, "new"), Hit(stamp + 1100), End(stamp + 2000, "new"),
                ];
                File.WriteAllText(path, string.Join('\n', rows) + "\n", new UTF8Encoding(false));
            }
            var records = new HistoryCatalog().Read(path, structured);
            check(records.Count == 2 && records[^1].ReferenceDate == "2026-11-06",
                "Midnight history keeps two distinct battles and the selected first-hit identity");
            HistoryAnalyzer analyzer = new(new ResourceFiles(root));
            var battle = (EvidenceObject)analyzer.Analyze(records[^1]).Get("battle");
            DateTimeOffset Time(EvidenceObject data, string key) => DateTimeOffset.Parse(((EvidenceText)data.Get(key)).Value, System.Globalization.CultureInfo.InvariantCulture);
            check(Time(battle, "battle_start_at") == origin && Time(battle, "battle_end_at") == origin.AddSeconds(2)
                && EvidenceJson.PythonEquals(battle.Get("total_damage"), new EvidenceInteger(100)),
                $"Selected {(structured ? "JSONL" : "session")} replay uses the pre-midnight timer date in offset {offset}, excluding previous hits");
            var exported = Path.Combine(root, TraceExportService.DefaultBattleFileName(records[^1]));
            TraceExportService.ExportBattle(records[^1], exported);
            var imported = new HistoryCatalog().Read(exported, true);
            var actual = (EvidenceObject)analyzer.Analyze(imported.Single()).Get("battle");
            check(TraceExportService.LoadIntegrity(exported).Verified
                && Time(actual, "battle_start_at").DateTime == origin.DateTime
                && Time(actual, "battle_end_at").DateTime == origin.AddSeconds(2).DateTime
                && EvidenceJson.PythonEquals(actual.Get("total_damage"), new EvidenceInteger(100))
                && EvidenceJson.PythonEquals(actual.Get("duration_ms"), battle.Get("duration_ms")),
                $"Single-battle compatible {(structured ? "JSONL" : "session")} export preserves midnight dates, damage and proof in offset {offset}");
        }
    }
}
