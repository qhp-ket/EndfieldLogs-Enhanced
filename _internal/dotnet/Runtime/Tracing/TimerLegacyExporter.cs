using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class TimerLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("battle_timer" or "official_timer" or "battle_phase" or "battle_timer_missing")) throw new InvalidDataException("Expected timer event");
        var data = ExportValues.Data(item);
        var phase = S(data.Get("phase"));
        (string Input, string Output)[] fields = (item.Type, phase) switch
        {
            ("battle_phase", _) => [("operation_seq","seq"), ("source","source"), ("game_id","gameId")],
            ("battle_timer_missing", _) or ("official_timer", "missing") => [("boundary","boundary"), ("packet_battle_active","packetBattleActive"),
                ("official_expected","officialExpected"), ("official_start_seen","officialStartSeen"), ("game_id","gameId")],
            ("battle_timer", "start") => [("operation_seq","seq"), ("source","source"), ("start_ms","startMs"), ("expire_ms","expireMs"), ("official","official")],
            ("battle_timer", "end") => [("operation_seq","seq"), ("source","source"), ("elapsed_ms","elapsedMs"), ("start_ms","startMs"), ("end_ms","endMs"),
                ("expire_ms","expireMs"), ("sane","sane"), ("official","official"), ("packet_elapsed_ms","packetElapsedMs"), ("wall_elapsed_ms","wallElapsedMs")],
            ("battle_timer", "reset") => [("source","source"), ("scene_num_id","scene")],
            ("official_timer", "start") => [("source","source"), ("game_id","gameId"), ("challenge_start_ts","challengeStartTs"), ("challenge_expire_ts","challengeExpireTs"), ("prepare_seconds","prepareSeconds")],
            ("official_timer", "end") => [("source","source"), ("game_id","gameId"), ("is_pass","isPass"), ("pass_time","passTime"), ("force_leave_ts","forceLeaveTs"), ("bp_score","bpScore"), ("danger_meter","dangerMeter")],
            ("official_timer", "await") => [("source","source"), ("game_id","gameId"), ("official_start_seen","officialStartSeen")],
            _ => throw new InvalidDataException("Invalid timer phase"),
        };
        List<string> parts = [item.Type switch {
            "battle_phase" => "BATTLE_PHASE_START", "battle_timer_missing" => "BATTLE_TIMER_MISSING",
            _ => (item.Type == "battle_timer" ? "GAME_TIMER_" : "OFFICIAL_TIMER_") + phase.ToUpperInvariant() }];
        foreach (var (key, output) in fields)
            if (data.Fields.TryGetValue(key, out var value) && value is not EvidenceNull)
                parts.Add(output + "=" + (key is "is_pass" or "packet_battle_active" or "official_expected" or "official_start_seen" ? Truth(value) ? "1" : "0" : item.Type == "battle_timer" && value is EvidenceBoolean flag ? flag.Value ? "1" : "0" : S(value)));
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + string.Join(' ', parts) + "\n"];
    }
}
