using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Runtime.Versioning;
using EndfieldLogs.Capture;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Capture.Workers;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;
using EndfieldLogs.Native.Processes;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Capture;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Sessions;
using EndfieldLogs.Runtime.Tracing;
using Google.Protobuf;

internal static class CaptureRuntimeSpecs
{
    private sealed class FakeDevices : ICaptureDevices
    {
        public int Starts, Closes;
        public readonly TaskCompletionSource Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public void Start() { Interlocked.Increment(ref Starts); Started.TrySetResult(); }
        public void Dispose() => Interlocked.Increment(ref Closes);
        public CaptureStatistics Statistics() => new(1, 0, 0);
        public IReadOnlyList<DeviceInfo> Devices => [];
    }
    private sealed class BrokenSource : ICaptureSource
    {
        public int Closes;
        public NativePacket? Read() => throw new IOException("native read failed");
        public PcapStatistics? Statistics() => null;
        public void Dispose() => Interlocked.Increment(ref Closes);
    }
    private static readonly FlowKey First = new(new("192.0.2.1", 30001), new("203.0.113.1", 30000));
    private static byte[] Frame(byte[] head, byte[] body) => [(byte)head.Length, (byte)body.Length, (byte)(body.Length >> 8), ..head, ..body];
    private static void Wait(Task task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();

    public static void Run(Action<bool, string> check)
    {
        byte[] table = new byte[28];
        BinaryPrimitives.WriteUInt32LittleEndian(table, 1);
        IPAddress.Parse(First.Client.Ip).GetAddressBytes().CopyTo(table, 8);
        IPAddress.Parse(First.Server.Ip).GetAddressBytes().CopyTo(table, 16);
        BinaryPrimitives.WriteUInt16BigEndian(table.AsSpan(12), (ushort)First.Client.Port);
        BinaryPrimitives.WriteUInt16BigEndian(table.AsSpan(20), (ushort)First.Server.Port);
        BinaryPrimitives.WriteUInt32LittleEndian(table.AsSpan(24), 1234);
        var native = TcpProcessConnections.Parse(table).Single();
        check(native is { ProcessId: 1234, LocalAddress: "192.0.2.1", LocalPort: 30001, RemoteAddress: "203.0.113.1", RemotePort: 30000 },
            "Native owner-PID rows retain network byte order for IPv4 addresses and ports");
        if (OperatingSystem.IsWindows())
        {
            var actual = TcpProcessConnections.Read();
            check(actual.All(row => row.LocalPort is >= 0 and <= 65535 && row.RemotePort is >= 0 and <= 65535),
                "The actual Windows IP Helper table can be enumerated without a game or admin capture");
            check(new GameProcessMonitor("Endfield-Synthetic-Nonexistent.exe").Read() == new GameProcessObservation(false, null),
                "An absent game process has no fabricated connection");
            using TcpListener listener = new(IPAddress.Loopback, 0); listener.Start();
            using TcpClient client = new(AddressFamily.InterNetwork);
            client.Connect((IPEndPoint)listener.LocalEndpoint);
            using var accepted = listener.AcceptTcpClient();
            var local = (IPEndPoint)client.Client.LocalEndPoint!;
            var remote = (IPEndPoint)client.Client.RemoteEndPoint!;
            check(TcpProcessConnections.Read().Any(row => row.ProcessId == (uint)Environment.ProcessId
                && row.LocalAddress == local.Address.ToString() && row.LocalPort == local.Port
                && row.RemoteAddress == remote.Address.ToString() && row.RemotePort == remote.Port),
                "The real Windows owner table identifies an established loopback socket and its owning process");
        }

        using var live = new LiveBattleSession(() => (_, _, _, _) => null);
        List<string> lines = [];
        using var recording = new TraceRecording(line => { lines.Add(line); live.FeedLine(line); }, timeZone: TimeZoneInfo.Utc);
        MessageRegistry registry = new("[{\"msg_id\":1,\"class_name\":\"CS_BATTLE_OP\"}]", "[]");
        var key = Enumerable.Range(0, 32).Select(index => (byte)index).ToArray(); byte[] nonce = new byte[12];
        var resets = 0;
        CaptureFlowSession flow = new((selected, output) => new(selected, Guid.NewGuid().ToString(), registry, bytes => bytes, _ => key, output, new RuntimeMetrics()),
            recording, () => { resets++; live.Reset(); }, clock: () => 0);
        flow.Initialize(new(true, First));
        flow.Process(new(1000, First.Client, First.Server, 0, Frame([], []), "synthetic"));
        flow.Observe(new(true, First));
        check(flow.Snapshot is { State: ServiceState.WaitingRestart, SessionId: null } && lines.Count == 0,
            "Starting while the game runs waits for a genuine process restart and ignores partial encrypted streams");
        flow.Observe(new(false, null)); flow.Observe(new(true, null));
        check(flow.State == ServiceState.WaitingConnection, "After the observed exit, a new process can wait for its connection");

        var message = JsonParser.Default.Parse("""
            {"client_data":{"op_list":[{"op_type":"BattleOpSetBuffEnableState","owner_id":"11","seq_id":1,
              "set_buff_enable_state_op_data":{"buff_inst_id_to_enable_state":{"888":false}}}]}}
            """, ProtocolCatalog.Messages["CS_BATTLE_OP"]);
        byte[] head = [8, 1];
        var encrypted = new Xxe1(key, nonce, 1).Process([..head, ..message.ToByteArray()]);
        var wire = Frame(encrypted[..head.Length], encrypted[head.Length..]);
        var login = Frame([], [0x1a, 1, 0, 0x22, 12, ..nonce]);
        // Buffered packets arrive interleaved; replay orders both TCP directions and lets the real cipher retain its stream position.
        flow.Process(new(1003, First.Server, First.Client, 5, login[5..], "synthetic"));
        flow.Process(new(1002, First.Client, First.Server, 3, wire, "synthetic"));
        flow.Process(new(1000, First.Client, First.Server, 0, Frame([], []), "synthetic"));
        flow.Process(new(1001, First.Server, First.Client, 0, login[..5], "synthetic"));
        flow.Observe(new(true, First));
        check(flow.Snapshot is { State: ServiceState.Live, Live: true, ActivationReason: "buffered_bidirectional_payload" }
            && lines.Any(line => line.Contains("BUFF_ENABLE", StringComparison.Ordinal)),
            "Buffered bidirectional split login reaches canonical business output through the actual framing, cipher and registry");
        var count = lines.Count;
        flow.Process(new(1004, First.Client, First.Server, 3, wire, "synthetic"));
        check(lines.Count == count, "Discovery copies and retransmissions do not duplicate active-flow events");
        flow.Observe(new(true, new(new("192.0.2.1", 30002), First.Server)));
        check(flow.Snapshot is { State: ServiceState.WaitingHandshake, ActivationReason: "process_connection_fallback" } && resets == 1,
            "A changed process connection resets the previous analysis and starts a distinct session");
        flow.Observe(new(false, null));
        check(flow.Snapshot is { State: ServiceState.WaitingGame, Flow: null, SessionId: null } && resets == 2,
            "Game exit clears the active flow, decoded state and live analysis");

        // Test the actual async owner, cancellation and fault propagation with deterministic barriers.
        var folder = Directory.CreateTempSubdirectory("endfield-runtime-spec-");
        try
        {
            using var session = new LiveBattleSession(() => (_, _, _, _) => null);
            using var disk = new TraceRecording(session, folder.FullName);
            CaptureFlowSession state = new((selected, output) => new(selected, "runtime", registry, bytes => bytes, _ => key, output, new()), disk, session.Reset);
            FakeDevices devices = new(); using CancellationTokenSource cancel = new();
            var snapshots = new System.Collections.Concurrent.ConcurrentQueue<CaptureRuntimeSnapshot>();
            CaptureRuntime runtime = new(state, disk, () => new(false, null), (_, diagnostic) =>
            {
                diagnostic("one optional adapter failed", new IOException("optional adapter")); return devices;
            }, snapshots.Enqueue, monitorInterval: TimeSpan.FromMilliseconds(5), statisticsInterval: TimeSpan.FromMilliseconds(5));
            var run = runtime.RunAsync(cancel.Token); Wait(devices.Started.Task); cancel.Cancel(); Wait(run);
            check(devices.Starts == 1 && devices.Closes == 1 && !runtime.Snapshot.Running && runtime.Snapshot.Error is null,
                "Normal cancellation releases capture exactly once and a nonfatal adapter diagnostic does not abort other devices");
            check(!disk.IsWriting(disk.FilePath!) && snapshots.Last().Running == false, "Async shutdown closes the recording before publishing stopped status");

            using var session2 = new LiveBattleSession(() => (_, _, _, _) => null);
            using var disk2 = new TraceRecording(session2, folder.FullName);
            CaptureFlowSession state2 = new((selected, output) => new(selected, "failure", registry, bytes => bytes, _ => key, output, new()), disk2, session2.Reset);
            BrokenSource source = new();
            CaptureRuntime failed = new(state2, disk2, () => new(false, null), (packet, diagnostic) =>
                new CaptureManager([new("synthetic", "Synthetic", ["192.0.2.1"], 0)], (_, _) => source, packet, diagnostic),
                statisticsInterval: TimeSpan.FromMilliseconds(5));
            try { Wait(failed.RunAsync()); throw new InvalidOperationException("Native worker fault was hidden"); }
            catch (IOException error)
            {
                check(error.InnerException?.Message == "native read failed" && source.Closes == 1
                    && !failed.Snapshot.Running && failed.Snapshot.Error is not null,
                    "A real CaptureWorker native failure reaches the service task and closes its file and source");
            }
        }
        finally { folder.Delete(recursive: true); }
    }
}
