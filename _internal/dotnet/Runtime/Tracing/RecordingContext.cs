using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Observed mappings and live BUFF instances, without retained damage history.</summary>
internal sealed class RecordingContext
{
    private readonly Dictionary<string, (long Serial, BattleLogEvent Event)> rows = new(StringComparer.Ordinal);
    private long serial;
    public void Clear() => rows.Clear();
    private void Put(string key, BattleLogEvent value) => rows[key] = (++serial, value);
    private static string Id(EvidenceObject value, string key) => TraceData.Present(value.Get(key), "");
    private void RemoveBuff(string uid)
    { foreach (var key in rows.Keys.Where(key => key.StartsWith("buff/" + uid + "/", StringComparison.Ordinal)).ToArray()) rows.Remove(key); }
    private static BattleLogEvent With(BattleLogEvent value, string key, EvidenceValue data)
    {
        var payload = new Dictionary<string, object?>(value.Payload) { [key] = data };
        return value with { Payload = payload };
    }
    public void Observe(BattleLogEvent value)
    {
        var type = value.EventType;
        if (type is not ("SC_SELF_SCENE_INFO" or "LOADOUT" or "DUNGEON_CONTEXT" or "CONTRACT_TAGS" or "SC_SELF_SCENE_INFO_SKILLS"
            or "SC_OBJECT_ENTER_VIEW" or "SC_SYNC_ATTR" or "BattleOpSkillAttach" or "BattleOpSkillDetach" or "BattleOpAddBuff"
            or "BattleOpFinishBuff" or "BattleOpSetBuffEnableState" or "BattleOpTriggerAction")) return;
        if (type == "BattleOpTriggerAction" && value.Payload.GetValueOrDefault("action") is IReadOnlyDictionary<string, object?> actionPayload
            && !actionPayload.ContainsKey("create_buff_action") && !actionPayload.ContainsKey("remove_buff_action")) return;
        var row = TraceData.Obj(TraceData.Value(value.Payload));
        if (type is "SC_SELF_SCENE_INFO" or "LOADOUT" or "DUNGEON_CONTEXT" or "CONTRACT_TAGS") Put(type, value);
        else if (type == "SC_SELF_SCENE_INFO_SKILLS") Put(type + "/" + Id(row, "owner_inst_id") + "/" + Id(row, "owner_templateid"), value);
        else if (type == "SC_OBJECT_ENTER_VIEW")
            foreach (var item in TraceData.Rows(row.Get("objects")))
                Put(type + "/" + Id(item, "battle_inst_id") + "/" + Id(item, "id"), With(value, "objects", new EvidenceArray([item])));
        else if (type == "SC_SYNC_ATTR")
            foreach (var item in TraceData.Rows(row.Get("attrs")))
                Put(type + "/" + Id(row, "battle_inst_id") + "/" + Id(row, "obj_id") + "/" + Id(item, "attr_type"), With(value, "attrs", new EvidenceArray([item])));
        else if (type == "BattleOpSkillAttach") Put(type + "/" + Id(row, "skill_inst_id"), value);
        else if (type == "BattleOpSkillDetach") rows.Remove("BattleOpSkillAttach/" + Id(row, "skill_inst_id"));
        else if (type == "BattleOpAddBuff") Put("buff/" + Id(row, "buff_inst_id") + "/add", value);
        else if (type == "BattleOpFinishBuff") RemoveBuff(Id(row, "buff_inst_id"));
        else if (type == "BattleOpSetBuffEnableState") Put("buff/" + Id(row, "buff_inst_id") + "/enable", value);
        else if (type == "BattleOpTriggerAction")
        {
            var action = TraceData.Obj(row.Get("action"));
            foreach (var field in new[] { "create_buff_action", "remove_buff_action" })
                foreach (var item in TraceData.Rows(TraceData.Obj(action.Get(field)).Get("details")))
                {
                    var uid = Id(item, "buff_inst_id");
                    if (field == "remove_buff_action") RemoveBuff(uid);
                    else
                    {
                        var parts = new Dictionary<string, EvidenceValue> { [field] = TraceData.Make(("details", new EvidenceArray([item]))) };
                        Put("buff/" + uid + "/create", With(value, "action", new EvidenceObject(parts)));
                    }
                }
        }
    }
    public IReadOnlyList<BattleLogEvent> Snapshot() => rows.Values.OrderBy(pair => pair.Serial).Select(pair => pair.Event).ToArray();
}
