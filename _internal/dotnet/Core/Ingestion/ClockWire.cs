using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public sealed record ClockObservation(string Kind, string Source, long CapturedAtMs, BigInteger? TickMs,
    BigInteger? ClientTs, BigInteger? ServerTs, BigInteger? LogicalTs, bool? Frozen);

public static class ClockWire
{
    public static (string Type, EvidenceObject Data)? Data(EvidenceObject source, string eventType)
    {
        string kind, origin;
        if (eventType == "GAME_CLOCK_TICK")
        {
            if (source.Get("source") is not EvidenceText { Value: "CS_BATTLE_OP" } || SkillWire.Integer(source.Get("tick_ms")) is not { } tick || tick <= 0) return null;
            kind = "clock_tick"; origin = "CS_BATTLE_OP";
        }
        else
        {
            kind = eventType is "CS_PING" or "SC_PING" ? "clock_sync"
                : eventType is "CS_GAME_TIME_FREEZE_START_REQ" or "CS_GAME_TIME_FREEZE_END_REQ" ? "time_freeze_request" : "time_freeze_state";
            origin = eventType;
        }
        (string Input, string Output)[] fields = kind switch
        {
            "clock_tick" => [("tick_ms", "tick_ms"), ("seq_id", "operation_seq")],
            "clock_sync" => [("msg_id", "message_id"), ("client_ts", "client_ts"), ("server_ts", "server_ts"), ("logical_ts", "logical_ts"), ("raw_body_hex", "raw_body_hex")],
            "time_freeze_request" => [("msg_id", "message_id"), ("reason", "reason"), ("raw_body_hex", "raw_body_hex")],
            _ => [("msg_id", "message_id"), ("reason", "reason"), ("raw_body_hex", "raw_body_hex"), ("in_time_freeze", "in_time_freeze")],
        };
        Dictionary<string, EvidenceValue> result = new() { ["source"] = new EvidenceText(origin) };
        foreach (var (input, output) in fields) if (source.Fields.TryGetValue(input, out var value)) result[output] = value;
        return (kind, new(result));
    }

    public static ClockObservation Observation(TraceEvent item)
    {
        if (item.Type is not ("clock_tick" or "clock_sync" or "time_freeze_request" or "time_freeze_state")) throw new InvalidDataException("Expected clock event");
        if (item.Data.Get("source") is not EvidenceText { Value.Length: > 0 } source) throw new InvalidDataException("Clock event requires its observed source");
        BigInteger? Nonnegative(string key) => SkillWire.Integer(item.Data.Get(key)) is { } value && value >= 0 ? value : null;
        return new(item.Type, source.Value, item.CapturedAtMs, SkillWire.Integer(item.Data.Get("tick_ms")),
            Nonnegative("client_ts"), Nonnegative("server_ts"), Nonnegative("logical_ts"),
            item.Data.Get("in_time_freeze") is EvidenceBoolean flag ? flag.Value : null);
    }
}
