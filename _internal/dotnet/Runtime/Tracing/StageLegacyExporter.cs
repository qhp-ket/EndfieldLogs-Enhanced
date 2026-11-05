using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public static class StageLegacyExporter
{
    public static IReadOnlyList<string> Lines(TraceEvent item, int timeZoneOffsetMinutes)
    {
        if (item.Type is not ("dungeon" or "contracts" or "battle_result")) throw new InvalidDataException("Expected stage event");
        if (item.Data.Get("legacy_layout") is not EvidenceObject layout) throw new InvalidDataException("Stage event lacks legacy export layout");
        var data = Obj(TraceValueProjection.Restore(item.Data, layout));
        List<string> parts;
        if (item.Type == "dungeon")
        {
            parts = ["DUNGEON_CONTEXT", "dungeonId=" + S(data.Get("dungeon_id")), "source=" + S(data.Get("source"))];
            foreach (var (key, output) in new[] { ("scene_num_id","scene"), ("scene_id","sceneId"), ("challenge_expire_ts","challengeExpireTs"),
                ("leave_dungeon_ts","leaveDungeonTs"), ("char_team_count","charTeamCount") })
                if (data.Get(key) is not EvidenceNull) parts.Add(output + "=" + S(data.Get(key)));
            foreach (var (key, output) in new[] { ("is_reward","isReward"), ("is_calc","isCalc"), ("is_pass","isPass") })
                if (data.Get(key) is not EvidenceNull) parts.Add(output + "=" + (Truth(data.Get(key)) ? "1" : "0"));
        }
        else if (item.Type == "battle_result") parts = ["BATTLE_RESULT", "source=" + S(data.Get("source")), "dungeonId=" + S(data.Get("dungeon_id")),
            "isCalc=" + (Truth(data.Get("is_calc")) ? "1" : "0"), "isPass=" + (Truth(data.Get("is_pass")) ? "1" : "0")];
        else
        {
            var raw = Truth(data.Get("tag_ids")) ? data.Get("tag_ids") : Truth(data.Get("alternate_tag_ids")) ? data.Get("alternate_tag_ids") : data.Get("display_tag_ids");
            var tags = Items(raw).Select(Int).Where(value => value is { IsZero: false });
            parts = ["CONTRACT_TAGS", "dungeonId=" + Text(data.Get("dungeon_id"), "unknown"), "source=" + S(data.Get("source")), "tagIds=[" + string.Join(',', tags.Select(value => I(value))) + "]"];
            if (Int(data.Get("score")) is { } score) parts.Add("score=" + I(score));
            if (Text(data.Get("direction")) is { Length: > 0 } direction) parts.Add("direction=" + direction);
            if (Int(Truth(data.Get("message_id")) ? data.Get("message_id") : data.Get("alternate_message_id")) is { } message) parts.Add("msgId=" + I(message));
        }
        var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(timeZoneOffsetMinutes)).ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
        return ["[" + stamp + "] " + string.Join(' ', parts) + "\n"];
    }
}
