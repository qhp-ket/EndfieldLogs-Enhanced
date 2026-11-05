using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

public static class TimerWire
{
    public static EvidenceObject OfficialData(EvidenceObject source, string phase, string gameId, string origin)
    {
        Dictionary<string, EvidenceValue> data = new() { ["phase"] = new EvidenceText(phase), ["source"] = new EvidenceText(origin) };
        if (gameId.Length > 0) data["game_id"] = new EvidenceText(gameId);
        foreach (var (input, output) in new[] { ("challenge_start_ts", "challenge_start_ts"), ("challenge_expire_ts", "challenge_expire_ts"),
            ("prepare_challenge_seconds", "prepare_seconds"), ("is_pass", "is_pass"), ("pass_time", "pass_time"), ("force_leave_ts", "force_leave_ts") })
            if (source.Fields.TryGetValue(input, out var value)) data[output] = value;
        return new(data);
    }

    public static (string Marker, IReadOnlyDictionary<string, string> Fields) Observation(TraceEvent item)
    {
        if (item.Type is not ("battle_timer" or "official_timer" or "battle_phase" or "battle_timer_missing")) throw new InvalidDataException("Expected timer event");
        var phase = (item.Data.Get("phase") as EvidenceText)?.Value;
        var missing = item.Type == "battle_timer_missing" || item.Type == "official_timer" && phase == "missing";
        var required = missing ? "boundary" : "source";
        if (item.Data.Get(required) is not EvidenceText { Value.Length: > 0 }) throw new InvalidDataException("Timer " + required + " is required");
        if (item.Type == "battle_timer" && phase is not ("start" or "end" or "reset")
            || item.Type == "official_timer" && phase is not ("start" or "end" or "await" or "missing")) throw new InvalidDataException("Invalid timer phase");
        Dictionary<string, string> fields = [];
        foreach (var (input, output) in new[] {
            ("source","source"), ("operation_seq","seq"), ("scene_num_id","scene"), ("game_id","gameId"),
            ("start_ms","startMs"), ("end_ms","endMs"), ("elapsed_ms","elapsedMs"), ("expire_ms","expireMs"),
            ("packet_elapsed_ms","packetElapsedMs"), ("wall_elapsed_ms","wallElapsedMs"), ("official","official"),
            ("sane","sane"), ("fallback","fallback"), ("is_pass","isPass"), ("pass_time","passTime"),
            ("challenge_start_ts","challengeStartTs"), ("challenge_expire_ts","challengeExpireTs"),
            ("prepare_seconds","prepareSeconds"), ("force_leave_ts","forceLeaveTs"), ("bp_score","bpScore"), ("danger_meter","dangerMeter"),
            ("boundary","boundary"), ("packet_battle_active","packetBattleActive"), ("official_expected","officialExpected"), ("official_start_seen","officialStartSeen") })
            if (item.Data.Fields.TryGetValue(input, out var value) && value is not EvidenceNull)
                fields[output] = input is "is_pass" or "packet_battle_active" or "official_expected" or "official_start_seen" ? Catalog.CatalogValues.Truth(value) ? "1" : "0"
                    : item.Type == "battle_timer" && value is EvidenceBoolean flag ? flag.Value ? "1" : "0" : PythonDisplay.String(value);
        var marker = item.Type switch
        {
            "battle_phase" => "BATTLE_PHASE_START", "battle_timer_missing" => "BATTLE_TIMER_MISSING",
            _ => (item.Type == "battle_timer" ? "GAME_TIMER_" : "OFFICIAL_TIMER_") + phase!.ToUpperInvariant(),
        };
        return (marker, fields);
    }
}
