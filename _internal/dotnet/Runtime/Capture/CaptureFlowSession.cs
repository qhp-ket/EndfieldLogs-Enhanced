using EndfieldLogs.Core.Models;
using EndfieldLogs.Runtime.Sessions;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Capture;

public sealed record CaptureFlowSnapshot(ServiceState State, FlowKey? Flow, string? SessionId, bool Live,
    string? ActivationReason, IReadOnlyDictionary<string, object?>? Session);

/// <summary>Serial owner of discovery buffers and one decoded flow. It never reopens capture handles after login.</summary>
public sealed class CaptureFlowSession(
    Func<FlowKey, Action<BattleLogEvent>, GameSessionPipeline> createSession,
    TraceRecording recording, Action resetAnalysis, Action<BattleLogEvent>? onEvent = null,
    Func<long>? clock = null, Action? onSessionClosed = null)
{
    private readonly Dictionary<FlowKey, Queue<CapturedPacket>> pending = [];
    private GameSessionPipeline? session;
    private FlowKey? active;
    private string? activationReason;
    private ServiceState state = ServiceState.WaitingGame;
    public ServiceState State => state;
    public string? SessionId => session?.SessionId;
    public CaptureFlowSnapshot Snapshot => new(state, active, session?.SessionId, session?.IsLive == true,
        activationReason, session?.Status());

    public void Initialize(GameProcessObservation observation) => state = observation.Running ? ServiceState.WaitingRestart : ServiceState.WaitingGame;

    public void Observe(GameProcessObservation observation)
    {
        if (state == ServiceState.WaitingRestart)
        {
            if (!observation.Running) state = ServiceState.WaitingGame;
            return;
        }
        if (!observation.Running) { Reset(); state = ServiceState.WaitingGame; return; }
        if (observation.Flow is null) { if (active is not null) Reset(); state = ServiceState.WaitingConnection; return; }
        if (active != observation.Flow) Activate(observation.Flow);
        state = session?.IsLive == true ? ServiceState.Live : ServiceState.WaitingHandshake;
    }

    public void Process(CapturedPacket packet)
    {
        if (state == ServiceState.WaitingRestart) return;
        var flow = Normalize(packet);
        if (flow is null) return;
        if (!pending.TryGetValue(flow, out var packets)) pending[flow] = packets = new();
        if (packets.Count == 8192) packets.Dequeue();
        packets.Enqueue(packet);
        if (active == flow && session is not null)
        {
            session.ProcessPacket(packet);
            if (session.IsLive) state = ServiceState.Live;
        }
    }

    public static FlowKey? Normalize(CapturedPacket packet) => packet.Src.Port == 30000 ? new(packet.Dst, packet.Src)
        : packet.Dst.Port == 30000 ? new(packet.Src, packet.Dst) : null;

    private void Activate(FlowKey flow)
    {
        var replay = pending.GetValueOrDefault(flow)?.OrderBy(packet => packet.Src == flow.Client ? 0 : 1)
            .ThenBy(packet => packet.Seq).ThenBy(packet => packet.TimestampMs).ToArray() ?? [];
        if (active is not null || session is not null) Reset();
        active = flow;
        activationReason = replay.Any(packet => packet.Src == flow.Client) && replay.Any(packet => packet.Src == flow.Server)
            ? "buffered_bidirectional_payload" : "process_connection_fallback";
        session = createSession(flow, value => { recording.Handle(value); onEvent?.Invoke(value); });
        recording.BeginSession(replay.Length > 0 ? replay.Min(packet => packet.TimestampMs) : clock?.Invoke() ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        foreach (var packet in replay) session.ProcessPacket(packet);
    }

    public void Reset()
    {
        var previous = session;
        try
        {
            if (active is not null || previous is not null) recording.EndSession();
            previous?.FlushDebugState();
        }
        finally
        {
            var hadSession = active is not null || previous is not null;
            active = null; session = null; activationReason = null;
            if (hadSession)
            {
                try { onSessionClosed?.Invoke(); }
                finally { resetAnalysis(); }
            }
        }
    }
}
