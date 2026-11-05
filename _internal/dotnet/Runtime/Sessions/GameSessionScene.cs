using System.Numerics;
using System.Globalization;
using EndfieldLogs.Capture.Framing;
using Google.Protobuf;

namespace EndfieldLogs.Runtime.Sessions;

public sealed partial class GameSessionBusiness
{
    private static readonly string[] EndminVariants = ["chr_0002_endminm", "chr_0003_endminf"];
    private readonly Dictionary<BigInteger, SessionOwner> entities = [];
    private readonly Dictionary<BigInteger, BigInteger> objectToBattle = [];
    private readonly Dictionary<BigInteger, SceneMember> squad = [];
    private readonly Dictionary<string, BigInteger> potentials = new(StringComparer.Ordinal);
    private BigInteger[] sceneTeam = [];
    private BigInteger[]? dungeonTeam;
    private string? trackedDungeonId;

    public IReadOnlyList<BigInteger> SceneTeam => sceneTeam.ToArray();
    public IReadOnlyList<BigInteger>? DungeonTeam => dungeonTeam?.ToArray();
    public string? TrackedDungeonId => trackedDungeonId;

    private sealed record SceneMember(SessionOwner Owner, bool IsLeader, BigInteger? Level, double? Hp)
    {
        public List<Dictionary<string, object?>> Attributes { get; set; } = [];
    }

    private bool ProcessScene(DecodedMessage decoded, ProtoMessage message, long timestampMs)
    {
        switch (decoded.ClassName)
        {
            case "CS_ENTER_DUNGEON":
                var entered = message.Payload();
                entered["raw_body_len"] = decoded.RawBody.Length;
                entered["raw_body_hex"] = Convert.ToHexStringLower(decoded.RawBody);
                Emit(decoded.ClassName, timestampMs, entered);
                EnterDungeon(message, timestampMs);
                return true;
            case "CS_LEAVE_DUNGEON":
                sceneTeam = []; dungeonTeam = null;
                if (MergeMultiPhaseEnemyBattles && MergedBattleActive)
                    Emit("BattleOpModifyBattleState", timestampMs, new() { ["seq_id"] = null, ["client_tick_tms"] = null, ["is_in_battle"] = false });
                trackedDungeonId = null; TrackedEnemyTemplateId = null; TrackedEnemyInstanceIds.Clear(); MergedBattleActive = false;
                return true;
            case "SC_SELF_SCENE_INFO": UpdateSquad(message, timestampMs); return true;
            case "SC_OBJECT_ENTER_VIEW": UpdateEntities(message, timestampMs); return true;
            case "SC_OBJECT_LEAVE_VIEW":
                foreach (var item in message.Children("obj_list"))
                    if (item.Optional("obj_id") is { } obj && objectToBattle.Remove(obj, out var id))
                    { entities.Remove(id); squad.Remove(id); RemoveOwner(id); }
                return true;
            case "SC_SYNC_ATTR": UpdateAttributes(message, timestampMs); return true;
            default: return false;
        }
    }

    private void EmitBattleContext(long timestampMs)
    {
        if (squad.Count > 0) EmitSceneInfo(timestampMs);
        EmitLoadout("BATTLE_START", timestampMs, true);
    }

    private void EnterDungeon(ProtoMessage message, long timestampMs)
    {
        sceneTeam = [];
        var team = message.Children("char_team").ToArray();
        var ids = team.Select(row => row.Number("obj_id")).Where(id => !id.IsZero).ToArray();
        dungeonTeam = ids.Length > 0 ? ids : null;
        var dungeon = message.Text("dungeon_id").Trim();
        if (dungeon.Length > 0) Emit("DUNGEON_CONTEXT", timestampMs, new() { ["source"] = "CS_ENTER_DUNGEON", ["dungeon_id"] = dungeon, ["char_team_count"] = team.Length });
        if (!MergeMultiPhaseEnemyBattles) return;
        var template = multiPhaseDungeons?.GetValueOrDefault(dungeon);
        if (string.IsNullOrEmpty(template))
        {
            trackedDungeonId = null; TrackedEnemyTemplateId = null; TrackedEnemyInstanceIds.Clear(); MergedBattleActive = false;
            return;
        }
        trackedDungeonId = dungeon; TrackedEnemyTemplateId = template;
        TrackedEnemyInstanceIds.Clear();
        foreach (var entity in entities.Values) if (entity.TemplateId == template) TrackedEnemyInstanceIds.Add(entity.BattleInstanceId);
    }

    private static List<Dictionary<string, object?>> Attributes(ProtoMessage value)
    {
        List<Dictionary<string, object?>> rows = [];
        foreach (var attr in value.Children(value.Declares("attrs") ? "attrs" : "attr_list"))
        {
            var type = attr.Number("attr_type");
            if (!type.IsZero) rows.Add(new() { ["attr_type"] = type, ["basic_value"] = attr.Real("basic_value"), ["value"] = attr.Real("value") });
        }
        return rows;
    }

