using System.Text;
using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Sessions;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Core.Timing;
using EndfieldLogs.Core.Reporting;
using Google.Protobuf;

internal static class TraceBridgeSpecs
{
    private static EvidenceObject E(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool, string> check)
    {
        StructuredClock(check);
        StructuredTimer(check);
        StructuredStage(check);
        StructuredContext(check);
        StructuredTimerReport(check);
        List<string> lines = [];
        TraceBridge bridge = new(lines.Add, timeZone: TimeZoneInfo.Utc, clock: () => 0);
        bridge.Handle(E("""{"type":"BattleOpAddBuff","timestamp_ms":1000,"buff_inst_id":8,"int_id":55,"target_inst_id":11,"src_inst_id":22}"""));
        check(lines.Count == 0, "Add-Buff groups remain pending until a semantic boundary");
        bridge.Handle(E("""{"type":"CS_PING","timestamp_ms":9000,"client_ts":0}"""));
        check(lines.Count == 1 && lines[0].StartsWith("[00:00:09.000] GAME_CLOCK_SYNC", StringComparison.Ordinal),
            "Clock observations bypass pending Buff groups and retain capture timestamps");
        bridge.EndCaptureSession();
        check(lines.Count == 3 && lines[1].StartsWith("[00:00:01.000] BUFF_START", StringComparison.Ordinal)
            && lines[2].Contains("BUFF_CREATE_OBSERVED", StringComparison.Ordinal), "End flushes buffered evidence at its original packet timestamp");
        bridge.BeginCaptureSession(2000);
        bridge.Handle(E("""{"type":"BattleOpFinishBuff","timestamp_ms":2001,"buff_inst_id":8}"""));
        check(lines[^1].Contains("BUFF_END #1 id=\"\" uid=8", StringComparison.Ordinal), "New flows clear Buff identity and sequence caches");

        lines.Clear();
        bridge.BeginCaptureSession(0);
        bridge.Handle(E("""{"type":"DUNGEON_CONTEXT","timestamp_ms":1000,"dungeon_id":"indie_battletower_test"}"""));
        bridge.Handle(E("""{"type":"BattleOpModifyBattleState","timestamp_ms":1100,"is_in_battle":true,"client_tick_tms":5}"""));
        bridge.Handle(E("""{"type":"CS_PING","timestamp_ms":9000,"client_ts":0}"""));
        bridge.EndCaptureSession();
        check(lines[^1].StartsWith("[00:00:01.100] OFFICIAL_TIMER_MISSING", StringComparison.Ordinal)
            && !lines.Any(line => line.Contains("OFFICIAL_TIMER_END", StringComparison.Ordinal)),
            "A lost official-only run reports missing completion at the last semantic packet, without counting later ping time");

        var folder = Directory.CreateTempSubdirectory("endfield-trace-spec-");
        try
        {
            using var live = LiveBattleSession.Create(new ResourceFiles(folder.FullName), new(2026, 10, 29), timeZone: TimeZoneInfo.Utc);
            var notifications = 0;
            var archive = new DateTime(2026, 10, 29, 12, 0, 0);
            using var recording = new TraceRecording(live, folder.FullName, timeZone: TimeZoneInfo.Utc, archiveTime: archive, onChanged: () => notifications++);
            var path = recording.FilePath!;
            check(recording.IsWriting(path) && File.Exists(path), "The public recording contract identifies an active writer");
            // Drive the actual typed protobuf business path into the file/live sink, rather than constructing HP trace text.
            GameSessionBusiness business = new("synthetic", recording.Handle);
            var message = JsonParser.Default.Parse("""
                {"client_data":{"op_list":[{"owner_id":"11","seq_id":1,"client_tick_tms":"1000","op_type":"BattleOpTriggerAction",
                  "trigger_action_op_data":{"inst_id":"777","owner_id":"11","template_id":{"type":"Skill","str_id":"chr_0001_test_skill"},
                  "action":{"action_id":0,"action_type":"BattleActionDamage","damage_action":{"attacker_id":"11","details":[{"target_id":"33","value":-123.5,"cur_hp":900}]}}}}]}}
                """, ProtocolCatalog.Messages["CS_BATTLE_OP"]);
            recording.BeginSession(0);
            void Observe(string name, string json)
            {
                var observation = JsonParser.Default.Parse(json, ProtocolCatalog.Messages[name]);
                business.Process(new DecodedMessage("sc", name, 1, new SessionHead(), observation, observation.ToByteArray()), 500);
            }
            Observe("SC_SELF_SCENE_INFO", """{"detail":{"char_list":[{"common_info":{"id":"101","templateid":"chr_0001_test"},"battle_info":{"battle_inst_id":"11"}}]}}""");
            Observe("SC_OBJECT_ENTER_VIEW", """{"detail":{"monster_list":[{"common_info":{"id":"303","templateid":"eny_0001_test"},"battle_info":{"battle_inst_id":"33"}}]}}""");
            business.Process(new DecodedMessage("cs", "CS_BATTLE_OP", 1, new SessionHead(), message, message.ToByteArray()), 1000);
            using var readStream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var reader = new StreamReader(readStream, Encoding.UTF8);
            var content = reader.ReadToEnd();
            check(content.Contains("HP_V2 #1 hit=124", StringComparison.Ordinal) && live.State.HitCount == 1,
                "Typed decoded damage reaches canonical disk recording and live battle ingestion");
            var report = live.SnapshotAsync().GetAwaiter().GetResult()!;
            check(((EvidenceObject)report.Get("battle")).Get("total_damage") is EvidenceInteger { Value: var total } && total == 124,
                "The connected recording path uses production report calculation with the observed hit rounding");
            readStream.Position = 0;
            check(readStream.ReadByte() == '[' && !content.Contains('\r'),
                "Canonical UTF-8 trace has no BOM or platform-newline rewriting");
            check(recording.LinesWritten == content.Count(unit => unit == '\n') && notifications == recording.LinesWritten,
                "Each completed disk/live line signals new work exactly once");
            recording.Dispose(); recording.Dispose();
            check(!recording.IsWriting(path), "Idempotent close releases the active-write contract and file handle");
            reader.Dispose(); readStream.Dispose();
            File.Move(path, path + ".moved");
            using var other = new TraceRecording(live, folder.FullName, timeZone: TimeZoneInfo.Utc, archiveTime: archive);
            using var collision = new TraceRecording(live, folder.FullName, timeZone: TimeZoneInfo.Utc, archiveTime: archive);
            check(collision.FilePath != other.FilePath && collision.FilePath!.EndsWith("_01.log", StringComparison.Ordinal),
                "Concurrent archive creation reserves unique names without overwriting a trace");
        }
        finally { folder.Delete(recursive: true); }
    }

