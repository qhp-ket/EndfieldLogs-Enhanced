using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class ClockLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("clock_tick" or "clock_sync" or "time_freeze_request" or "time_freeze_state")) throw new InvalidDataException("Expected clock event");
        var data = ExportValues.Data(item);
        var source = S(data.Get("source"));
        var message = data.Fields.TryGetValue("message_id", out var msg) ? S(msg) : "unknown";
        var raw = data.Get("raw_body_hex") is EvidenceText text ? text.Value.Length == 0 ? "empty" : text.Value : "unknown";
        string body;
        if (item.Type == "clock_tick" && source is "GAME_TIMER_TICK" or "HEARTBEAT") body = HistoricalLegacyExporter.Body(item.Type, data);
        else if (item.Type == "clock_tick") body = $"GAME_CLOCK_TICK source={source} tickMs={I(Int(data.Get("tick_ms")))} seq={I(Int(data.Get("operation_seq")))}";
        else if (item.Type == "clock_sync")
        {
            List<string> parts = [$"GAME_CLOCK_SYNC source={source}", "msgId=" + message, "captureMs=" + item.CapturedAtMs.ToString(CultureInfo.InvariantCulture)];
            foreach (var (key, output) in new[] { ("client_ts", "clientTs"), ("server_ts", "serverTs"), ("logical_ts", "logicalTs") })
                if (Int(data.Get(key)) is { } value && value >= 0) parts.Add(output + "=" + I(value));
            if (data.Get("raw_body_hex") is EvidenceText) parts.Add("rawBodyHex=" + raw);
            body = string.Join(' ', parts);
        }
        else if (item.Type == "time_freeze_request") body = $"GAME_TIME_FREEZE_REQUEST source={source} reason={I(Int(data.Get("reason")))} msgId={message} rawBodyHex={raw}";
        else body = $"GAME_TIME_FREEZE_STATE source={source} inTimeFreeze={(data.Get("in_time_freeze") is EvidenceBoolean flag ? flag.Value ? "1" : "0" : "unknown")} reason={I(Int(data.Get("reason")))} msgId={message} rawBodyHex={raw}";
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + body + "\n"];
    }
}
