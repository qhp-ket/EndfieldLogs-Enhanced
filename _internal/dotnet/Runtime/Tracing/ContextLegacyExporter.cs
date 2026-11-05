using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class ContextLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("game_instance" or "game_mechanics" or "scene_battle" or "battle_reset" or "session_warning")
            || item.Data.Get("legacy_layout") is not EvidenceObject layout) throw new InvalidDataException("Expected context event with legacy layout");
        var data = Obj(TraceValueProjection.Restore(item.Data, layout));
        List<string> parts;
        if (item.Type is "game_instance" or "game_mechanics")
        {
            var source = S(data.Get("source"));
            parts = [ContextWire.Mechanics[source].Marker, "source=" + source];
            if (Truth(data.Get("game_id"))) parts.Add("gameId=" + S(data.Get("game_id")));
            foreach (var (key, output) in new[] { ("game_inst_id","gameInstId"), ("game_unique_id","gameUniqueId"), ("is_hunter_mode","isHunterMode"),
                ("interactive_obj_id","interactiveObjId"), ("npc_proxy_id","npcProxyId"), ("npc_obj_id","npcObjId") })
                if (data.Get(key) is not EvidenceNull && data.Get(key) is not EvidenceText { Value.Length: 0 })
                    parts.Add(output + "=" + (key == "is_hunter_mode" ? Truth(data.Get(key)) ? "1" : "0" : S(data.Get(key))));
            if (S(data.Get("action")) == "time_freeze" && data.Get("time_freeze_infos") is EvidenceArray freezes)
            {
                parts.Add("count=" + freezes.Items.Count);
                var rows = Rows(freezes).ToArray();
                if (rows.Length > 0)
                {
                    parts.Add("freezeInfos=[" + string.Join(',', rows.Select(row => I(Int(row.Get("time_key")) ?? 0) + ":" + I(Int(row.Get("total_freeze_time_in_ms")) ?? 0))) + "]");
                    parts.Add("totalFreezeMs=" + I(rows.Select(row => Int(row.Get("total_freeze_time_in_ms")) ?? 0).Append(BigInteger.Zero).Max()));
                }
            }
        }
        else if (item.Type == "scene_battle") parts = ["SCENE_BATTLE_STATE", "source=" + S(data.Get("source")), "inBattle=" + (Truth(data.Get("in_battle")) ? "1" : "0")];
        else if (item.Type == "battle_reset")
        {
            parts = ["BATTLE_RESET_STATUS"];
            foreach (var (key, output) in new[] { ("reason","reason"), ("event_inst_id","inst"), ("battle_inst_id","battleInst") })
                if (data.Get(key) is not EvidenceNull) parts.Add(output + "=" + S(data.Get(key)));
        }
        else
        {
            string TextOrUnknown(string key) => Truth(data.Get(key)) ? S(data.Get(key)) : "unknown";
            string Present(string key) => data.Get(key) is EvidenceNull ? "unknown" : S(data.Get(key));
            parts = ["SESSION_WARNING", "kind=" + TextOrUnknown("kind"), "direction=" + TextOrUnknown("direction"),
                "missingBytes=" + Present("missing_bytes"), "gapCount=" + Present("startup_tcp_gap_count")];
        }
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + string.Join(' ', parts) + "\n"];
    }
}
