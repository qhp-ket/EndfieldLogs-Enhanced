using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Catalog;

namespace EndfieldLogs.Runtime.Sessions;

/// <summary>One ordered encrypted TCP session, decoded business events and diagnostic ownership.</summary>
public sealed class GameSessionPipeline
{
    private readonly SessionTransport transport;
    private readonly Dictionary<string, long> unhandledClasses = new(StringComparer.Ordinal);
    public GameSessionBusiness Business { get; }
    public string SessionId { get; }
    public FlowKey Flow { get; }
    public bool IsLive => transport.IsLive;
    public IReadOnlyDictionary<string, long> UnhandledClasses => new Dictionary<string, long>(unhandledClasses, StringComparer.Ordinal);

    public GameSessionPipeline(FlowKey flow, string sessionId, MessageRegistry registry,
        Func<byte[], byte[]> decryptLogin, Func<byte[], byte[]> decryptKey, Action<BattleLogEvent> onEvent,
        RuntimeMetrics metrics, Action<DecodedMessage, long>? onDebugMessage = null,
        Action<Dictionary<string, object?>>? onDebugRecord = null, Action<string, long, bool>? loadoutContext = null,
        bool rotationClockTrace = true, IReadOnlyDictionary<string, string>? names = null,
        IReadOnlyDictionary<string, string>? multiPhaseDungeons = null, bool mergeMultiPhaseEnemyBattles = false,
        LoadoutDisplayCatalog? loadoutCatalog = null)
    {
        Flow = flow; SessionId = sessionId;
        void Emit(BattleLogEvent value) { metrics.OutboundEventsEmitted++; onEvent(value); }
        Business = new(sessionId, Emit, loadoutContext, rotationClockTrace, names, multiPhaseDungeons, loadoutCatalog)
            { MergeMultiPhaseEnemyBattles = mergeMultiPhaseEnemyBattles };
        transport = new(flow, sessionId, registry, decryptLogin, decryptKey, (decoded, timestamp) =>
        {
            onDebugMessage?.Invoke(decoded, timestamp);
            if (!Business.Process(decoded, timestamp))
                unhandledClasses[decoded.ClassName] = unhandledClasses.GetValueOrDefault(decoded.ClassName) + 1;
        }, Emit, metrics, onDebugRecord);
    }

    public void ProcessPacket(CapturedPacket packet) => transport.Process(packet);
    public Dictionary<string, object?> Status() => transport.Status();
    public void FlushDebugState() => transport.FlushDebugState();
}