    private static void StructuredTimerReport(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Lifecycle emitted legacy text"), eventSink: events.Add);
        foreach (var payload in new[] {
            """{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_START","timestamp_ms":1000,"game_id":"indie_battletower_synthetic","challenge_start_ts":1234}""",
            """{"type":"SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE","timestamp_ms":1500,"game_id":"indie_battletower_synthetic","time_freeze_infos":[{"time_key":0,"total_freeze_time_in_ms":100}]}""",
            """{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE","timestamp_ms":2000,"game_id":"indie_battletower_synthetic","is_pass":true,"pass_time":800}""" }) bridge.Handle(E(payload));
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(events.Select((item, index) => (index + 1, item)));
        var text = string.Concat(events.SelectMany(item => item.Type == "game_mechanics" ? ContextLegacyExporter.Lines(item, 0) : TimerLegacyExporter.Lines(item, 0)));
        var expected = TimerEvidenceCollector.Collect(text)!;
        check(EvidenceJson.PythonEquals(stream.OfficialTimerCollector.Evidence!.ToEvidence(), expected.ToEvidence()),
            "Direct official lifecycle evidence matches independent legacy collection");
        var captured = BattleReportInput.Capture(stream);
        var selected = new ReportLifecycle(_ => null).Select(captured.Calculation, captured.Timing, "");
        check(selected.Timing.GameElapsedMs == 800 && selected.Timing.OfficialPassConfirmed && selected.ObservedOfficialElapsedMs == 1000
            && EvidenceJson.PythonEquals(selected.OfficialEvidence!.ToEvidence(), expected.ToEvidence()),
            "Report selects official elapsed and quality evidence directly without legacy trace text");
        bridge.BeginCaptureSession(3000); stream.Accept(4, events[^1]);
        check(stream.OfficialTimerCollector.Evidence!.Start is null && EvidenceJson.PythonEquals(captured.Timing.CollectedOfficialEvidence!.ToEvidence(), expected.ToEvidence()),
            "Captured report timing remains isolated from later ingestion and capture resets");
    }

