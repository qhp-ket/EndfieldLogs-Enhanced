using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Protocol;
using EndfieldLogs.Runtime.Sessions;

internal static class SessionBusinessCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray outcomes = [];
        Dictionary<string, LoadoutDisplayCatalog> catalogs = new(StringComparer.OrdinalIgnoreCase);
        foreach (var test in cases)
        {
            var config = JsonNode.Parse(test!["config_json"]!.GetValue<string>())!;
            List<BattleLogEvent> events = [];
            static Dictionary<string, string>? TextMap(JsonNode? node) => node?.AsObject()
                .ToDictionary(pair => pair.Key, pair => pair.Value!.GetValue<string>(), StringComparer.Ordinal);
            LoadoutDisplayCatalog? display = null;
            if (config["resource_root"] is JsonValue root)
            {
                var directory = root.GetValue<string>();
                if (!catalogs.TryGetValue(directory, out display)) catalogs[directory] = display = new(new ResourceFiles(directory));
            }
            GameSessionBusiness session = new("synthetic", events.Add,
                names: TextMap(config["names"]), multiPhaseDungeons: TextMap(config["dungeons"]),
                loadoutCatalog: display)
            {
                MergeMultiPhaseEnemyBattles = config["merge"]!.GetValue<bool>(),
                TrackedEnemyTemplateId = config["merge"]!.GetValue<bool>() ? "enemy" : null,
            };
            foreach (var id in config["tracked"]!.AsArray()) session.TrackedEnemyInstanceIds.Add(id!.GetValue<long>());
            foreach (var owner in config["owners"]!.AsArray())
            {
                var id = BigInteger.Parse(owner!["owner"]!.GetValue<string>(), CultureInfo.InvariantCulture);
                session.ObserveOwner(new(id, id + 1000, "chr_test", "测试角色", 0),
                    ProtocolCatalog.Parse(owner["battle_type"]!.GetValue<string>(), Convert.FromHexString(owner["battle_hex"]!.GetValue<string>())));
            }
            JsonArray actual = [];
            foreach (var step in config["steps"]!.AsArray())
            {
                var name = step!["name"]!.GetValue<string>();
                var bytes = Convert.FromHexString(step["bytes"]!.GetValue<string>());
                session.Process(new(step["direction"]!.GetValue<string>(), name, step["message_id"]!.GetValue<int>(),
                    new SessionHead(), ProtocolCatalog.Parse(name, bytes), bytes), step["timestamp_ms"]!.GetValue<long>());
                JsonObject skills = [];
                foreach (var (id, rows) in session.ServerSkillSnapshot())
                    skills[id.ToString(CultureInfo.InvariantCulture)] = FieldCases.Canonical(rows);
                JsonObject state = new() { ["events"] = FieldCases.Canonical(events.Select(row => row.ToPayload()).ToArray()),
                    ["skills"] = skills, ["merged"] = session.MergedBattleActive,
                    ["tracked"] = new JsonArray(session.TrackedEnemyInstanceIds.Order().Select(id => JsonValue.Create((ulong)id)).ToArray()) };
                if (config["scene_state"]?.GetValue<bool>() == true)
                {
                    state["scene_team"] = FieldCases.Canonical(session.SceneTeam);
                    state["dungeon_team"] = FieldCases.Canonical(session.DungeonTeam);
                    state["tracked_dungeon"] = session.TrackedDungeonId;
                }
                if (config["inventory_state"]?.GetValue<bool>() == true) state["loadout"] = FieldCases.Canonical(session.LoadoutSnapshot());
                actual.Add(state);
            }
            outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Session business differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
