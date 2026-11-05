using System.Text.Json.Serialization;

namespace EndfieldLogs.Core.Models;

public sealed record Endpoint(string Ip, int Port);
public sealed record FlowKey(Endpoint Client, Endpoint Server);
public sealed record CapturedPacket(long TimestampMs, Endpoint Src, Endpoint Dst, long Seq,
    byte[] Payload, string DeviceName);
public sealed record EntityInfo(ulong BattleInstId, ulong? ObjId, string? TemplateId, int? EntityType);
public sealed record ActorRefPayload(ulong? BattleInstId, string? DisplayName);
public sealed record DamageDetailPayload(ulong? TargetBattleInstId, bool IsCrit, double Value,
    double AbsValue, double? CurHp);

public sealed record DamageEvent(string SessionId, long TimestampMs, long? SeqId, long? ClientTickTms,
    int? SkillTemplateId, ActorRefPayload Attacker, ActorRefPayload Target,
    IReadOnlyList<DamageDetailPayload> Details)
{
    public string Type => "damage";
}

public sealed record BattleLogEvent(string SessionId, long TimestampMs, string EventType,
    IReadOnlyDictionary<string, object?> Payload)
{
    // Payload order and key precedence follow the existing external event contract.
    public Dictionary<string, object?> ToPayload()
    {
        var result = new Dictionary<string, object?>
        {
            ["type"] = EventType,
            ["session_id"] = SessionId,
            ["timestamp_ms"] = TimestampMs,
        };
        foreach (var entry in Payload) result[entry.Key] = entry.Value;
        return result;
    }
}

[JsonConverter(typeof(JsonStringEnumConverter<ServiceState>))]
public enum ServiceState
{
    [JsonStringEnumMemberName("waiting_restart")] WaitingRestart,
    [JsonStringEnumMemberName("waiting_game")] WaitingGame,
    [JsonStringEnumMemberName("waiting_connection")] WaitingConnection,
    [JsonStringEnumMemberName("waiting_handshake")] WaitingHandshake,
    [JsonStringEnumMemberName("live")] Live,
}
