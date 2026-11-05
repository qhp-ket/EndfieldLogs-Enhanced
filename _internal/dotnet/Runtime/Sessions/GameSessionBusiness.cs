using System.Globalization;
using System.Numerics;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Catalog;
using Google.Protobuf;

namespace EndfieldLogs.Runtime.Sessions;

public sealed record SessionOwner(BigInteger BattleInstanceId, BigInteger? ObjectId, string? TemplateId,
    string? DisplayName = null, int? SquadIndex = null);

/// <summary>Single-owner decoded message business state. Events retain the existing external payload contract.</summary>
public sealed partial class GameSessionBusiness(string sessionId, Action<BattleLogEvent> emit,
    Action<string, long, bool>? loadoutContext = null, bool rotationClockTrace = true,
    IReadOnlyDictionary<string, string>? names = null, IReadOnlyDictionary<string, string>? multiPhaseDungeons = null,
    LoadoutDisplayCatalog? loadoutCatalog = null)
{
    private readonly Dictionary<BigInteger, SessionOwner> owners = [];
    private readonly Dictionary<BigInteger, Dictionary<string, BigInteger>> skillLevels = [];
    private readonly Dictionary<BigInteger, Dictionary<BigInteger, Dictionary<string, object?>>> serverSkills = [];
    private readonly Dictionary<BigInteger, BigInteger> skillOwners = [];

    public bool MergeMultiPhaseEnemyBattles { get; set; }
    public string? TrackedEnemyTemplateId { get; set; }
    public HashSet<BigInteger> TrackedEnemyInstanceIds { get; } = [];
    public bool MergedBattleActive { get; private set; }

    // Scene/inventory owners supply these observations; operation decoding never invents a level or owner.
    public void ObserveOwner(SessionOwner owner, IMessage battleInfo)
    {
        owners[owner.BattleInstanceId] = owner;
        var skills = new ProtoMessage(battleInfo).Children("skill_list").ToArray();
        Dictionary<string, BigInteger> levels = new(StringComparer.Ordinal);
        foreach (var skill in skills)
        {
            var template = ProtoMessage.Template(skill.Child("skill_id"));
            var key = TemplateKey(template);
            if (key is not null) levels[key] = skill.Optional("level") ?? BigInteger.One;
        }
        if (levels.Count > 0) skillLevels[owner.BattleInstanceId] = levels;
        RefreshWeaponSkillEvidence(owner.BattleInstanceId, new ProtoMessage(battleInfo));
        if (serverSkills.Remove(owner.BattleInstanceId, out var previous))
            foreach (var instance in previous.Keys) skillOwners.Remove(instance);
        CacheSkills(owner.BattleInstanceId, skills.Select(skill => SkillRow(owner.BattleInstanceId, skill)));
    }

    public void RemoveOwner(BigInteger instance)
    {
        owners.Remove(instance);
        // The source retains per-owner level evidence until the next scene roster snapshot.
        if (serverSkills.Remove(instance, out var rows)) foreach (var skill in rows.Keys) skillOwners.Remove(skill);
    }

    public void ClearSceneSkillLevels() => skillLevels.Clear();

    public IReadOnlyList<IReadOnlyDictionary<string, object?>> ServerSkills(BigInteger owner) =>
        serverSkills.GetValueOrDefault(owner)?.Values.Select(row => (IReadOnlyDictionary<string, object?>)CloneRow(row)).ToArray() ?? [];

    public IReadOnlyDictionary<BigInteger, IReadOnlyList<IReadOnlyDictionary<string, object?>>> ServerSkillSnapshot() =>
        serverSkills.Keys.ToDictionary(owner => owner, ServerSkills);

    public bool Process(DecodedMessage decoded, long timestampMs)
    {
        var message = new ProtoMessage(decoded.Message);
        var kind = decoded.ClassName;
        if (ProcessScene(decoded, message, timestampMs)) return true;
        if (ProcessInventory(kind, message, timestampMs)) return true;
        if (kind == "CS_BATTLE_OP") { DecodeOperations(message, timestampMs); return true; }
        if (kind is "SC_ATTACH_SERVER_SKILL" or "SC_UPDATE_SERVER_SKILL")
        {
            if (message.Optional("inst_id") is { } owner)
            {
                var rows = message.Children("skills").Select(skill => SkillRow(owner, skill)).ToArray();
                CacheSkills(owner, rows);
                EmitSkills(kind, owner, message.Optional("generation"), rows, timestampMs);
            }
            return true;
        }
        if (kind == "SC_DETACH_SERVER_SKILL") { DetachSkills(message, timestampMs); return true; }
        if (kind is "CS_PING" or "SC_PING" or "CS_GAME_TIME_FREEZE_START_REQ" or "CS_GAME_TIME_FREEZE_END_REQ"
            or "SC_GAME_TIME_FREEZE_START_RSP" or "SC_GAME_TIME_FREEZE_END_RSP")
        {
            var payload = message.Payload(defaults: true);
            payload["direction"] = decoded.Direction;
            payload["msg_id"] = decoded.MessageId;
            payload["raw_body_hex"] = Convert.ToHexStringLower(decoded.RawBody);
            Emit(kind, timestampMs, payload);
            return true;
        }
        if (kind is "CS_CONTINGENCY_CONTRACT_SET_TAGS" or "SC_CONTINGENCY_CONTRACT_SET_TAGS"
            or "SC_CONTINGENCY_CONTRACT_TAGS_SYNC" or "SC_CONTINGENCY_CONTRACT_BATTLE_RESULT")
        {
            var dungeon = message.Text("dungeon_id").Trim();
            var tags = message.Items("tag_ids").Select(Integer).Where(id => id > 0).ToArray();
            var display = message.Items("display_tag_ids").Select(Integer).Where(id => id > 0).ToArray();
            if (tags.Length == 0) tags = display.ToArray();
            if (dungeon.Length > 0 || tags.Length > 0)
                Emit("CONTRACT_TAGS", timestampMs, new() { ["dungeon_id"] = dungeon.Length > 0 ? dungeon : null,
                    ["tag_ids"] = tags, ["display_tag_ids"] = display, ["score"] = message.Optional("score"),
                    ["source"] = kind, ["direction"] = decoded.Direction, ["msg_id"] = decoded.MessageId });
            return true;
        }
        if (Passthrough.Contains(kind)) { Emit(kind, timestampMs, message.Payload()); return true; }
        // Callers retain diagnostics for classes outside the maintained business dispatch.
        return false;
    }

    private static readonly HashSet<string> Passthrough = new(StringComparer.Ordinal)
    {
        "CS_DEV_CLEAR_BATTLE_INFO", "CS_CONDITIONAL_MULTI_STAGE_ACTIVITY_GAIN_REWARD", "CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH",
        "CS_GAME_MECHANICS_REQ_START", "CS_GAME_MECHANICS_REQ_STOP", "CS_SCENE_LOAD_FINISH", "CS_SCENE_SET_BATTLE",
        "SC_ACTIVITY_CONDITIONAL_MULTI_STAGE_BASE_CHANGE", "SC_ACTIVITY_CONDITIONAL_STAGE_PROGRESS_CHANGE", "SC_ACTIVITY_PROGRESS_CHANGE",
        "SC_ADD_SERVER_BUFF", "SC_REMOVE_SERVER_BUFF", "SC_BATTLE_ADD_GLOBAL_BUFF", "SC_BATTLE_DEBUG_INFO", "SC_BATTLE_GENERATION_CHANGE",
        "SC_BATTLE_REMOVE_GLOBAL_BUFF", "SC_BATTLE_SYNC_GLOBAL_BUFF_INFO", "SC_BATTLE_SYNC_SEQ_ID", "SC_ENTER_DUNGEON",
        "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE", "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE", "SC_GAME_MECHANICS_SYNC_CHALLENGE_START",
        "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD", "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST", "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST",
        "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST", "SC_CONDITIONAL_MULTI_STAGE_ACTIVITY_GAIN_REWARD", "SC_RESET_BATTLE_STATUS",
        "SC_SCENE_SET_BATTLE", "SC_SYNC_FULL_DUNGEON_STATUS", "SC_SYNC_WEEK_RAID_SETTLEMENT",
    };

    private void Emit(string kind, long timestampMs, Dictionary<string, object?> payload) => emit(new(sessionId, timestampMs, kind, payload));
    private static BigInteger Integer(object value) => BigInteger.Parse(Convert.ToString(value, CultureInfo.InvariantCulture)!, CultureInfo.InvariantCulture);
    private static string? TemplateKey((string? Type, BigInteger? Number, string? Text) id) => id.Text is { Length: > 0 } text
        ? $"{(id.Type ?? "unknown").ToLowerInvariant()}:str:{text}"
        : id.Number is { } number ? $"{(id.Type ?? "unknown").ToLowerInvariant()}:int:{number}" : null;

    private Dictionary<string, object?> OwnerMetadata(BigInteger? id)
    {
        var owner = id is { } value ? owners.GetValueOrDefault(value) : null;
        return new() { ["owner_inst_id"] = id, ["owner_obj_id"] = owner?.ObjectId, ["owner_templateid"] = owner?.TemplateId,
            ["owner_display_name"] = owner?.DisplayName ?? owner?.TemplateId, ["owner_squad_index"] = owner?.SquadIndex };
    }

    private static Dictionary<string, object?> SkillRow(BigInteger owner, ProtoMessage skill)
    {
        var template = ProtoMessage.Template(skill.Child("skill_id"));
        Dictionary<string, object?> row = new() { ["owner_inst_id"] = owner, ["skill_inst_id"] = skill.Optional("inst_id"),
            ["template_type"] = template.Type, ["template_int_id"] = template.Number, ["level"] = skill.Optional("level"),
            ["potential_lv"] = skill.Optional("potential_lv"), ["source"] = skill.Enum("source"),
            ["is_server_init"] = skill.Boolean("is_server_init"), ["is_enable"] = skill.Boolean("is_enable"), ["is_passive"] = skill.Boolean("is_passive") };
        if (template.Text is not null) row["template_str_id"] = template.Text;
        var nodes = skill.Items("talent_node_ids").Select(value => value.ToString()!).Where(value => value.Length > 0).ToArray();
        if (nodes.Length > 0) row["talent_node_ids"] = nodes;
        return row;
    }

    private void CacheSkills(BigInteger owner, IEnumerable<Dictionary<string, object?>> rows)
    {
        if (!serverSkills.TryGetValue(owner, out var state)) serverSkills[owner] = state = [];
        foreach (var row in rows)
            if (row["skill_inst_id"] is BigInteger instance) { state[instance] = CloneRow(row); skillOwners[instance] = owner; }
    }

    private void EmitSkills(string kind, BigInteger owner, BigInteger? generation,
        IEnumerable<Dictionary<string, object?>> rows, long timestampMs)
    {
        var payload = OwnerMetadata(owner);
        payload["generation"] = generation;
        payload["skills"] = rows.OrderBy(row => row["template_int_id"] as BigInteger? ?? 0)
            .ThenBy(row => row["skill_inst_id"] as BigInteger? ?? 0).ToArray();
        Emit(kind, timestampMs, payload);
    }

    private void DetachSkills(ProtoMessage message, long timestampMs)
    {
        var owner = message.Optional("inst_id");
        var deleted = message.Items("del_inst_ids").Select(Integer).Where(id => !id.IsZero).ToArray();
        List<Dictionary<string, object?>> removed = [];
        if (owner is { } value && serverSkills.TryGetValue(value, out var state))
        {
            foreach (var instance in deleted)
            {
                if (state.Remove(instance, out var row)) removed.Add(row);
                skillOwners.Remove(instance);
            }
            if (state.Count == 0) serverSkills.Remove(value);
        }
        var payload = OwnerMetadata(owner);
        payload["generation"] = message.Optional("generation");
        payload["del_skill_inst_ids"] = deleted;
        payload["removed_skills"] = removed;
        Emit("SC_DETACH_SERVER_SKILL", timestampMs, payload);
    }

    private static Dictionary<string, object?> CloneRow(Dictionary<string, object?> row) => row.ToDictionary(pair => pair.Key,
        pair => pair.Value is string[] list ? list.ToArray() : pair.Value, StringComparer.Ordinal);
}
