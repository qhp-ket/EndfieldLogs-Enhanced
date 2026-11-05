using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class BattleIngestionCases
{
    private static object Project(BattleIngestionStream state) => new Dictionary<string, object?>
    {
        ["context"] = new Dictionary<string, object?>
        {
            ["origin"] = state.TimestampClockOrigin, ["first"] = state.FirstContextMs, ["last"] = state.LastContextMs,
            ["timer_times"] = state.TimerObservedTimes, ["party_ids"] = state.PartyActorIds.Order(StringComparer.Ordinal).ToArray(),
            ["squad"] = state.Loadouts.SquadActorKeys,
        },
        ["timers"] = TimerCases.Project(state.Timers),
        ["skills"] = ObservationCases.Project(state.Skills),
        ["entities"] = ObservationCases.Project(state.Entities),
        ["loadouts"] = LoadoutStateCases.Snapshot(state.Loadouts),
        ["hits"] = HitObservationCases.Project(state.Hits, state.Packets, state.Buffs),
        ["poise"] = ((Dictionary<string, object?>)PacketEvidenceCases.Project(state.Packets))["poise_damage_events"],
        ["dynamics"] = state.Buffs.DynamicEvents.Select(row => row.Evidence).ToArray(),
        ["refreshes"] = state.Buffs.AttributeRefreshEvents.Select(row => row.Evidence).ToArray(),
    };

    private static BattleIngestionResources Resources(EvidenceObject config)
    {
        Dictionary<string, EvidenceObject> Objects(string key) => config.Get(key) is EvidenceObject obj
            ? obj.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal) : [];
        Dictionary<string, string> Strings(string key) => config.Get(key) is EvidenceObject obj
            ? obj.Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal) : [];
        var names = Strings("names");
        var buffs = Strings("buffs");
        SkillIdentityCatalog identities = new(Strings("skills"), buffs, new Dictionary<string, RuntimeBuffDamageProfile>());
        return new()
        {
            Identities = identities,
            BuffMappings = new(Objects("numeric"), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), buffs),
            BuffNumbers = buffs, BuffRoots = Objects("roots"),
            Loadouts = new(Objects("weapons"), Objects("equipment"), Objects("suits"), new(Objects("refinement")), identities, key => names.GetValueOrDefault(key)),
            CharacterName = key => names.GetValueOrDefault(key), EnemyName = key => names.GetValueOrDefault(key),
            SkillName = key => names.GetValueOrDefault(key), Dungeon = _ => null,
            DamageUnits = _ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>(), SkillProfile = _ => null,
            Metadata = _ => new("", "", "", new Dictionary<BigInteger, string>(), false),
        };
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = test!["config_json"] is JsonNode configNode ? (EvidenceObject)EvidenceJson.Parse(configNode.GetValue<string>()) : null;
            var original = config is null ? null : EvidenceJsonSignature.Sorted(config);
            using var files = config is null ? new ResourceFixture(test) : null;
            BattleIngestionStream state = new(config is null ? BattleIngestionResources.Load(files!.Files) : Resources(config));
            JsonArray steps = [];
            foreach (var batch in test["batches"]!.AsArray())
            {
                state.Accept(batch!.AsArray().Select(row => (row!["number"]!.GetValue<int>(), row["text"]!.GetValue<string>())));
                steps.Add(FieldCases.Canonical(Project(state)));
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = steps,
                ["passed"] = JsonNode.DeepEquals(steps, test["expected"])
                    && (config is null || original == EvidenceJsonSignature.Sorted(config)) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Battle ingestion differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