    private static void StructuredContext(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Context emitted legacy text"), eventSink: events.Add);
        foreach (var payload in new[] {
            """{"type":"DUNGEON_CONTEXT","timestamp_ms":1000,"dungeon_id":"indie_battletower_synthetic"}""",
            """{"type":"SC_GAME_MECHANICS_SYNC_CHALLENGE_START","timestamp_ms":1100,"game_id":"indie_battletower_synthetic"}""",
            """{"type":"BattleOpModifyBattleState","timestamp_ms":1200,"is_in_battle":true,"seq_id":0}""",
            """{"type":"BattleOpModifyBattleState","timestamp_ms":1300,"is_in_battle":false}""",
            """{"type":"SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST","timestamp_ms":1400,"game_id":"indie_battletower_synthetic","game_inst_id":"0009007199254740993"}""" }) bridge.Handle(E(payload));
        bridge.EndCaptureSession();
        var items = events.Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToArray();
        check(items.Select(item => item.Type).SequenceEqual(new[] { "dungeon", "official_timer", "dungeon", "battle_phase", "official_timer", "game_instance", "official_timer", "battle_timer" }),
            "Official phase and leave preserve ordered instance, missing timer and reset events");
        check(items.Where(item => item.Type != "dungeon").SelectMany(item => item.Type == "game_instance" ? ContextLegacyExporter.Lines(item, 0) : TimerLegacyExporter.Lines(item, 0)).SequenceEqual(new[] {
            "[00:00:01.100] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower_synthetic\n",
            "[00:00:01.200] BATTLE_PHASE_START seq=0 source=BattleOpModifyBattleState gameId=indie_battletower_synthetic\n",
            "[00:00:01.300] OFFICIAL_TIMER_AWAIT source=BattleOpModifyBattleState gameId=indie_battletower_synthetic officialStartSeen=1\n",
            "[00:00:01.400] GAME_INST_LEAVE source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST gameId=indie_battletower_synthetic gameInstId=0009007199254740993\n",
            "[00:00:01.400] OFFICIAL_TIMER_MISSING boundary=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST packetBattleActive=0 officialExpected=1 officialStartSeen=1 gameId=indie_battletower_synthetic\n",
            "[00:00:01.400] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST\n" }), "Independent phase and boundary export preserves exact bytes");
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(items.Select((item, index) => (index + 1, item)));
        check(items[5].Data.Get("game_inst_id") is EvidenceText { Value: "9007199254740993" }
            && stream.TimerObservedTimes.OrderBy(pair => pair.Key).SequenceEqual(new Dictionary<int, long> { [2]=1100, [5]=1300, [6]=1400, [7]=1400, [8]=1400 }),
            "Wide instance IDs and timer evidence positions survive JSONL");
        check(stream.Timers.GameElapsedMs is null && stream.Timers.OfficialElapsedMs is null && !stream.Timers.EndSeen && !stream.Timers.ChallengePassConfirmed,
            "Phase, await and missing observations cannot certify an elapsed time or completion");

        events.Clear();
        foreach (var payload in new[] {
            """{"type":"SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE","timestamp_ms":1000,"game_inst_id":18446744073709551615,"is_hunter_mode":false,"time_freeze_infos":[null,{"time_key":0,"total_freeze_time_in_ms":-7},{"time_key":"02","total_freeze_time_in_ms":3.9},{}]}""",
            """{"type":"SC_RESET_BATTLE_STATUS","timestamp_ms":2000}""",
            """{"type":"SC_RESET_BATTLE_STATUS","timestamp_ms":3000,"reason":0,"inst_id":null,"battle_inst_id":"00012"}""",
            """{"type":"SESSION_WARNING","timestamp_ms":4000,"kind":"","direction":null,"missing_bytes":0,"startup_tcp_gap_count":null}""",
            """{"type":"SC_SCENE_SET_BATTLE","timestamp_ms":5000,"in_battle":false}""",
            """{"type":"SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD","timestamp_ms":6000}""" }) bridge.Handle(E(payload));
        items = events.Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToArray();
        check(items.SelectMany(item => ContextLegacyExporter.Lines(item, 330)).SequenceEqual(new[] {
            "[05:30:01.000] GAME_MECHANICS_TIME_FREEZE source=SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE gameInstId=18446744073709551615 isHunterMode=0 count=4 freezeInfos=[0:-7,2:3,0:0] totalFreezeMs=3\n",
            "[05:30:02.000] BATTLE_RESET_STATUS\n", "[05:30:03.000] BATTLE_RESET_STATUS reason=0 battleInst=00012\n",
            "[05:30:04.000] SESSION_WARNING kind=unknown direction=unknown missingBytes=0 gapCount=unknown\n",
            "[05:30:05.000] SCENE_BATTLE_STATE source=SC_SCENE_SET_BATTLE inBattle=0\n",
            "[05:30:06.000] SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD source=SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD\n" }), "Context export preserves raw freeze count, signs, optional fields, timezone and bare reset");
        stream = StructuredDamageSpecs.Stream(); stream.Accept(items.Select((item, index) => (index + 1, item)));
        check(items[0].Data.Get("game_inst_id") is EvidenceText { Value: "18446744073709551615" } && items[2].Data.Fields.ContainsKey("event_inst_id")
            && items[2].Data.Get("event_inst_id") is EvidenceNull && items[2].Data.Get("battle_inst_id") is EvidenceText { Value: "12" }
            && !items[1].Data.Fields.ContainsKey("reason"), "Context retains instance precision and null versus absent fields");
        check(stream.FirstContextMs == 1000 && stream.LastContextMs == 6000 && stream.TimerObservedTimes.Count == 1 && stream.TimerObservedTimes[1] == 1000
            && stream.PartyActorIds.Count == 0 && !stream.Timers.ChallengePassConfirmed && stream.Timers.GameElapsedMs is null,
            "Context tracks time without inventing actors, completion or elapsed time");
        events.Clear();
        bridge = new(_ => throw new InvalidOperationException("Timer emitted legacy text"), eventSink: events.Add);
        bridge.Handle(E("""{"type":"BattleOpModifyBattleState","timestamp_ms":7000,"is_in_battle":true}"""));
        bridge.EndCaptureSession();
        check(events.Select(item => item.Type).SequenceEqual(new[] { "battle_timer", "battle_timer_missing" })
            && TimerLegacyExporter.Lines(events[1], 0).Single() == "[00:00:07.000] BATTLE_TIMER_MISSING boundary=CAPTURE_SESSION_LOST packetBattleActive=1 officialExpected=0 officialStartSeen=0\n",
            "Lost packet capture records a missing boundary rather than a manufactured end");
    }

