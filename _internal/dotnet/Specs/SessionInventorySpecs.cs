using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Sessions;
using Google.Protobuf;

internal static class SessionInventorySpecs
{
    public static void Run(Action<bool, string> check)
    {
        var directory = Path.Combine(Path.GetTempPath(), "endfield-inventory-" + Guid.NewGuid().ToString("N"));
        try
        {
            var weaponDir = Path.Combine(directory, "data/akedata/weapon/items");
            Directory.CreateDirectory(weaponDir);
            File.WriteAllText(Path.Combine(weaponDir, "wpn_test.json"), """
                {"weaponId":"wpn_test","baseAtk":[10,20.5],"skilllist":[{"skillName":"武器","blackboard":[{"key":"atk","value":[0.1,0.2]}]}]}
                """);
            LoadoutDisplayCatalog catalog = new(new ResourceFiles(directory));
            List<BattleLogEvent> events = [];
            GameSessionBusiness session = new("inventory", events.Add, loadoutCatalog: catalog);
            void Process(string name, string json)
            {
                var message = JsonParser.Default.Parse(json, ProtocolCatalog.Messages[name]);
                if (!session.Process(new("sc", name, 1, new(), message, message.ToByteArray()), 1000))
                    throw new InvalidDataException("Unhandled maintained inventory message: " + name);
            }
            const string bag = """
                {"char_info":[
                  {"objid":"101","templateid":"chr_a","weapon_id":"501","potential_level":2,"equip_col":{"0":"301"},
                   "battle_mgr_info":{"skill_list":[{"source":"Weapon","skill_id":{"type":"Skill","int_id":42},"level":3,"potential_lv":2}]}},
                  {"objid":"202","templateid":"chr_b","weapon_id":"502","potential_level":5,
                   "battle_mgr_info":{"skill_list":[{"source":"Weapon","skill_id":{"type":"Skill","int_id":84},"level":4,"potential_lv":5}]}}
                ],"team_info":[{"char_team":["101","202"]}]}
                """;
            Process("SC_SYNC_CHAR_BAG_INFO", bag);
            var initial = session.LoadoutSnapshot();
            Process("SC_SYNC_CHAR_BAG_INFO", bag);
            check(events.Count == 1 && events[0].EventType == "LOADOUT", "An identical complete character sync retains one loadout event");
            Process("SC_ITEM_BAG_SCOPE_SYNC", """
                {"bag":{"grids":[{"id":"wpn_test","inst":{"inst_id":"501","weapon":{"inst_id":"501","weapon_lv":2,"refine_lv":1}}}]}}
                """);
            var observed = session.LoadoutSnapshot()[0];
            check(observed["weapon_base_atk"] is double atk && atk == 20.5 && observed["weapon_sync_source"] is "WEAPON_DATA"
                && observed["weapon_base_atk_lv1"] is BigInteger lower && lower == 10,
                "Explicit weapon data selects the exact observed level and preserves numeric attack types");
            check(initial[0]["weapon_sync_source"] is "missing" && initial[0]["refine"] is null,
                "Later inventory packets cannot mutate a previously returned loadout snapshot");
            Process("SC_WEAPON_PUTON", """{"charid":"101","weaponid":"502","offweaponid":"501","put_off_charid":"202"}""");
            var swapped = session.LoadoutSnapshot();
            check((string)swapped[0]["weapon_source_skills"]! == "84:level=4:potentialLv=2:bb={}"
                && (string)swapped[1]["weapon_source_skills"]! == "42:level=3:potentialLv=5:bb={}",
                "Weapon source skill evidence follows the swapped instance while its potential follows the receiving character");
            Process("SC_WEAPON_ATTACH_GEM", """{"weaponid":"501","gemid":"601"}""");
            check(session.LoadoutSnapshot()[1]["weapon_source_skills"] is "" && session.LoadoutSnapshot()[1]["skill_int_ids"] is "",
                "A gem change invalidates old weapon skill totals and their integer identities");
            Process("SC_EQUIP_PUTON", """{"charid":"101","slotid":2,"equipid":"301"}""");
            check(session.LoadoutSnapshot()[0]["equip_inst_ids"] is "{[2]=301}", "Moving an equipment instance replaces its old slot within the same character");
            Process("SC_CHAR_BAG_SET_TEAM", """{"char_team":["202","101"]}""");
            check(session.LoadoutSnapshot()[0]["char"] is "chr_b", "Explicit team changes preserve the selected party order");
            Process("CS_BATTLE_OP", """{"client_data":{"op_list":[{"op_type":"BattleOpModifyBattleState","modify_battle_state_op_data":{"is_in_battle":true}}]}}""");
            check(events[^1].EventType == "LOADOUT" && events[^1].Payload["reason"] is "BATTLE_START",
                "Battle entry republishes complete loadout context even if its values are unchanged");
        }
        finally { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
    }
}