    private string? DisplayName(string? template) => template is null ? null : names?.GetValueOrDefault(template) ?? template;
    private static string? EndminVariant(string text) => EndminVariants.FirstOrDefault(text.Contains);

    private static string? SceneTemplate(ProtoMessage common, ProtoMessage battle)
    {
        var template = common.Text("templateid");
        if (template != "chr_9000_endmin") return template.Length > 0 ? template : null;
        foreach (var buff in battle.Children("buff_list")) if (EndminVariant(buff.Text("stacking_group_id")) is { } variant) return variant;
        foreach (var group in battle.Children("stacking_group_list")) if (EndminVariant(group.Text("stacking_key")) is { } variant) return variant;
        foreach (var skill in battle.Children("skill_list"))
        {
            foreach (var node in skill.Items("talent_node_ids")) if (EndminVariant(node.ToString() ?? "") is { } variant) return variant;
            foreach (var (_, value) in skill.Child("blackboard").Mapping("blackboard"))
                if (value is IMessage typed && EndminVariant(new ProtoMessage(typed).Text("str_value")) is { } variant) return variant;
        }
        return template;
    }

    private BigInteger Potential(string? template) => template is null ? BigInteger.Zero
        : potentials.TryGetValue(template, out var level) ? level
        : EndminVariants.Contains(template) ? potentials.GetValueOrDefault("chr_9000_endmin") : BigInteger.Zero;

    private static Dictionary<string, object?>? SceneDungeon(ProtoMessage message)
    {
        if (!message.Has("dungeon")) return null;
        var dungeon = message.Child("dungeon");
        var id = dungeon.Text("dungeon_id").Trim();
        if (id.Length == 0) return null;
        var scene = message.Optional("scene_id")?.ToString(CultureInfo.InvariantCulture);
        return new() { ["dungeon_id"] = id, ["source"] = "SC_SELF_SCENE_INFO", ["scene_num_id"] = message.Optional("scene_num_id"),
            ["scene_id"] = scene, ["challenge_expire_ts"] = dungeon.Optional("challenge_expire_ts"),
            ["leave_dungeon_ts"] = dungeon.Optional("leave_dungeon_ts"), ["is_reward"] = dungeon.Boolean("is_reward"),
            ["is_calc"] = dungeon.Boolean("is_calc"), ["is_pass"] = dungeon.Boolean("is_pass") };
    }

    private void EmitSceneInfo(long timestampMs, Dictionary<string, object?>? dungeon = null, ProtoMessage message = default)
    {
        var rows = squad.Values.OrderBy(member => member.Owner.SquadIndex).Select(member => new Dictionary<string, object?>
        {
            ["id"] = member.Owner.ObjectId, ["templateid"] = member.Owner.TemplateId, ["battle_inst_id"] = member.Owner.BattleInstanceId,
            ["display_name"] = member.Owner.DisplayName ?? DisplayName(member.Owner.TemplateId), ["potential_level"] = Potential(member.Owner.TemplateId),
            ["is_leader"] = member.IsLeader, ["squad_index"] = member.Owner.SquadIndex, ["level"] = member.Level, ["hp"] = member.Hp,
            ["attrs"] = member.Attributes.Select(CloneRow).ToArray(),
        }).ToArray();
        Dictionary<string, object?> payload = new() { ["dungeon"] = dungeon, ["char_list"] = rows };
        if (message.Value is not null)
        {
            payload["scene_num_id"] = message.Optional("scene_num_id");
            payload["scene_id"] = message.Optional("scene_id")?.ToString(CultureInfo.InvariantCulture);
        }
        Emit("SC_SELF_SCENE_INFO", timestampMs, payload);
    }