    private static void StructuredStage(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Stage emitted legacy text"), eventSink: events.Add);
        bridge.Handle(E("""{"type":"DUNGEON_CONTEXT","timestamp_ms":1000,"dungeon_id":" synthetic ","is_calc":true,"is_pass":true,"scene_num_id":0,"scene_id":null,"is_reward":false}"""));
        bridge.Handle(E("""{"type":"CONTRACT_TAGS","timestamp_ms":2000,"dungeon_id":"synthetic","tag_ids":[],"tagIds":[0,-2,"0003",3,4.8,"bad"],"score":0,"direction":"sc","msg_id":0}"""));
        var stages = events.Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToArray();
        check(stages.Select(item => item.Type).SequenceEqual(new[] { "battle_result", "dungeon", "contracts" }), "Stage results and replayed context retain source order");
        check(stages[1].Data.Fields.ContainsKey("scene_id") && stages[1].Data.Get("scene_id") is EvidenceNull
            && stages[2].Data.Get("message_id") is EvidenceInteger { Value.IsZero: true }, "Stage data preserves explicit null and message zero");
        check(stages.SelectMany(item => StageLegacyExporter.Lines(item, 0)).SequenceEqual(new[] {
            "[00:00:01.000] BATTLE_RESULT source=DUNGEON_CONTEXT dungeonId=synthetic isCalc=1 isPass=1\n",
            "[00:00:01.000] DUNGEON_CONTEXT dungeonId=synthetic source=packet scene=0 isReward=0 isCalc=1 isPass=1\n",
            "[00:00:02.000] CONTRACT_TAGS dungeonId=synthetic source=packet tagIds=[-2,3,3,4] score=0 direction=sc\n" }), "Independent stage export retains raw signs, aliases, order and presence");
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(stages.Select((item, index) => (index + 1, item)));
        check(stream.Timers.DungeonId == "synthetic" && stream.Timers.ChallengePassConfirmed && stream.Timers.CompletionSource == "DUNGEON_CONTEXT",
            "Typed stage uses shared dungeon and completion semantics");
        check(stream.Timers.ContractTagIds.SequenceEqual(new BigInteger[] { 2, 3, 3, 4 }) && stream.Timers.ContractTagScore == 0,
            "Typed contracts retain legacy magnitude projection, duplicates and zero score");
        check(stream.Timers.GameElapsedMs is null && stream.TimerObservedTimes.Count == 0 && stream.PartyActorIds.Count == 0,
            "Stage completion alone creates neither elapsed time nor actor identity");
        foreach (var (kind, data) in new[] { ("dungeon", """{"source":"packet"}"""), ("contracts", """{"tag_ids":[7]}"""),
            ("battle_result", """{"source":"packet","dungeon_id":7}""") })
        {
            var clean = StructuredDamageSpecs.Stream();
            try { clean.Accept(1, new TraceEvent(1, 1000, kind, E(data), E("{}"))); throw new InvalidOperationException("Invalid stage accepted"); }
            catch (InvalidDataException) { check(clean.FirstContextMs is null && clean.Timers.DungeonId is null, "Invalid stage rejected before context mutation"); }
        }
    }

