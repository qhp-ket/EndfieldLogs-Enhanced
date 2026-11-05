using System.Collections.Concurrent;
using System.Text;
using System.Text.Json.Nodes;
using System.Net.WebSockets;
using System.Net;
using System.Net.Sockets;
using EndfieldLogs.Capture;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Native.Capture;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Capture;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;
using Google.Protobuf;

internal static class GameCaptureServiceSpecs
{
    internal sealed class Backend : ICaptureBackend
    {
        public MessageRegistry Registry { get; } = new("""[{"msg_id":1,"class_name":"CS_BATTLE_OP"}]""",
            """[{"msg_id":2,"class_name":"SC_SELF_SCENE_INFO"},{"msg_id":3,"class_name":"SC_OBJECT_ENTER_VIEW"}]""");
        public readonly byte[] Key = Enumerable.Range(0, 32).Select(index => (byte)index).ToArray();
        public readonly TaskCompletionSource Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public Action<CapturedPacket>? Receive;
        public bool GameRunning;
        public int BackendCloses, DeviceCloses;
        private Action<string, Exception?>? diagnostic;
        public GameProcessObservation ObserveGame() => new(Volatile.Read(ref GameRunning), Volatile.Read(ref GameRunning) ? Flow : null);
        public ICaptureDevices OpenCapture(Action<CapturedPacket> onPacket, Action<string, Exception?> onDiagnostic)
        { Receive = onPacket; diagnostic = onDiagnostic; return new DeviceOwner(this); }
        public byte[] DecryptLogin(byte[] encrypted) => encrypted;
        public byte[] DecryptKey(byte[] encrypted) => Key;
        private sealed class DeviceOwner(Backend owner) : ICaptureDevices
        {
            public IReadOnlyList<DeviceInfo> Devices => [new("synthetic", "Synthetic", ["192.0.2.1"], 0)];
            public CaptureStatistics Statistics() => new(5, 1, 0);
            public void Start() => owner.Started.TrySetResult();
            public void Dispose()
            {
                owner.DeviceCloses++;
                owner.diagnostic?.Invoke("capture closed", null);
            }
        }
        public void Dispose() => BackendCloses++;
    }
    private static readonly FlowKey Flow = new(new("192.0.2.1", 31001), new("203.0.113.1", 30000));
    private static void Wait(Task task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
    private static byte[] Frame(byte[] head, byte[] body) => [(byte)head.Length, (byte)body.Length, (byte)(body.Length >> 8), ..head, ..body];
    private static string ReadActive(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using StreamReader reader = new(stream, Encoding.UTF8); return reader.ReadToEnd();
    }

    public static void Run(Action<bool, string> check)
    {
        var folder = Directory.CreateTempSubdirectory("endfield-service-spec-");
        try
        {
            var resources = Path.Combine(folder.FullName, "internal"); Directory.CreateDirectory(Path.Combine(resources, "jsondata"));
            File.WriteAllText(Path.Combine(resources, "jsondata", "CharacterNameIndex.json"), """{"chr_0001_test":"测试角色"}""");
            foreach (var configuredFormat in new string?[] { null, "legacy", "jsonl" })
            {
                var format = configuredFormat ?? "jsonl";
                var extension = format == "jsonl" ? ".jsonl" : ".log";
                var logs = Path.Combine(folder.FullName, "logs-" + (configuredFormat ?? "default")); var debug = Path.Combine(folder.FullName, "debug-" + (configuredFormat ?? "default"));
                Backend backend = new(); using CancellationTokenSource stop = new();
                TaskCompletionSource live = new(TaskCreationOptions.RunContinuationsAsynchronously);
                TaskCompletionSource hit = new(TaskCreationOptions.RunContinuationsAsynchronously);
                TaskCompletionSource secondHit = new(TaskCreationOptions.RunContinuationsAsynchronously);
                ConcurrentQueue<LiveSnapshotFrame> snapshots = new(); ConcurrentQueue<string> diagnostics = new();
                GameCaptureOptions options = new("SyntheticGame.exe", "unused", "unused", logs, DebugDirectory: debug, WebSocketPort: 0);
                if (configuredFormat is not null) options = options with { TraceFormat = configuredFormat };
                GameCaptureService service = new(new(resources), options, () => backend);
                var run = service.RunAsync((frame, _) =>
                {
                    snapshots.Enqueue(frame);
                    if (frame.Snapshot?.Get("battle") is EvidenceObject battle && battle.Get("total_damage") is EvidenceInteger { Value: var total } && total == 124)
                        hit.TrySetResult();
                    if (frame.Snapshot?.Get("battle") is EvidenceObject nextBattle && nextBattle.Get("total_damage") is EvidenceInteger { Value: var nextTotal } && nextTotal == 248)
                        secondHit.TrySetResult();
                    return ValueTask.CompletedTask;
                }, onStatus: snapshot => { if (snapshot.Flow.Live) live.TrySetResult(); },
                    diagnostic: (message, _) => diagnostics.Enqueue(message), cancellationToken: stop.Token);
                try
                {
                    Wait(backend.Started.Task);
                    using ClientWebSocket network = new();
                    Wait(network.ConnectAsync(new(service.WebSocketEndpoint!, "?analysis=summary"), stop.Token));
                    check(LoopbackWebSocketSpecs.Read(network)["type"]!.GetValue<string>() == "hello",
                        "The running capture composition exposes its own native WebSocket service");
                    var trace = Directory.GetFiles(logs, "trace_*" + extension, SearchOption.AllDirectories).Single();
                    check(service.IsWriting(trace) && service.ActiveTracePath == trace && service.Status?.Running == true, "The composed service exposes its active trace after native startup");
                    Volatile.Write(ref backend.GameRunning, true);
                    backend.Receive!(new(1000, Flow.Client, Flow.Server, 0, Frame([], []), "synthetic"));
                    var login = Frame([], [0x1a, 1, 0, 0x22, 12, ..new byte[12]]);
                    backend.Receive(new(1001, Flow.Server, Flow.Client, 0, login, "synthetic"));
                    Wait(live.Task);
                    check(service.Status?.Flow.State == ServiceState.Live, "The production composition advances through process discovery and the actual split-direction login");
                    var cipher = new Xxe1(backend.Key, new byte[12], 1); var serverSequence = login.Length;
                    byte[] SendServer(int id, string type, string json, bool unknown = false)
                    {
                        var message = JsonParser.Default.Parse(json, ProtocolCatalog.Messages[type]);
                        var body = unknown ? message.ToByteArray().Concat(new byte[] { 0xf8, 0x7f, 1 }).ToArray() : message.ToByteArray();
                        var encrypted = cipher.Process([8, (byte)id, ..body]);
                        var wire = Frame(encrypted[..2], encrypted[2..]);
                        backend.Receive(new(1100, Flow.Server, Flow.Client, serverSequence, wire, "synthetic")); serverSequence += wire.Length;
                        return body;
                    }
                    var raw = SendServer(2, "SC_SELF_SCENE_INFO", """{"detail":{"char_list":[{"common_info":{"id":"101","templateid":"chr_0001_test"},"battle_info":{"battle_inst_id":"11"}}]}}""", unknown: true);
                    SendServer(3, "SC_OBJECT_ENTER_VIEW", """{"detail":{"monster_list":[{"common_info":{"id":"303","templateid":"eny_0001_test"},"battle_info":{"battle_inst_id":"33"}}]}}""");
                    var damage = JsonParser.Default.Parse("""
                        {"client_data":{"op_list":[{"owner_id":"11","seq_id":1,"client_tick_tms":"1200","op_type":"BattleOpTriggerAction",
                        "trigger_action_op_data":{"inst_id":"777","owner_id":"11","template_id":{"type":"Skill","str_id":"chr_0001_test_skill"},
                        "action":{"action_id":0,"action_type":"BattleActionDamage","damage_action":{"attacker_id":"11","details":[{"target_id":"33","value":-123.5,"cur_hp":900}]}}}}]}}
                        """, ProtocolCatalog.Messages["CS_BATTLE_OP"]);
                    var clientCipher = new Xxe1(backend.Key, new byte[12], 1);
                    var client = clientCipher.Process([8, 1, ..damage.ToByteArray()]);
                    var clientWire = Frame(client[..2], client[2..]);
                    backend.Receive(new(1200, Flow.Client, Flow.Server, 3, clientWire, "synthetic"));
                    Wait(hit.Task);
                    JsonNode remote;
                    do { remote = LoopbackWebSocketSpecs.Read(network); }
                    while (remote["type"]?.GetValue<string>() != "analysis_summary" || remote["snapshot"]?["battle"]?["total_damage"]?.GetValue<int>() != 124);
                    check(remote["snapshot"]!["battle"]!["total_damage"]!.GetValue<int>() == 124,
                        "The same encrypted capture produces matching local-observer and real WebSocket damage results");
                    check(snapshots.Any(frame => frame.Snapshot?.Get("participants") is EvidenceArray { Items.Count: > 0 }),
                        "Encrypted protobuf reaches production calculation and compact participant publication without bypassing trace ingestion");
                    var content = ReadActive(trace);
                    if (format == "jsonl")
                    {
                        var rows = content.Split('\n', StringSplitOptions.RemoveEmptyEntries);
                        var header = (TraceHeader)TraceJsonl.Parse(rows[0], header: true);
                        var recorded = rows.Skip(1).Select(line => (TraceEvent)TraceJsonl.Parse(line, header: false)).ToArray();
                        check(header.Language == "csharp" && header.Volume == 1 && header.PreviousVolume is null
                            && header.TimeZoneOffsetMinutes == (int)TimeZoneInfo.Local.GetUtcOffset(DateTime.Now).TotalMinutes
                            && recorded.Any(item => item.Type == "damage")
                            && recorded.Select(item => item.Sequence).SequenceEqual(Enumerable.Range(1, recorded.Length).Select(value => (long)value))
                            && !Directory.GetFiles(logs, "*.log", SearchOption.AllDirectories).Any(),
                            "Structured service records ordered business events with its actual zone and emits no continuous legacy log");
                        content = string.Concat(recorded.SelectMany(item => TraceLegacyExporter.Lines(item, header.TimeZoneOffsetMinutes)));
                    }
                    check(content.Contains("HP_V2 #1 hit=124", StringComparison.Ordinal) && content.Contains("chr_0001_test", StringComparison.Ordinal),
                        "The canonical archive retains template identity and observed hit rounding");
                    var ndjson = Directory.GetFiles(logs, "session_*.ndjson", SearchOption.AllDirectories).Single();
                    check(service.IsWriting(ndjson), "Public writing query covers active session NDJSON as well as trace logs");
                    var events = ReadActive(ndjson).Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(line => JsonNode.Parse(line)!).ToArray();
                    check(events.Any(value => value["type"]!.GetValue<string>() == "BattleOpTriggerAction")
                        && events.Any(value => value["type"]!.GetValue<string>() == "SC_SELF_SCENE_INFO"
                            && value["char_list"]![0]!["display_name"]?.GetValue<string>() == "测试角色")
                        && events.All(value => value["session_id"] is not null),
                        "Session NDJSON retains public events, explicit session identity and names from CharacterNameIndex");
                    var proto = Directory.GetFiles(debug, "*.json", SearchOption.AllDirectories).Select(path => JsonNode.Parse(File.ReadAllText(path))!)
                        .Single(value => value["class_name"]?.GetValue<string>() == "SC_SELF_SCENE_INFO" && value["type"]?.GetValue<string>() == "debug_proto");
                    check(Convert.FromBase64String(proto["raw_body_base64"]!.GetValue<string>()).SequenceEqual(raw)
                        && proto["raw_body_size"]!.GetValue<int>() == raw.Length
                        && proto["protobuf_schema_files_sha256"]!.AsObject().Count > 0,
                        "Replay diagnostics retain unknown protobuf fields, exact decompressed body bytes and descriptor provenance");
                    var status = JsonNode.Parse(File.ReadAllText(trace + ".status.json"))!;
                    check(status["type"]!.GetValue<string>() == "status" && status["state"]!.GetValue<string>() == "live"
                        && status["capture_devices"]![0]!["ipv4_addrs"]![0]!.GetValue<string>() == "192.0.2.1"
                        && status["active_flow"]!["server"]!.GetValue<string>() == "203.0.113.1:30000",
                        "The uploader-recognized sidecar keeps the existing status field names and active flow");
                    if (format == "jsonl")
                    {
                        var sessionBefore = service.Status!.Flow.SessionId;
                        var generation = snapshots.Last().SourceGeneration;
                        var rotation = service.RotateRecordingAsync(); Wait(rotation);
                        var paths = rotation.Result;
                        check(paths.TracePath != trace && paths.SessionPath != ndjson
                            && service.ActiveTracePath == paths.TracePath && service.IsWriting(paths.TracePath) && service.IsWriting(paths.SessionPath)
                            && !service.IsWriting(trace) && !service.IsWriting(ndjson) && service.Status!.Flow.SessionId == sessionBefore,
                            "A queued manual rotation switches both active files at the capture owner without replacing the flow session");
                        var firstSession = JsonNode.Parse(ReadActive(ndjson).Split('\n')[0])!;
                        var nextSession = JsonNode.Parse(ReadActive(paths.SessionPath).Split('\n')[0])!;
                        check(firstSession["type"]!.GetValue<string>() == "session_volume" && nextSession["volume"]!.GetValue<int>() == 2
                            && firstSession["recording_id"]!.GetValue<string>() == nextSession["recording_id"]!.GetValue<string>()
                            && nextSession["previous_volume"]!["file"]!.GetValue<string>() == Path.GetFileName(ndjson)
                            && nextSession["event_offset"]!.GetValue<int>() == events.Length - 1,
                            "Paired session volumes retain immutable identity, predecessor and the exact business-event offset");
                        var secondMessage = JsonNode.Parse(JsonFormatter.Default.Format(damage))!;
                        secondMessage["clientData"]!["opList"]![0]!["seqId"] = 2;
                        secondMessage["clientData"]!["opList"]![0]!["clientTickTms"] = "1400";
                        var second = clientCipher.Process([8, 1, ..JsonParser.Default.Parse(secondMessage.ToJsonString(), ProtocolCatalog.Messages["CS_BATTLE_OP"]).ToByteArray()]);
                        backend.Receive(new(1400, Flow.Client, Flow.Server, 3 + clientWire.Length, Frame(second[..2], second[2..]), "synthetic"));
                        Wait(secondHit.Task);
                        check(snapshots.Last(frame => frame.Snapshot is not null).SourceGeneration == generation
                            && snapshots.Last().Snapshot?.Get("participants") is EvidenceArray { Items.Count: > 0 },
                            "The next real encrypted hit continues the same analysis generation, previous damage and actor context after rotation");
                        var chain = TraceVolumes.Resolve(paths.TracePath);
                        var continuous = TraceVolumes.ReadEvents(chain).ToArray();
                        check(chain.IsComplete && chain.Volumes.Count == 2 && continuous.Count(item => item.Type == "damage") == 2
                            && chain.Volumes[1].Header.PreviousVolume?.FileName == Path.GetFileName(trace)
                            && JsonNode.Parse(File.ReadAllText(paths.TracePath + ".status.json"))!["log"]!["path"]!.GetValue<string>() == paths.SessionPath,
                            "Both trace volumes remain continuously sequenced and the new status sidecar points to the paired session");
                        HistoryIndex history = new(Path.Combine(logs, "index"));
                        var row = history.Records(paths.SessionPath).Single();
                        var report = new HistoryAnalyzer(new(resources)).Analyze(row);
                        check(row.SessionSource?.Volumes.Count == 2 && row.FilePath == ndjson && row.TotalDamage == 247
                            && report.Get("battle") is EvidenceObject reportBattle && TraceData.Int(reportBattle.Get("total_damage")) == 248,
                            "The normal history index and direct-event report combine both raw session volumes without losing pre-split actors or rounded damage");
                        var exported = Path.Combine(logs, "continuous-export.log");
                        TraceExportService.Export(paths.SessionPath, exported);
                        var integrity = TraceExportService.LoadIntegrity(exported);
                        check(integrity.Verified && integrity.RawContent == string.Concat(continuous.SelectMany(item => TraceLegacyExporter.Lines(item, chain.Volumes[0].Header.TimeZoneOffsetMinutes))),
                            "Exporting a linked raw history record resolves its trace volumes and proves the exact canonical legacy body");
                        foreach (var (source, at) in new[] { (trace, 1205L), (paths.TracePath, 1305L) })
                        {
                            var wall = at * 1_000_000;
                            using InputLogWriter input = new(InputLogWriter.Companion(source), source, clock: () => new(wall, wall));
                            input.Put("input", TraceData.Make(("kind", "key"), ("code", "K:49"), ("device", "keyboard"), ("phase", "down")));
                            wall += 5_000_000;
                            input.Put("input", TraceData.Make(("kind", "key"), ("code", "K:49"), ("device", "keyboard"), ("phase", "up")));
                        }
                        var inputs = InputEvidenceLoader.Discover(paths.SessionPath);
                        var evidence = new InputEvidenceLoader().Load(new(inputs, row.FilePath, (EvidenceObject)report.Get("battle"), TraceData.Make()));
                        check(inputs.Count == 2 && evidence.Get("actions") is EvidenceArray { Items.Count: 2 }
                            && evidence.Get("warnings") is EvidenceArray messages && messages.Items.OfType<EvidenceText>().Any(message => message.Value == "已校验 trace 关联"),
                            "A raw session battle automatically discovers input from both paired trace volumes and verifies each sidecar against its own source");
                        SettingsContext context = new(logs);
                        SettingsStore settings = new(new() { Service = ServiceSettings.Default(context) }, new(context));
                        using (InputEvidenceController bound = new((EvidenceObject)report.Get("battle"), settings))
                        {
                            Wait(bound.SetRecordAsync(row)); bound.Drain();
                            Wait(bound.SetAlignmentAsync(5, null, new Dictionary<int, string>())); bound.Drain();
                        }
                        using (InputEvidenceController restored = new((EvidenceObject)report.Get("battle"), settings))
                        {
                            Wait(restored.SetRecordAsync(row)); restored.Drain();
                            check(restored.State.Paths.Count == 2 && restored.State.OffsetMs == 5
                                && restored.State.Evidence.Get("actions") is EvidenceArray { Items.Count: 2 },
                                "Saving and reopening manual alignment retains every input volume rather than reducing a continuous battle to its first sidecar");
                        }
                        var renamed = HistoryFiles.Rename(ndjson, "连续录制");
                        var refreshed = history.Records(paths.SessionPath).Single();
                        check(!HistoryCatalog.SourcesUnchanged(row) && refreshed.FilePath == renamed
                            && refreshed.SourceEndLine == row.SourceEndLine && refreshed.SessionSource?.Volumes.Count == 2,
                            "Renaming a closed earlier volume invalidates old history metadata and finds the same continuous recording by identity");
                        var away = Path.Combine(logs, "missing-first.ndjson"); File.Move(renamed, away);
                        try
                        {
                            var incomplete = SessionVolumes.Resolve(paths.SessionPath);
                            var refused = false;
                            try { history.Records(paths.SessionPath); } catch (InvalidDataException) { refused = true; }
                            check(!incomplete.IsComplete && incomplete.Issues.Any(message => message.Contains("不完整", StringComparison.Ordinal)) && refused,
                                "A missing earlier session volume is explicitly incomplete and never analyzed as a complete battle");
                        }
                        finally { File.Move(away, renamed); }
                    }
                }
                finally { stop.Cancel(); Wait(run); }
                var archive = Directory.GetFiles(logs, "trace_*" + extension, SearchOption.AllDirectories).Order(StringComparer.Ordinal).First();
                check(Directory.GetFiles(logs, "session_*.ndjson", SearchOption.AllDirectories).All(path => !service.IsWriting(path)),
                    "Completed session NDJSON stops reporting an active writer after shutdown");
                check(backend.DeviceCloses == 1 && backend.BackendCloses == 1 && !service.IsWriting(archive) && service.ActiveTracePath is null && service.Status?.Running == false,
                    "Shutdown releases native dependencies, the selected devices and the active archive exactly once");
                check(snapshots.Last().Snapshot is null && snapshots.Last().SourceGeneration > snapshots.First().SourceGeneration,
                    "Stopped capture delivers an explicit cleared generation after the last live result");
                File.Move(archive, archive + ".moved");
                check(!Directory.GetFiles(logs, "*.tmp", SearchOption.AllDirectories).Any() && diagnostics.All(message => message == "capture closed"),
                    "Normal lifecycle leaves no temporary sidecars or diagnostics and permits immediate file operations");
            }

            var failedLogs = Path.Combine(folder.FullName, "observer-failure"); Backend rejected = new();
            GameCaptureService failed = new(new(resources), new("SyntheticGame.exe", "unused", "unused", failedLogs, WebSocketPort: null), () => rejected);
            try { Wait(failed.RunAsync((_, _) => throw new InvalidOperationException("Observer rejected frame"))); throw new IOException("Observer failure was hidden"); }
            catch (InvalidOperationException error)
            {
                check(error.Message == "Observer rejected frame" && rejected.DeviceCloses == 1 && rejected.BackendCloses == 1
                    && failed.Status is { Running: false, ErrorTask: "observer", ErrorType: "InvalidOperationException" },
                    "An observer failure stops and releases the whole service while preserving the actual fault and owning task");
            }
            var failureStatus = JsonNode.Parse(File.ReadAllText(Directory.GetFiles(failedLogs, "*.status.json", SearchOption.AllDirectories).Single()))!;
            check(failureStatus["fatal_error"]!["message"]!.GetValue<string>() == "Observer rejected frame",
                "A managed trace retains its fatal background failure in the uploader-compatible sidecar");

            using TcpListener occupied = new(IPAddress.Loopback, 0); occupied.Start(); Backend bindBackend = new();
            GameCaptureService bindFailure = new(new(resources), new("SyntheticGame.exe", "unused", "unused",
                WebSocketPort: ((IPEndPoint)occupied.LocalEndpoint).Port), () => bindBackend);
            try { Wait(bindFailure.RunAsync()); throw new IOException("WebSocket bind failure was hidden"); }
            catch (SocketException)
            {
                check(bindBackend.DeviceCloses == 1 && bindBackend.BackendCloses == 1 && bindFailure.Status is { Running: false, ErrorTask: "websocket" },
                    "A real occupied loopback port fails the composition and releases native capture instead of leaving it running");
            }
        }
        finally { folder.Delete(recursive: true); }
    }
}
