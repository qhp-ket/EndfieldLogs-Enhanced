using System.Numerics;
using System.Globalization;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Single-owner canonical trace state. Each completed line has one ordered disk/live destination.</summary>
public sealed partial class TraceBridge(Action<string> lineSink, SkillResourceCatalog? identities = null,
    TimeZoneInfo? timeZone = null, Func<long>? clock = null, Action<TraceEvent>? damageSink = null, Action<TraceEvent>? eventSink = null)
{
    private readonly Action<TraceEvent>? eventOutput = damageSink is not null && eventSink is not null
        ? throw new ArgumentException("Choose one structured event destination") : eventSink;
    private readonly Action<TraceEvent>? damageOutput = damageSink ?? eventSink;
    private readonly Dictionary<BigInteger, string> names = [], aliases = [], skills = [], skillSources = [], buffIds = [];
    private readonly HashSet<string> emittedSkills = new(StringComparer.Ordinal);
    private readonly Dictionary<BigInteger, (BigInteger? Owner, BigInteger? Source)> buffActors = [];
    private readonly Dictionary<BigInteger, Dictionary<string, double>> buffValues = [];
    private readonly Dictionary<BigInteger, HashSet<string>> buffKeys = [];
    private readonly Dictionary<BigInteger, List<(BigInteger Action, double Value)>> dynamicBb = [];
    private readonly Dictionary<BigInteger, List<(BigInteger Action, string Key, double Value)>> calcBb = [];
    private readonly Dictionary<(string Session, string Owner, string Uid), (BigInteger Seq, double? Rate)> keywordSerials = [];
    private readonly List<EvidenceObject> pendingAdd = [], pendingCreate = [];
    private readonly Dictionary<BigInteger, (string Buff, string Owner, string Source, EvidenceValue Assigned, EvidenceObject Origin)> pendingStarts = [];
    private long? lastTs, addTs, createTs, startTs, battleStartTs;
    private BigInteger? battleStartTick;
    private long hitSeq, buffSeq;
    private bool battleActive, officialActive, officialExpected, dungeonEmitted, hasSceneSquad;
    private long? officialObservedStart;
    private string officialGameId = "";
    private EvidenceObject? dungeonContext;

    public void Handle(BattleLogEvent value) => Handle((EvidenceObject)Value(value.ToPayload()));
    public void Handle(EvidenceObject source)
    {
        // Pending batches own their event data; callers can reuse/mutate decoded payload containers.
        var e = (EvidenceObject)EvidenceJson.Clone(source);
        var type = Text(e.Get("type"));
        var time = Int(e.Get("timestamp_ms"));
        if (ClockTypes.Contains(type)) { WriteClock(e, type, time is null ? null : checked((long)time)); return; }
        var ts = time is null ? Now() : checked((long)time);
        lastTs = ts;
        var action = Obj(e.Get("action"));
        var create = type == "BattleOpTriggerAction" && (Text(action.Get("action_type")) == "BattleActionCreateBuff" || action.Fields.ContainsKey("create_buff_action"));
        if (type != "BattleOpAddBuff") FlushAdds();
        if (!create) FlushCreates();
        switch (type)
        {
            case "DUNGEON_CONTEXT": Dungeon(e, ts); break;
            case "CS_ENTER_DUNGEON": case "CS_SCENE_LOAD_FINISH":
                MissingTimer(ts, type, e); TimerReset(ts, type, Int(e.Get("scene_num_id")), e); break;
            case "CS_SCENE_SET_BATTLE": case "SC_SCENE_SET_BATTLE":
                if (eventOutput is not null) EmitStructured(ts, "scene_battle", ContextWire.Data("scene_battle", e, type), e);
                else Line(ts, $"SCENE_BATTLE_STATE source={type} inBattle={(Truth(e.Get("in_battle")) ? 1 : 0)}");
                if (!Truth(e.Get("in_battle")) && OfficialRequired && battleActive) AwaitOfficial(ts, type, e);
                break;
            case "CONTRACT_TAGS": Contracts(e, ts); break;
            case "SC_SELF_SCENE_INFO": Scene(e, ts); break;
            case "SC_SELF_SCENE_INFO_SKILLS": SceneSkills(e, ts); break;
            case "SC_OBJECT_ENTER_VIEW": Objects(e, ts); break;
            case "SC_SYNC_ATTR": Attributes(e, ts); break;
            case "LOADOUT": Loadout(e, ts); break;
            case "BattleOpSkillAttach": Attach(e, ts); break;
            case "BattleOpSkillDetach":
                if (Id(e.Get("skill_inst_id")) is { } detached) { skills.Remove(detached); skillSources.Remove(detached); } break;
            case "BattleOpSkillStartCast": Cast(e, ts, true); break;
            case "BattleOpSkillEndCast": Cast(e, ts, false); break;
            case "BattleOpUpdateAtbInfo": Atb(e, ts); break;
            case "BattleOpModifyPoiseValue": Poise(e, ts); break;
            case "BattleOpModifyBattleState": BattleState(e, ts); break;
            case "SC_RESET_BATTLE_STATUS":
                if (eventOutput is not null) { EmitStructured(ts, "battle_reset", ContextWire.Data("battle_reset", e), e); break; }
                var parts = new List<string> { "BATTLE_RESET_STATUS" };
                Optional(parts, e, ("reason", "reason"), ("inst_id", "inst"), ("battle_inst_id", "battleInst")); Line(ts, string.Join(' ', parts)); break;
            case "SC_SYNC_WEEK_RAID_SETTLEMENT": Settlement(e, ts); break;
            case "BattleOpAddBuff":
                if (addTs is not null && addTs != ts) FlushAdds(); addTs = ts; pendingAdd.Add(e); break;
            case "BattleOpFinishBuff": if (Id(e.Get("buff_inst_id")) is { } uid) Finish(ts, uid, e); break;
            case "BattleOpTriggerAction":
                if (create) { if (createTs is not null && createTs != ts) FlushCreates(); createTs = ts; pendingCreate.Add(e); }
                else Trigger(e, action, ts);
                break;
            case "BattleOpTriggerKeyword": Keyword(e, ts); break;
            case "BattleOpSetBuffEnableState": Enable(e, ts); break;
            case "BattleOpEntityDie":
                if (eventOutput is not null) EmitStructured(ts, "entity_die", new(e.Fields.TryGetValue("entity_inst_id", out var dead)
                    ? new Dictionary<string, EvidenceValue> { ["entity_id"] = dead } : []), e);
                else Line(ts, "ENTITY_DIE id=" + S(e.Get("entity_inst_id")));
                break;
            case "BattleOpEntityValueModify": EntityValue(e, ts); break;
            case "SESSION_WARNING":
                if (eventOutput is not null) { EmitStructured(ts, "session_warning", ContextWire.Data("session_warning", e), e); break; }
                Line(ts, $"SESSION_WARNING kind={Text(e.Get("kind"), "unknown")} direction={Text(e.Get("direction"), "unknown")} missingBytes={Present(e.Get("missing_bytes"))} gapCount={Present(e.Get("startup_tcp_gap_count"))}"); break;
            default: if (MechanicTypes.Contains(type)) Mechanics(e, type, ts); break;
        }
    }

    public void BeginCaptureSession(long? timestampMs = null)
    {
        lastTs = timestampMs ?? Now();
        TimerReset(lastTs.Value, "CAPTURE_SESSION_START");
        names.Clear(); aliases.Clear(); skills.Clear(); skillSources.Clear(); emittedSkills.Clear();
        buffIds.Clear(); buffActors.Clear(); buffValues.Clear(); buffKeys.Clear(); keywordSerials.Clear();
        dynamicBb.Clear(); calcBb.Clear(); hitSeq = buffSeq = 0;
        pendingAdd.Clear(); pendingCreate.Clear(); pendingStarts.Clear(); addTs = createTs = startTs = null;
        dungeonContext = null; hasSceneSquad = false;
    }

    public void EndCaptureSession(long? timestampMs = null)
    {
        lastTs = timestampMs ?? lastTs ?? Now();
        FlushPending(); MissingTimer(lastTs.Value, "CAPTURE_SESSION_LOST");
    }
    public void FlushPending() { FlushAdds(); FlushCreates(); FlushStarts(); }

    private long Now() => clock?.Invoke() ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private void Line(long ts, string body) { FlushStarts(); Append(ts, body); }
    private void Append(long ts, string body)
    {
        var local = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds(ts), timeZone ?? TimeZoneInfo.Local);
        lineSink("[" + local.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + "] " + body + "\n");
    }
    private static void Optional(List<string> parts, EvidenceObject e, params (string Input, string Output)[] fields)
    {
        foreach (var (input, output) in fields) if (e.Get(input) is not EvidenceNull) parts.Add(output + "=" + S(e.Get(input)));
    }
    private string Name(BigInteger? id, bool target = false)
    {
        if (id is null || (!target && id.Value.IsZero)) return "?";
        var found = names.GetValueOrDefault(id.Value);
        if (target) return found ?? aliases.GetValueOrDefault(id.Value) ?? "id_" + I(id);
        if (!string.IsNullOrEmpty(found) && found != "eny_0000_unknown") return found;
        return aliases.GetValueOrDefault(id.Value) ?? found ?? "id_" + I(id);
    }
    private string? ResolveSkill(EvidenceValue strId, EvidenceValue intId)
    {
        if (strId is EvidenceText { Value.Length: > 0 } key) return key.Value;
        var number = Int(intId);
        return number is not null && number >= 0 ? identities?.Skills.GetValueOrDefault(I(number)) : null;
    }
    private string ResolveBuff(EvidenceValue strId, EvidenceValue intId)
    {
        if (strId is EvidenceText { Value.Length: > 0 } key) return key.Value;
        var number = Int(intId);
        return number is not null && number >= 0 ? identities?.Buffs.GetValueOrDefault(I(number)) ?? I(number) : "unknown_buff";
    }
    private string TriggerSkill(EvidenceObject e)
    {
        var text = Text(e.Get("template_str_id"));
        if (text.Length > 0) return text;
        var number = Int(e.Get("template_int_id"));
        if (number is null) return "unknown_skill";
        return Text(e.Get("template_type")).ToLowerInvariant() switch
        {
            "buff" => ResolveBuff(EvidenceNull.Value, new EvidenceInteger(number.Value)),
            "skill" => ResolveSkill(EvidenceNull.Value, new EvidenceInteger(number.Value)) ?? "skill_" + I(number),
            _ => "skill_" + I(number),
        };
    }
}