    private static void StructuredTimer(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Timer emitted legacy text"), eventSink: events.Add);
        bridge.BeginCaptureSession(1000);
        bridge.Handle(E("""{"type":"BattleOpModifyBattleState","timestamp_ms":1100,"is_in_battle":true,"client_tick_tms":2000,"seq_id":0}"""));
        bridge.Handle(E("""{"type":"BattleOpModifyBattleState","timestamp_ms":2100,"is_in_battle":false,"client_tick_tms":2600,"seq_id":1}"""));
        bridge.EndCaptureSession();
        check(events.Count == 3 && events.All(item => item.Type == "battle_timer"), "Packet and capture boundaries emit timer objects");
        var timers = events.Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToArray();
        check(timers.SelectMany(item => TimerLegacyExporter.Lines(item, 330)).SequenceEqual(new[] {
            "[05:30:01.000] GAME_TIMER_RESET source=CAPTURE_SESSION_START\n",
            "[05:30:01.100] GAME_TIMER_START seq=0 source=PacketBattleState startMs=2000 expireMs=0 official=1\n",
            "[05:30:02.100] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=1000 startMs=2000 endMs=2600 expireMs=0 sane=1 official=1 packetElapsedMs=600\n" }), "Independent timer export preserves time domains, field order, timezone and LF");
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(timers.Select((item, index) => (index + 1, item)));
        check(stream.Timers.GameElapsedMs == 1000 && stream.Timers.PacketElapsedMs == 600 && stream.Timers.StartSeen && stream.Timers.EndSeen,
            "Typed packet timer retains distinct capture and packet elapsed time");
        check(stream.TimerObservedTimes.Count == 3 && stream.TimerObservedTimes[3] == 2100 && stream.Hits.Hits.Count == 0,
            "Typed timer records evidence positions without manufacturing damage");
        foreach (var value in new[] { "null", "0", "-1", "true", "\"unknown\"" })
        {
            List<TraceEvent> observed = []; TraceBridge raw = new(_ => { }, eventSink: observed.Add);
            raw.Handle(E("{\"type\":\"SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE\",\"timestamp_ms\":2000,\"pass_time\":" + value + "}"));
            var clean = StructuredDamageSpecs.Stream(); clean.Accept(1, observed.Single());
            check(clean.Timers.OfficialElapsedMs is null && !clean.Timers.EndSeen && !clean.Timers.ChallengePassConfirmed,
                "Invalid raw official duration does not become elapsed: " + value);
            if (value == "true") check(TimerLegacyExporter.Lines(observed.Single(), 0).Single().Contains("passTime=True", StringComparison.Ordinal),
                "Raw official boolean is not reinterpreted as one millisecond");
        }
        var restart = StructuredDamageSpecs.Stream();
        restart.Accept(1, new TraceEvent(1, 1000, "official_timer", E("""{"phase":"end","source":"official","pass_time":750,"is_pass":true}"""), E("{}")));
        check(restart.Timers.OfficialElapsedMs == 750 && restart.Timers.OfficialPassConfirmed, "Observed official completion retains its duration and pass evidence");
        restart.Accept(2, new TraceEvent(2, 2000, "official_timer", E("""{"phase":"start","source":"official","game_id":"synthetic"}"""), E("{}")));
        check(restart.Timers.OfficialElapsedMs is null && restart.Timers.GameElapsedMs is null && !restart.Timers.OfficialPassConfirmed && !restart.Timers.EndSeen,
            "New explicit challenge start clears prior completion");
        var fallback = StructuredDamageSpecs.Stream();
        fallback.Accept(1, new TraceEvent(1, 1000, "battle_timer", E("""{"phase":"end","source":"BattleOpModifyBattleState","elapsed_ms":500,"sane":true,"official":false}"""), E("{}")));
        check(fallback.Timers.GameElapsedMs is null && !fallback.Timers.EndSeen, "Fallback packet timer cannot certify elapsed time");
        var reset = StructuredDamageSpecs.Stream();
        reset.Accept(1, new TraceEvent(1, 2000, "official_timer", E("""{"phase":"end","source":"official","pass_time":900,"is_pass":true}"""), E("{}")));
        reset.Entities.CriticalAttributesByActor["11"] = new CriticalAttributeObservation(null);
        reset.Accept(2, new TraceEvent(2, 3000, "battle_timer", E("""{"phase":"reset","source":"CAPTURE_SESSION_START"}"""), E("{}")));
        check(reset.Entities.CriticalAttributesByActor.Count == 0 && reset.Timers.OfficialElapsedMs == 900 && reset.Timers.OfficialPassConfirmed,
            "Capture reset clears critical observations and retains legacy timer scope semantics");
        foreach (var data in new[] { """{"phase":"end"}""", """{"phase":"invalid","source":"PacketBattleState"}""" })
        {
            var clean = StructuredDamageSpecs.Stream();
            try { clean.Accept(1, new TraceEvent(1, 1000, "battle_timer", E(data), E("{}"))); throw new InvalidOperationException("Invalid timer accepted"); }
            catch (InvalidDataException) { check(clean.FirstContextMs is null && clean.TimerObservedTimes.Count == 0, "Invalid timer rejected before context mutation"); }
        }
    }