    private void UpdateSquad(ProtoMessage message, long timestampMs)
    {
        var dungeon = SceneDungeon(message);
        if (dungeon is not null) Emit("DUNGEON_CONTEXT", timestampMs, new(dungeon));
        var characters = message.Child("detail").Children("char_list").ToArray();
        if (characters.Length == 0) return;
        var leader = message.Child("team_info").Number("cur_leader_id");
        var previous = squad.Keys.ToArray();
        foreach (var old in previous)
            if (entities.TryGetValue(old, out var entity)) owners[old] = entity;
        squad.Clear(); skillLevels.Clear();
        List<BigInteger> ids = [];
        for (var index = 0; index < characters.Length; index++)
        {
            var character = characters[index];
            var common = character.Child("common_info");
            var battle = character.Child("battle_info");
            var id = battle.Number("battle_inst_id");
            if (id.IsZero) continue;
            var obj = common.Optional("id");
            var template = SceneTemplate(common, battle);
            SessionOwner owner = new(id, obj, template, DisplayName(template), index);
            SceneMember member = new(owner, obj == leader, character.Optional("level"), common.Real("hp") is var hp && hp != 0 ? hp : null)
                { Attributes = Attributes(character) };
            squad[id] = member;
            entities[id] = new(id, obj, template, DisplayName(template));
            if (obj is { } objectId) { objectToBattle[objectId] = id; ids.Add(objectId); }
            ObserveOwner(owner, battle.Value!);
        }
        foreach (var old in previous.Where(old => !squad.ContainsKey(old)))
        {
            if (serverSkills.Remove(old, out var detached)) foreach (var skill in detached.Keys) skillOwners.Remove(skill);
        }
        sceneTeam = ids.ToArray();
        EmitSceneInfo(timestampMs, dungeon, message);
        foreach (var member in squad.Values)
            if (serverSkills.TryGetValue(member.Owner.BattleInstanceId, out var rows) && rows.Count > 0)
                EmitSkills("SC_SELF_SCENE_INFO_SKILLS", member.Owner.BattleInstanceId, null, rows.Values.Select(CloneRow), timestampMs);
        EmitLoadout("SC_SELF_SCENE_INFO", timestampMs);
    }

    private void UpdateEntities(ProtoMessage message, long timestampMs)
    {
        var detail = message.Child("detail");
        if (detail.Value is null) return;
        List<Dictionary<string, object?>> objects = [];
        foreach (var field in detail.Value.Descriptor.Fields.InFieldNumberOrder().Where(field => field.IsRepeated))
        foreach (var item in detail.Children(field.Name))
        {
            var common = item.Child("common_info");
            if (common.Value is null) continue;
            var battle = item.Child("battle_info");
            var id = battle.Number("battle_inst_id");
            if (id.IsZero) continue;
            var obj = common.Optional("id");
            var raw = common.Text("templateid");
            var template = raw.Length > 0 ? raw : null;
            SessionOwner owner = new(id, obj, template, DisplayName(template));
            entities[id] = owner;
            if (!squad.ContainsKey(id)) owners[id] = owner;
            if (obj is { } objectId) objectToBattle[objectId] = id;
            var kind = field.Name.EndsWith("_list", StringComparison.Ordinal) ? field.Name[..^5] : field.Name;
            objects.Add(new() { ["kind"] = kind.Length > 0 ? kind : "object", ["obj_id"] = obj, ["battle_inst_id"] = id,
                ["templateid"] = template, ["entity_type"] = common.Optional("type"), ["level"] = item.Optional("level"),
                ["hp"] = common.Real("hp"), ["attrs"] = Attributes(item) });
            if (MergeMultiPhaseEnemyBattles && TrackedEnemyTemplateId is not null && template == TrackedEnemyTemplateId) TrackedEnemyInstanceIds.Add(id);
            // Object refresh updates level evidence without replacing the server skill snapshot.
            Dictionary<string, BigInteger> levels = new(StringComparer.Ordinal);
            foreach (var skill in battle.Children("skill_list"))
                if (TemplateKey(ProtoMessage.Template(skill.Child("skill_id"))) is { } key) levels[key] = skill.Optional("level") ?? 1;
            if (levels.Count > 0) skillLevels[id] = levels;
            RefreshWeaponSkillEvidence(id, battle);
        }
        if (objects.Count > 0) Emit("SC_OBJECT_ENTER_VIEW", timestampMs, new() { ["objects"] = objects });
    }

    private void UpdateAttributes(ProtoMessage message, long timestampMs)
    {
        var obj = message.Number("obj_id");
        var attrs = Attributes(message);
        if (obj.IsZero || attrs.Count == 0) return;
        BigInteger? id = objectToBattle.TryGetValue(obj, out var mapped) ? mapped : entities.ContainsKey(obj) ? obj : null;
        var entity = id is { } key ? entities.GetValueOrDefault(key) : null;
        var member = id is { } owner ? squad.GetValueOrDefault(owner) : null;
        if (member is not null)
        {
            var merged = member.Attributes.ToDictionary(row => (BigInteger)row["attr_type"]!, CloneRow);
            foreach (var attr in attrs) merged[(BigInteger)attr["attr_type"]!] = CloneRow(attr);
            member.Attributes = merged.OrderBy(row => row.Key).Select(row => row.Value).ToList();
        }
        Emit("SC_SYNC_ATTR", timestampMs, new() { ["obj_id"] = obj, ["battle_inst_id"] = id,
            ["templateid"] = entity?.TemplateId ?? member?.Owner.TemplateId, ["attrs"] = attrs });
    }
}
