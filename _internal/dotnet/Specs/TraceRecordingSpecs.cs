using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Sessions;
using EndfieldLogs.Runtime.Tracing;
using Google.Protobuf;

internal static class TraceRecordingSpecs
{
    private static byte[] Bytes(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using MemoryStream bytes = new(); stream.CopyTo(bytes); return bytes.ToArray();
    }
    private static IReadOnlyList<TraceRecord> Read(string path)
    {
        using TraceJsonlReader reader = new();
        var records = reader.Feed(Bytes(path));
        if (reader.PendingBytes != 0) throw new InvalidDataException("Unflushed trace batch");
        return records;
    }
    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-jsonl-recording-");
        try
        {
            var archive = new DateTime(2026, 11, 1, 12, 0, 0);
            Dictionary<string, string> resources = new() { ["runtime"] = "synthetic-中文" };
            TraceHeader header = new("synthetic", 1, null, "csharp", "test", "Asia/Shanghai", 480, resources);
            using var live = LiveBattleSession.Create(new ResourceFiles(folder.FullName), new(2026, 11, 1), new(Summary: false), TimeZoneInfo.Utc);
            using var streams = LiveAnalysisStreams.Create(new ResourceFiles(folder.FullName), new(2026, 11, 1), TimeZoneInfo.Utc);
            using var summarySubscription = streams.Subscribe();
            using var fullSubscription = streams.Subscribe(compact: false);
            streams.FlushPendingAsync().GetAwaiter().GetResult();
            TraceRecording? active = null;
            List<IReadOnlyList<TraceEvent>> batches = []; var notifications = 0;
            using var recording = TraceRecording.CreateStructured(batch =>
            {
                // Read the active file inside delivery: disk framing must already be complete.
                var disk = Read(active!.FilePath!).OfType<TraceEvent>().TakeLast(batch.Count).ToArray();
                check(disk.Select(TraceJsonl.Serialize).SequenceEqual(batch.Select(TraceJsonl.Serialize)),
                    "The complete canonical business batch is reader-visible before direct live delivery");
                batches.Add(batch); live.FeedEvents(batch); streams.FeedEvents(batch);
            }, header, folder.FullName, archiveTime: archive, onChanged: () => notifications++);
            active = recording;
            var firstPath = recording.FilePath!;
            check(recording.IsWriting(firstPath) && Read(firstPath).Single() is TraceHeader { Volume: 1 },
                "A structured recording reserves its file and flushes its header before accepting events");
            resources["runtime"] = "changed";
            recording.BeginSession(0);
            GameSessionBusiness business = new("synthetic", recording.Handle);
            void Observe(string name, string json, long time, string direction = "sc")
            {
                var message = JsonParser.Default.Parse(json, ProtocolCatalog.Messages[name]);
                business.Process(new DecodedMessage(direction, name, 1, new SessionHead(), message, message.ToByteArray()), time);
            }
            Observe("SC_SELF_SCENE_INFO", """{"detail":{"char_list":[{"common_info":{"id":"101","templateid":"chr_0001_test"},"battle_info":{"battle_inst_id":"11"}}]}}""", 500);
            Observe("SC_OBJECT_ENTER_VIEW", """{"detail":{"monster_list":[{"common_info":{"id":"303","templateid":"eny_0001_test"},"battle_info":{"battle_inst_id":"33"}}]}}""", 500);
            const string damage = """
                {"client_data":{"op_list":[{"owner_id":"11","seq_id":1,"client_tick_tms":"1000","op_type":"BattleOpTriggerAction",
                "trigger_action_op_data":{"inst_id":"777","owner_id":"11","template_id":{"type":"Skill","str_id":"chr_0001_test_skill"},
                "action":{"action_id":0,"action_type":"BattleActionDamage","damage_action":{"attacker_id":"11","details":[{"target_id":"33","value":-123.5,"cur_hp":900}]}}}}]}}
                """;
            Observe("CS_BATTLE_OP", damage, 1000, "cs");
            var before = live.SnapshotAsync().GetAwaiter().GetResult()!;
            check(live.State.HitCount == 1 && ((EvidenceObject)before.Get("battle")).Get("total_damage") is EvidenceInteger { Value: var total } && total == 124,
                "Decoded protobuf damage is recorded and reaches the real typed calculator with existing rounding");
            var count = recording.EventsWritten;
            recording.Handle(new BattleLogEvent("synthetic", 1100, "BattleOpAddBuff", new Dictionary<string, object?>
                { ["buff_inst_id"] = 71L, ["str_id"] = "buff_test", ["src_inst_id"] = 11L, ["target_inst_id"] = 33L }));
            check(recording.EventsWritten == count, "An incomplete BUFF group remains pending before rotation");
            var nextPath = recording.RotateVolume(archive);
            var nextHeader = (TraceHeader)Read(nextPath).Single();
            check(nextPath.EndsWith("_01.jsonl", StringComparison.Ordinal) && !recording.IsWriting(firstPath) && recording.IsWriting(nextPath)
                && nextHeader.Volume == 2 && nextHeader.PreviousVolume == new TracePreviousVolume(1, Path.GetFileName(firstPath))
                && nextHeader.RecordingId == header.RecordingId && nextHeader.Resources["runtime"] == "synthetic-中文"
                && nextHeader.TimeZoneOffsetMinutes == 480, "Rotation preserves recording identity and immutable metadata and reserves a linked next volume");
            using (new FileStream(firstPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
            check(live.State.HitCount == 1 && EvidenceJson.PythonEquals(before, live.SnapshotAsync().GetAwaiter().GetResult()!),
                "Rotation releases the old handle without resetting live calculation or its current result");
            recording.Handle(new BattleLogEvent("synthetic", 1200, "BattleOpFinishBuff", new Dictionary<string, object?> { ["buff_inst_id"] = 71L }));
            var continued = Read(nextPath).OfType<TraceEvent>().ToArray();
            check(continued.Select(item => item.Type).SequenceEqual(["buff_start", "buff_creation", "buff_end"])
                && continued[0].CapturedAtMs == 1100 && continued[^1].Data.Get("template") is EvidenceText { Value: "buff_test" },
                "Pending BUFF identity, ordering and original capture time survive volume rotation");
            Observe("CS_BATTLE_OP", damage, 2000, "cs");
            check(live.State.HitCount == 2 && ((EvidenceObject)live.SnapshotAsync().GetAwaiter().GetResult()!.Get("battle")).Get("total_damage")
                is EvidenceInteger { Value: var allDamage } && allDamage == 248,
                "Damage in the next volume appends to the same real live calculation");
            var finalPath = recording.RotateVolume(archive.AddDays(1));
            check(Path.GetDirectoryName(finalPath) == Path.GetDirectoryName(firstPath)
                && ((TraceHeader)Read(finalPath).Single()).PreviousVolume == new TracePreviousVolume(2, Path.GetFileName(nextPath)),
                "A manual split after midnight retains same-directory volume links");
            streams.FlushPendingAsync().GetAwaiter().GetResult(); // The capture reset clears each observer first.
            streams.FlushPendingAsync().GetAwaiter().GetResult();
            check(streams.State().HitCount == 2 && streams.State(compact: false).HitCount == 2,
                "The recorded business batch enters both demanded production sessions");
            check(streams.Current().Snapshot?.Get("battle") is EvidenceObject summaryBattle
                && EvidenceJson.PythonEquals(summaryBattle.Get("total_damage"), new EvidenceInteger(248)),
                "The real summary publisher receives typed damage groups");
            check(EvidenceJson.PythonEquals(streams.Current(compact: false).Snapshot!, LiveSnapshotPublisher.TransportCopy(live.ReadSnapshot()!)),
                "One recorded event group drives real summary and full-report publishers without legacy text conversion");
            recording.Dispose(); recording.Dispose();
            var events = Read(firstPath).Concat(Read(nextPath)).Concat(Read(finalPath)).OfType<TraceEvent>().ToArray();
            check(events.Select(item => item.Sequence).SequenceEqual(Enumerable.Range(1, events.Length).Select(index => (long)index))
                && recording.EventsWritten == events.Length && recording.LinesWritten == 0
                && notifications == batches.Count + 2 && batches.Sum(batch => batch.Count) == events.Length,
                "Linked volumes keep one continuous sequence and publish once per complete business group");
            check(!recording.IsWriting(finalPath) && Bytes(firstPath)[0] == '{' && !Bytes(firstPath).Contains((byte)'\r')
                && !Bytes(nextPath).Contains((byte)'\r'), "Idempotent structured close releases the file and retains BOM-free UTF-8/LF");
            using (new FileStream(finalPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
            using var memoryOnly = TraceRecording.CreateStructured(_ => { }, header);
            memoryOnly.BeginSession(0);
            check(memoryOnly.FilePath is null && memoryOnly.EventsWritten == 1, "Typed live-only recording works without a file sink");
            using var failed = TraceRecording.CreateStructured(_ => throw new IOException("synthetic sink failure"), header);
            try { failed.BeginSession(0); throw new InvalidOperationException("Delivery failure swallowed"); }
            catch (IOException) { check(true, "Structured delivery errors propagate to the capture owner"); }
            try { failed.BeginSession(0); throw new InvalidOperationException("Failed recording resumed"); }
            catch (InvalidOperationException error) when (error.Message.Contains("cannot continue", StringComparison.Ordinal))
            { check(true, "A failed recording does not silently publish a later group"); }
        }
        finally { folder.Delete(recursive: true); }
    }
}
