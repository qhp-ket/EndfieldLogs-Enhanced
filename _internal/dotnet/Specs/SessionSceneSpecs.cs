using System.Numerics;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Sessions;
using Google.Protobuf;

internal static class SessionSceneSpecs
{
    public static void Run(Action<bool, string> check)
    {
        List<BattleLogEvent> events = [];
        List<(string Reason, long Time, bool Force)> loadouts = [];
        GameSessionBusiness session = new("scene", events.Add, (reason, time, force) => loadouts.Add((reason, time, force)),
            names: new Dictionary<string, string> { ["chr_test"] = "测试角色" },
            multiPhaseDungeons: new Dictionary<string, string> { ["trial"] = "boss" }) { MergeMultiPhaseEnemyBattles = true };
        void Process(string name, string json, long time = 1000)
        {
            var message = JsonParser.Default.Parse(json, ProtocolCatalog.Messages[name]);
            if (!session.Process(new(name.StartsWith("CS_", StringComparison.Ordinal) ? "cs" : "sc", name, 1,
                new(), message, message.ToByteArray()), time)) throw new InvalidDataException("Unhandled maintained scene message: " + name);
        }
        Process("SC_SELF_SCENE_INFO", """
            {"detail":{"char_list":[{"common_info":{"id":"101","templateid":"chr_test"},
              "battle_info":{"battle_inst_id":"11","skill_list":[{"inst_id":"71","level":4,
                "skill_id":{"type":"Skill","int_id":42}}]},
              "attrs":[{"attr_type":2,"value":10}]}]},"team_info":{"cur_leader_id":"101"}}
            """);
        check(events.Select(row => row.EventType).SequenceEqual(["SC_SELF_SCENE_INFO", "SC_SELF_SCENE_INFO_SKILLS"])
            && loadouts.SequenceEqual([("SC_SELF_SCENE_INFO", 1000L, false)]),
            "Roster evidence precedes owned server skills and the loadout context request");
        var skillEvent = events[1];
        check(skillEvent.Payload["owner_obj_id"] is BigInteger obj && obj == 101
            && skillEvent.Payload["owner_display_name"] is "测试角色" && skillEvent.Payload["owner_squad_index"] is 0,
            "Server skill metadata follows the actual scene squad and resolved display name");
        check(events[0].Payload["scene_id"] is null, "An unset numeric scene identity remains absent in the external payload");
        ((BigInteger[])session.SceneTeam)[0] = 999;
        check(session.SceneTeam.SequenceEqual([new BigInteger(101)]), "Returned team order is owned independently of the session");
        var snapshot = session.ServerSkillSnapshot();
        ((Dictionary<string, object?>)snapshot[11][0])["level"] = -1;
        check(session.ServerSkills(11)[0]["level"] is BigInteger level && level == 4,
            "A complete server-skill snapshot cannot modify internal rows");
        Process("SC_SYNC_ATTR", """{"obj_id":"101","attr_list":[{"attr_type":2,"value":20},{"attr_type":1,"value":5}]}""");
        Process("CS_BATTLE_OP", """{"client_data":{"op_list":[{"op_type":"BattleOpModifyBattleState","modify_battle_state_op_data":{"is_in_battle":true}}]}}""");
        var scene = events.Last(row => row.EventType == "SC_SELF_SCENE_INFO");
        var members = (Dictionary<string, object?>[])scene.Payload["char_list"]!;
        var attributes = (Dictionary<string, object?>[])members[0]["attrs"]!;
        check(attributes.Select(row => (BigInteger)row["attr_type"]!).SequenceEqual([new BigInteger(1), new BigInteger(2)])
            && (double)attributes[1]["value"]! == 20 && loadouts[^1] == ("BATTLE_START", 1000L, true),
            "Battle start replays current merged attributes in canonical type order and forces loadout context");
        var before = events[0].Payload["char_list"] as Dictionary<string, object?>[];
        check(((Dictionary<string, object?>[])before![0]["attrs"]!)[0]["value"] is double original && original == 10,
            "Later attribute changes cannot rewrite a previously emitted scene snapshot");
        Process("SC_OBJECT_ENTER_VIEW", """
            {"detail":{"monster_list":[{"common_info":{"id":"707","templateid":"boss"},"battle_info":{"battle_inst_id":"77"}}]}}
            """);
        Process("CS_ENTER_DUNGEON", """{"dungeon_id":"trial","char_team":[{"obj_id":"101"}]}""");
        check(session.TrackedDungeonId == "trial" && session.TrackedEnemyInstanceIds.SetEquals([new BigInteger(77)])
            && session.DungeonTeam!.SequenceEqual([new BigInteger(101)]) && session.SceneTeam.Count == 0,
            "Dungeon entry binds known boss instances and explicit party order before the next scene snapshot");
        Process("CS_BATTLE_OP", """{"client_data":{"op_list":[{"op_type":"BattleOpModifyBattleState","modify_battle_state_op_data":{"is_in_battle":true}}]}}""");
        Process("CS_LEAVE_DUNGEON", "{}");
        check(!session.MergedBattleActive && session.TrackedDungeonId is null && session.DungeonTeam is null
            && session.TrackedEnemyInstanceIds.Count == 0 && events[^1].Payload["is_in_battle"] is false,
            "Leaving an active merged dungeon emits the final stop and clears its tracking state");
        Process("SC_OBJECT_LEAVE_VIEW", """{"obj_list":[{"obj_id":"101"}]}""");
        check(!session.ServerSkillSnapshot().ContainsKey(11), "Entity departure removes its owned server skills");
    }
}
