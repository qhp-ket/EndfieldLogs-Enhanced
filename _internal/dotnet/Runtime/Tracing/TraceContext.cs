using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private static readonly HashSet<string> ClockTypes = ["GAME_CLOCK_TICK", "CS_PING", "SC_PING",
        "CS_GAME_TIME_FREEZE_START_REQ", "CS_GAME_TIME_FREEZE_END_REQ", "SC_GAME_TIME_FREEZE_START_RSP", "SC_GAME_TIME_FREEZE_END_RSP"];
    private static readonly HashSet<string> MechanicTypes = ["CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH",
        "CS_GAME_MECHANICS_REQ_START", "CS_GAME_MECHANICS_REQ_STOP", "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE",
        "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE", "SC_GAME_MECHANICS_SYNC_CHALLENGE_START",
        "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD", "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST",
        "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST", "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST"];
    private string Activity => officialGameId.Length > 0 ? officialGameId
        : dungeonContext is null ? "" : Text(dungeonContext.Get("dungeon_id"), Text(dungeonContext.Get("dungeonId")));
    private bool OfficialRequired => Activity.StartsWith("indie_battletower", StringComparison.Ordinal);

    private void WriteClock(EvidenceObject e, string type, long? time)
    {
        if (time is not { } ts) return;
        if (eventOutput is not null)
        {
            if (ClockWire.Data(e, type) is { } observation) AppendStructured(ts, observation.Type, observation.Data, e);
            return;
        }
        if (type == "GAME_CLOCK_TICK")
        {
            var tick = Int(e.Get("tick_ms"));
            if (Text(e.Get("source")) == "CS_BATTLE_OP" && tick > 0)
                Append(ts, $"GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs={I(tick)} seq={I(Int(e.Get("seq_id")))}");
            return;
        }
        var msg = e.Fields.ContainsKey("msg_id") ? S(e.Get("msg_id")) : "unknown";
        if (type is "CS_PING" or "SC_PING")
        {
            List<string> parts = [$"GAME_CLOCK_SYNC source={type}", "msgId=" + msg, $"captureMs={ts}"];
            foreach (var (key, output) in new[] { ("client_ts", "clientTs"), ("server_ts", "serverTs"), ("logical_ts", "logicalTs") })
                if (Int(e.Get(key)) is { } number && number >= 0) parts.Add(output + "=" + I(number));
            if (e.Get("raw_body_hex") is EvidenceText body) parts.Add("rawBodyHex=" + (body.Value.Length > 0 ? body.Value : "empty"));
            Append(ts, string.Join(' ', parts)); return;
        }
        var raw = e.Get("raw_body_hex") is EvidenceText text ? text.Value.Length > 0 ? text.Value : "empty" : "unknown";
        var reason = I(Int(e.Get("reason")));
        if (type is "CS_GAME_TIME_FREEZE_START_REQ" or "CS_GAME_TIME_FREEZE_END_REQ")
            Append(ts, $"GAME_TIME_FREEZE_REQUEST source={type} reason={reason} msgId={msg} rawBodyHex={raw}");
        else Append(ts, $"GAME_TIME_FREEZE_STATE source={type} inTimeFreeze={(e.Get("in_time_freeze") is EvidenceBoolean flag ? flag.Value ? "1" : "0" : "unknown")} reason={reason} msgId={msg} rawBodyHex={raw}");
    }
    private void Dungeon(EvidenceObject e, long ts)
    {
        var id = Text(e.Get("dungeon_id"), Text(e.Get("dungeonId"))).Trim();
        if (id.Length == 0) return;
        var fields = e.Fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
        fields["dungeon_id"] = new EvidenceText(id); dungeonContext = new(fields); dungeonEmitted = false;
        if (Truth(e.Get("is_calc")) && Truth(e.Get("is_pass")))
        {
            if (eventOutput is not null) EmitStructured(ts, "battle_result", StageWire.Data("battle_result", e, id, Text(e.Get("source"), "DUNGEON_CONTEXT")), e);
            else Line(ts, $"BATTLE_RESULT source={Text(e.Get("source"), "DUNGEON_CONTEXT")} dungeonId={id} isCalc=1 isPass=1");
        }
        WriteDungeon(dungeonContext, ts);
    }
    private void WriteDungeon(EvidenceObject e, long ts)
    {
        if (eventOutput is not null)
        {
            EmitStructured(ts, "dungeon", StageWire.Data("dungeon", e, Text(e.Get("dungeon_id"), Text(e.Get("dungeonId"))).Trim(), Text(e.Get("source"), "packet")), e); return;
        }
        List<string> parts = ["DUNGEON_CONTEXT", "dungeonId=" + Text(e.Get("dungeon_id"), Text(e.Get("dungeonId"))).Trim(), "source=" + Text(e.Get("source"), "packet")];
        Optional(parts, e, ("scene_num_id", "scene"), ("scene_id", "sceneId"), ("challenge_expire_ts", "challengeExpireTs"), ("leave_dungeon_ts", "leaveDungeonTs"), ("char_team_count", "charTeamCount"));
        foreach (var (key, output) in new[] { ("is_reward", "isReward"), ("is_calc", "isCalc"), ("is_pass", "isPass") })
            if (e.Get(key) is not EvidenceNull) parts.Add(output + "=" + (Truth(e.Get(key)) ? "1" : "0"));
        Line(ts, string.Join(' ', parts));
    }
    private void Contracts(EvidenceObject e, long ts)
    {
        var id = Text(e.Get("dungeon_id"), Text(e.Get("dungeonId"))).Trim();
        var raw = Truth(e.Get("tag_ids")) ? e.Get("tag_ids") : Truth(e.Get("tagIds")) ? e.Get("tagIds") : e.Get("display_tag_ids");
        var tags = Items(raw).Select(Int).Where(value => value is { IsZero: false }).ToArray();
        if (id.Length == 0 && tags.Length == 0) return;
        if (eventOutput is not null) { EmitStructured(ts, "contracts", StageWire.Data("contracts", e, id, Text(e.Get("source"), "packet")), e); return; }
        List<string> parts = ["CONTRACT_TAGS", "dungeonId=" + (id.Length > 0 ? id : "unknown"), "source=" + Text(e.Get("source"), "packet"), "tagIds=[" + string.Join(',', tags.Select(value => I(value))) + "]"];
        if (Int(e.Get("score")) is { } score) parts.Add("score=" + I(score));
        if (Text(e.Get("direction")) is { Length: > 0 } direction) parts.Add("direction=" + direction);
        var message = Int(Truth(e.Get("msg_id")) ? e.Get("msg_id") : e.Get("msgId"));
        if (message is not null) parts.Add("msgId=" + I(message));
        Line(ts, string.Join(' ', parts));
    }
    private void ClearBattle() { battleActive = false; battleStartTs = null; battleStartTick = null; dungeonEmitted = false; }
    private void ClearOfficial() { officialActive = officialExpected = false; officialObservedStart = null; officialGameId = ""; }
    private void TimerReset(long ts, string source, BigInteger? scene = null, EvidenceObject? origin = null)
    {
        if (eventOutput is not null)
        {
            var data = Make(("phase", "reset"), ("source", source)).Fields.ToDictionary();
            if (scene is { } number) data["scene_num_id"] = new EvidenceInteger(number);
            EmitStructured(ts, "battle_timer", new(data), origin ?? Make());
        }
        else Line(ts, "GAME_TIMER_RESET source=" + source + (scene is null ? "" : " scene=" + I(scene)));
        ClearBattle(); ClearOfficial();
    }
    private void MissingTimer(long ts, string boundary, EvidenceObject? origin = null)
    {
        if (!battleActive && !officialExpected && !officialActive) return;
        if (eventOutput is not null)
        {
            var data = Make(("phase", "missing"), ("boundary", boundary), ("packet_battle_active", battleActive), ("official_expected", officialExpected), ("official_start_seen", officialActive)).Fields.ToDictionary();
            if (Activity.Length > 0) data["game_id"] = new EvidenceText(Activity);
            EmitStructured(ts, officialExpected || officialActive ? "official_timer" : "battle_timer_missing", new(data), origin ?? Make());
        }
        else Line(ts, $"{(officialExpected || officialActive ? "OFFICIAL_TIMER_MISSING" : "BATTLE_TIMER_MISSING")} boundary={boundary} packetBattleActive={(battleActive ? 1 : 0)} officialExpected={(officialExpected ? 1 : 0)} officialStartSeen={(officialActive ? 1 : 0)}" + (Activity.Length > 0 ? " gameId=" + Activity : ""));
        ClearBattle(); ClearOfficial();
    }
    private void AwaitOfficial(long ts, string source, EvidenceObject origin)
    {
        if (eventOutput is not null) EmitStructured(ts, "official_timer", Make(("phase", "await"), ("source", source), ("game_id", Activity), ("official_start_seen", officialActive)), origin);
        else Line(ts, $"OFFICIAL_TIMER_AWAIT source={source} gameId={Activity} officialStartSeen={(officialActive ? 1 : 0)}");
        ClearBattle();
    }
    private void BattleState(EvidenceObject e, long ts)
    {
        var active = Truth(e.Get("is_in_battle"));
        var seq = I(Int(e.Get("seq_id")) ?? 0);
        var rawTick = Int(e.Get("client_tick_tms")); var tick = rawTick ?? 0;
        if (active && !battleActive)
        {
            var continuation = OfficialRequired && officialExpected;
            battleActive = true;
            if (OfficialRequired) { officialExpected = true; officialGameId = Activity; officialObservedStart ??= ts; }
            battleStartTs = ts; battleStartTick = rawTick;
            if (dungeonContext is not null && !dungeonEmitted) { WriteDungeon(dungeonContext, ts); dungeonEmitted = true; }
            if (continuation)
            {
                if (eventOutput is not null) EmitStructured(ts, "battle_phase", Make(("operation_seq", Int(e.Get("seq_id")) ?? 0), ("source", "BattleOpModifyBattleState"), ("game_id", Activity)), e);
                else Line(ts, $"BATTLE_PHASE_START seq={seq} source=BattleOpModifyBattleState gameId={Activity}");
            }
            else if (eventOutput is not null) EmitStructured(ts, "battle_timer", Make(("phase", "start"), ("operation_seq", Int(e.Get("seq_id")) ?? 0),
                ("source", rawTick is null ? "BattleOpModifyBattleState" : "PacketBattleState"), ("start_ms", tick), ("expire_ms", 0), ("official", rawTick is not null)), e);
            else Line(ts, $"GAME_TIMER_START seq={seq} source={(rawTick is null ? "BattleOpModifyBattleState" : "PacketBattleState")} startMs={I(tick)} expireMs=0 official={(rawTick is null ? 0 : 1)}");
        }
        else if (!active && battleActive)
        {
            if (OfficialRequired) { AwaitOfficial(ts, "BattleOpModifyBattleState", e); return; }
            var start = battleStartTick ?? tick;
            var packetElapsed = rawTick is not null && battleStartTick is not null ? tick - start : (BigInteger?)null;
            var elapsed = battleStartTs is null ? 0 : Math.Max(0, ts - battleStartTs.Value);
            var packet = packetElapsed >= 0;
            if (eventOutput is not null)
            {
                var data = Make(("phase", "end"), ("operation_seq", Int(e.Get("seq_id")) ?? 0), ("source", packet ? "PacketBattleState" : "BattleOpModifyBattleState"),
                    ("elapsed_ms", elapsed), ("start_ms", start), ("end_ms", tick), ("expire_ms", 0), ("sane", elapsed > 0), ("official", packet)).Fields.ToDictionary();
                if (packet) data["packet_elapsed_ms"] = new EvidenceInteger(packetElapsed!.Value);
                EmitStructured(ts, "battle_timer", new(data), e);
            }
            else Line(ts, $"GAME_TIMER_END seq={seq} source={(packet ? "PacketBattleState" : "BattleOpModifyBattleState")} elapsedMs={elapsed} startMs={I(start)} endMs={I(tick)} expireMs=0 sane={(elapsed > 0 ? 1 : 0)} official={(packet ? 1 : 0)}" + (packet ? " packetElapsedMs=" + I(packetElapsed) : ""));
            ClearBattle();
        }
    }
    private void Mechanics(EvidenceObject e, string type, long ts)
    {
        var game = Text(e.Get("game_id"), Text(e.Get("cur_game_id")));
        if (type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_START")
        {
            officialExpected = officialActive = true; officialObservedStart = ts; officialGameId = game;
            if (eventOutput is not null) { EmitStructured(ts, "official_timer", TimerWire.OfficialData(e, "start", game, type), e); return; }
            List<string> parts = ["OFFICIAL_TIMER_START", "source=" + type];
            if (game.Length > 0) parts.Add("gameId=" + game);
            Optional(parts, e, ("challenge_start_ts", "challengeStartTs"), ("challenge_expire_ts", "challengeExpireTs"), ("prepare_challenge_seconds", "prepareSeconds"));
            Line(ts, string.Join(' ', parts)); return;
        }
        if (type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE")
        {
            if (eventOutput is not null) { EmitStructured(ts, "official_timer", TimerWire.OfficialData(e, "end", game, type), e); ClearBattle(); ClearOfficial(); return; }
            List<string> parts = ["OFFICIAL_TIMER_END", "source=" + type];
            if (game.Length > 0) parts.Add("gameId=" + game);
            if (e.Get("is_pass") is not EvidenceNull) parts.Add("isPass=" + (Truth(e.Get("is_pass")) ? "1" : "0"));
            Optional(parts, e, ("pass_time", "passTime"), ("force_leave_ts", "forceLeaveTs"));
            Line(ts, string.Join(' ', parts)); ClearBattle(); ClearOfficial(); return;
        }
        if (eventOutput is not null)
        {
            var kind = ContextWire.Mechanics[type].Type;
            EmitStructured(ts, kind, ContextWire.Data(kind, e, type, game), e);
            if (type is "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST" or "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST")
            { MissingTimer(ts, type, e); TimerReset(ts, type, origin: e); }
            return;
        }
        var label = type switch
        {
            "CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH" => "GAME_MECHANICS_PREPARE_FINISH",
            "CS_GAME_MECHANICS_REQ_START" => "GAME_MECHANICS_REQ_START", "CS_GAME_MECHANICS_REQ_STOP" => "GAME_MECHANICS_REQ_STOP",
            "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE" => "GAME_MECHANICS_TIME_FREEZE", "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST" => "GAME_INST_ENTER",
            "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST" => "GAME_INST_LEAVE", "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST" => "GAME_INST_RESTART", _ => type,
        };
        List<string> body = [label, "source=" + type];
        if (game.Length > 0) body.Add("gameId=" + game);
        foreach (var (key, output) in new[] { ("game_inst_id", "gameInstId"), ("game_unique_id", "gameUniqueId"), ("is_hunter_mode", "isHunterMode"), ("interactive_obj_id", "interactiveObjId"), ("npc_proxy_id", "npcProxyId"), ("npc_obj_id", "npcObjId") })
            if (e.Get(key) is not EvidenceNull && e.Get(key) is not EvidenceText { Value.Length: 0 }) body.Add(output + "=" + (key == "is_hunter_mode" ? Truth(e.Get(key)) ? "1" : "0" : S(e.Get(key))));
        if (type == "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE" && e.Get("time_freeze_infos") is EvidenceArray freezes)
        {
            body.Add("count=" + freezes.Items.Count);
            var rows = Rows(freezes).ToArray();
            if (rows.Length > 0)
            {
                body.Add("freezeInfos=[" + string.Join(',', rows.Select(row => I(Int(row.Get("time_key")) ?? 0) + ":" + I(Int(row.Get("total_freeze_time_in_ms")) ?? 0))) + "]");
                body.Add("totalFreezeMs=" + I(rows.Select(row => Int(row.Get("total_freeze_time_in_ms")) ?? 0).Append(BigInteger.Zero).Max()));
            }
        }
        Line(ts, string.Join(' ', body));
        if (type is "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST" or "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST") { MissingTimer(ts, type, e); TimerReset(ts, type, origin: e); }
    }
    private void Settlement(EvidenceObject e, long ts)
    {
        var game = Text(e.Get("game_id")).Trim();
        if (!game.StartsWith("indie_battletower", StringComparison.Ordinal) || (!battleActive && !officialExpected && !officialActive)) return;
        if (eventOutput is not null)
        {
            var data = Make(("phase", "end"), ("source", "SC_SYNC_WEEK_RAID_SETTLEMENT"), ("game_id", game), ("is_pass", true)).Fields.ToDictionary();
            if (Int(e.Get("total_playtime")) is { } durationValue && durationValue >= 0) data["pass_time"] = new EvidenceInteger(durationValue);
            foreach (var key in new[] { "bp_score", "danger_meter" }) if (Int(e.Get(key)) is { } value) data[key] = new EvidenceInteger(value);
            EmitStructured(ts, "official_timer", new(data), e); ClearBattle(); ClearOfficial(); return;
        }
        List<string> parts = ["OFFICIAL_TIMER_END source=SC_SYNC_WEEK_RAID_SETTLEMENT", "gameId=" + game, "isPass=1"];
        if (Int(e.Get("total_playtime")) is { } duration && duration >= 0) parts.Add("passTime=" + I(duration));
        foreach (var (key, output) in new[] { ("bp_score", "bpScore"), ("danger_meter", "dangerMeter") })
            if (Int(e.Get(key)) is { } number) parts.Add(output + "=" + I(number));
        Line(ts, string.Join(' ', parts)); ClearBattle(); ClearOfficial();
    }
}