    private static void StructuredClock(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Clock emitted legacy text"), eventSink: events.Add);
        bridge.Handle(E("""{"type":"BattleOpAddBuff","timestamp_ms":1000,"buff_inst_id":8,"int_id":55,"target_inst_id":11,"src_inst_id":22}"""));
        bridge.Handle(E("""{"type":"CS_PING","timestamp_ms":9000,"client_ts":9007199254740993,"server_ts":-1,"logical_ts":0,"msg_id":0,"raw_body_hex":""}"""));
        bridge.Handle(E("""{"type":"GAME_CLOCK_TICK","timestamp_ms":9100,"source":"CS_BATTLE_OP","tick_ms":"00042","seq_id":0}"""));
        bridge.Handle(E("""{"type":"SC_GAME_TIME_FREEZE_END_RSP","timestamp_ms":9200,"in_time_freeze":false,"reason":0,"msg_id":null}"""));
        bridge.Handle(E("""{"type":"CS_GAME_TIME_FREEZE_START_REQ","timestamp_ms":9300,"raw_body_hex":""}"""));
        check(events.Select(item => item.Type).SequenceEqual(new[] { "clock_sync", "clock_tick", "time_freeze_state", "time_freeze_request" }), "Structured clocks bypass pending BUFF groups");
        foreach (var source in new[] {
            """{"type":"GAME_CLOCK_TICK","timestamp_ms":9400,"source":"CS_BATTLE_OP","tick_ms":0}""",
            """{"type":"GAME_CLOCK_TICK","timestamp_ms":9400,"source":"CS_BATTLE_OP","tick_ms":-1}""",
            """{"type":"GAME_CLOCK_TICK","timestamp_ms":9400,"source":"OTHER","tick_ms":42}""", """{"type":"CS_PING","client_ts":0}""" }) bridge.Handle(E(source));
        check(events.Count == 4, "Invalid tick and missing capture time do not fabricate a clock event");
        bridge.EndCaptureSession();
        check(events[4].Type == "buff_start" && events[4].CapturedAtMs == 1000
            && events.Select(item => item.Sequence).SequenceEqual(Enumerable.Range(1, events.Count).Select(index => (long)index)), "Clock bypass preserves original buffered timestamps and shared sequence");
        var clocks = events.Take(4).Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToArray();
        check(clocks[0].Data.Get("client_ts") is EvidenceInteger { Value: var client } && client == 9007199254740993
            && !clocks[3].Data.Fields.ContainsKey("message_id") && clocks[2].Data.Fields.ContainsKey("message_id"), "Clock JSONL retains wide timestamps and missing versus null message identity");
        check(clocks.SelectMany(item => ClockLegacyExporter.Lines(item, 330)).SequenceEqual(new[] {
            "[05:30:09.000] GAME_CLOCK_SYNC source=CS_PING msgId=0 captureMs=9000 clientTs=9007199254740993 logicalTs=0 rawBodyHex=empty\n",
            "[05:30:09.100] GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs=42 seq=0\n",
            "[05:30:09.200] GAME_TIME_FREEZE_STATE source=SC_GAME_TIME_FREEZE_END_RSP inTimeFreeze=0 reason=0 msgId=None rawBodyHex=unknown\n",
            "[05:30:09.300] GAME_TIME_FREEZE_REQUEST source=CS_GAME_TIME_FREEZE_START_REQ reason=unknown msgId=unknown rawBodyHex=empty\n" }), "Independent clock export retains zero, negative raw evidence, timezone, unknowns and LF");
        check(ClockWire.Observation(clocks[0]).ServerTs is null && ClockWire.Observation(clocks[2]).Frozen == false, "Negative timestamp stays unusable and explicit false remains an observed freeze state");
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(clocks.Select((item, index) => (index + 1, item)));
        check(stream.Hits.Hits.Count == 0 && stream.PartyActorIds.Count == 0 && stream.TimerObservedTimes.Count == 0
            && stream.Timers.GameElapsedMs is null && stream.LastContextMs == 9300, "Clock ingestion does not manufacture authoritative battle time or damage");
        var invalid = new TraceEvent(1, 0, "clock_sync", E("{}"), E("{}")); var clean = StructuredDamageSpecs.Stream();
        try { clean.Accept(1, invalid); throw new InvalidOperationException("Clock without source accepted"); }
        catch (InvalidDataException) { check(clean.FirstContextMs is null, "Malformed clock rejected before context mutation"); }
    }
}
