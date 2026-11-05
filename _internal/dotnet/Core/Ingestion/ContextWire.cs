using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Context and diagnostics retain observations without manufacturing a completed timer.</summary>
public static class ContextWire
{
    public static readonly IReadOnlyDictionary<string, (string Type, string Action, string Marker)> Mechanics =
        new Dictionary<string, (string, string, string)>(StringComparer.Ordinal)
        {
            ["CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH"] = ("game_mechanics", "prepare_finish", "GAME_MECHANICS_PREPARE_FINISH"),
            ["CS_GAME_MECHANICS_REQ_START"] = ("game_mechanics", "request_start", "GAME_MECHANICS_REQ_START"),
            ["CS_GAME_MECHANICS_REQ_STOP"] = ("game_mechanics", "request_stop", "GAME_MECHANICS_REQ_STOP"),
            ["SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE"] = ("game_mechanics", "time_freeze", "GAME_MECHANICS_TIME_FREEZE"),
            ["SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD"] = ("game_mechanics", "completion_reward", "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD"),
            ["SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST"] = ("game_instance", "enter", "GAME_INST_ENTER"),
            ["SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST"] = ("game_instance", "leave", "GAME_INST_LEAVE"),
            ["SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST"] = ("game_instance", "restart", "GAME_INST_RESTART"),
        };

    public static EvidenceObject Data(string kind, EvidenceObject source, string? origin = null, string gameId = "")
    {
        Dictionary<string, EvidenceValue> data = [];
        string[] fields;
        switch (kind)
        {
            case "game_instance": case "game_mechanics":
                var declaration = Mechanics[origin!];
                if (kind != declaration.Type) throw new InvalidDataException("Inconsistent mechanics type");
                data["source"] = new EvidenceText(origin!); data["action"] = new EvidenceText(declaration.Action);
                if (gameId.Length > 0) data["game_id"] = new EvidenceText(gameId);
                fields = ["game_inst_id", "game_unique_id", "is_hunter_mode", "interactive_obj_id", "npc_proxy_id", "npc_obj_id", "time_freeze_infos"];
                break;
            case "scene_battle":
                data["source"] = new EvidenceText(origin!); fields = ["in_battle"]; break;
            case "battle_reset": fields = ["reason", "inst_id", "battle_inst_id"]; break;
            case "session_warning": fields = ["kind", "direction", "missing_bytes", "startup_tcp_gap_count"]; break;
            default: throw new InvalidDataException("Expected context event");
        }
        foreach (var key in fields)
            if (source.Fields.TryGetValue(key, out var value)) data[key == "inst_id" ? "event_inst_id" : key] = value;
        return new(data);
    }

    public static EvidenceObject Observation(TraceEvent item)
    {
        if (item.Type is "game_instance" or "game_mechanics")
        {
            if (item.Data.Get("source") is not EvidenceText source || !Mechanics.TryGetValue(source.Value, out var declaration)
                || item.Type != declaration.Type || item.Data.Get("action") is not EvidenceText action || action.Value != declaration.Action)
                throw new InvalidDataException("Invalid mechanics source/action");
        }
        else if (item.Type == "scene_battle")
        {
            if (item.Data.Get("source") is not EvidenceText) throw new InvalidDataException("Scene source is required");
        }
        else if (item.Type is not ("battle_reset" or "session_warning")) throw new InvalidDataException("Expected context event");
        return item.Data;
    }

    public static (string Marker, IReadOnlyDictionary<string, string> Fields)? TimerObservation(TraceEvent item)
    {
        var data = Observation(item);
        if (item.Type is not ("game_instance" or "game_mechanics")) return null;
        var source = ((EvidenceText)data.Get("source")).Value;
        Dictionary<string, string> fields = new() { ["source"] = source };
        if (data.Get("game_id") is EvidenceText { Value.Length: > 0 } game) fields["gameId"] = game.Value;
        if (data.Get("action") is EvidenceText { Value: "time_freeze" } && data.Get("time_freeze_infos") is EvidenceArray freezes)
        {
            fields["count"] = freezes.Items.Count.ToString(System.Globalization.CultureInfo.InvariantCulture);
            var rows = freezes.Items.OfType<EvidenceObject>().ToArray();
            if (rows.Length > 0) fields["freezeInfos"] = "[" + string.Join(',', rows.Select(row =>
                (SkillWire.Integer(row.Get("time_key")) ?? 0).ToString(System.Globalization.CultureInfo.InvariantCulture) + ":"
                + (SkillWire.Integer(row.Get("total_freeze_time_in_ms")) ?? 0).ToString(System.Globalization.CultureInfo.InvariantCulture))) + "]";
        }
        return (Mechanics[source].Marker, fields);
    }
}
