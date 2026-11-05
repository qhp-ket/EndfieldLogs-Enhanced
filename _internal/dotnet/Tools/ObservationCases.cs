using System.Text.Json.Nodes;
using EndfieldLogs.Core.Ingestion;

internal static class ObservationCases
{
    private static Dictionary<string, object?> Snapshot(EntityStatsSnapshot row)
    {
        Dictionary<string, object?> value = new()
        {
            ["template"]=row.Template, ["kind"]=row.Kind, ["level"]=row.Level, ["attrs"]=row.Attributes,
            ["basic_attrs"]=row.BasicAttributes, ["ts_ms"]=row.TimestampMs,
            ["invalid_attr_types"]=row.InvalidAttributeTypes, ["invalid_attr_tokens"]=row.InvalidAttributeTokens,
            ["attribute_list_present"]=row.AttributeListPresent,
        };
        if (row.LineNumber is int line) value["line_no"] = line;
        return value;
    }

    private static object Cast(SkillCastObservation row)
    {
        Dictionary<string, object?> result = new()
        {
            ["ts_ms"]=row.TimestampMs, ["line_no"]=row.LineNumber, ["skill"]=row.Skill, ["owner"]=row.Owner,
            ["owner_id"]=row.OwnerId, ["skill_inst_id"]=row.SkillInstanceId, ["skill_source"]=row.SkillSource,
            ["source_character_key"]=row.CharacterKey, ["end_ts_ms"]=row.EndTimestampMs,
        };
        if (row.EndLineNumber is int line) result["end_line_no"] = line;
        return result;
    }

    internal static object Project(SkillObservationState state) => new Dictionary<string, object?>
    {
        ["atb_observations"]=state.AtbObservations.Select(row => new Dictionary<string, object?>
        {
            ["ts_ms"]=row.TimestampMs, ["line_no"]=row.LineNumber, ["character_key"]=row.CharacterKey,
            ["owner_actor_id"]=row.OwnerActorId, ["value"]=row.Value, ["delta"]=row.Delta,
            ["recovery_speed"]=row.RecoverySpeed, ["client_tick_ms"]=row.ClientTickMs, ["reason"]=row.Reason,
            ["source"]=row.Source, ["original_source"]=row.OriginalSource,
        }).ToArray(),
        ["atb_gain_ms_by_char"]=state.AtbGainMsByCharacter,
        ["skill_casts"]=state.Casts.Select(Cast).ToArray(),
        ["active_skill_casts_by_inst"]=state.ActiveCastsByInstance.ToDictionary(pair => pair.Key, pair => Cast(pair.Value)),
        ["recent_skill_casts_by_char"]=state.RecentCastsByCharacter.ToDictionary(pair => pair.Key, pair =>
            pair.Value.Select(row => new Dictionary<string, object?> { ["ts_ms"]=row.TimestampMs, ["skill"]=row.Skill,
                ["owner"]=row.Owner, ["skill_inst_id"]=row.SkillInstanceId, ["skill_source"]=row.SkillSource }).ToArray()),
        ["first_party_action_ms"]=state.FirstPartyActionMs,
    };

    internal static object Project(EntityObservationState state) => new Dictionary<string, object?>
    {
        ["entity_stats_timelines"]=state.Timelines.ToDictionary(pair => pair.Key,
            pair => pair.Value.Select(row => new object[] { row.TimestampMs, Snapshot(row.Snapshot) }).ToArray()),
        ["critical_stats_by_actor"]=state.CriticalAttributesByActor.ToDictionary(pair => pair.Key, pair =>
            new Dictionary<string, object?> { ["template"]=pair.Value.Template, ["values"]=pair.Value.Values,
                ["lines"]=pair.Value.Lines, ["times"]=pair.Value.Times }),
    };

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var kind = test!["kind"]!.GetValue<string>();
            object? result;
            if (kind == "identity")
            {
                var values = test["values"]!.AsArray().Select(value => value?.GetValue<string>()).ToArray();
                result = new Dictionary<string, object?> { ["character"]=ActorIdentity.CharacterKey(values),
                    ["enemy"]=ActorIdentity.EnemyKey(values), ["generic"]=ActorIdentity.IsGenericRuntimeSkill(values.FirstOrDefault()),
                    ["party_ids"]=ActorIdentity.PartyActorIds(test["line"]!.GetValue<string>()).Order(StringComparer.Ordinal).ToArray() };
            }
            else if (kind == "entity_parse")
            {
                var parsed = EntityStatsDecoder.Parse(test["line"]!.GetValue<string>());
                result = parsed is null ? null : new object[] { parsed.EntityId, Snapshot(parsed.Snapshot) };
            }
            else if (kind == "skills")
            {
                SkillObservationState state = new();
                JsonArray steps = [];
                foreach (var operation in test["operations"]!.AsArray())
                {
                    var handled = state.Observe(operation!["line"]!.GetValue<string>(), operation["number"]!.GetValue<int>(),
                        operation["time"]!.GetValue<long>());
                    steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["handled"]=handled, ["state"]=Project(state) }));
                }
                results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                    ["passed"]=JsonNode.DeepEquals(steps, test["expected"]), ["actual"]=steps });
                continue;
            }
            else if (kind == "entities")
            {
                EntityObservationState state = new();
                JsonArray steps = [];
                foreach (var operation in test["operations"]!.AsArray())
                {
                    var time = operation!["time"]!.GetValue<long>();
                    var handled = state.Observe(operation["line"]!.GetValue<string>(), operation["number"]!.GetValue<int>(), time);
                    var query = state.SnapshotAt(operation["query_id"]?.GetValue<string>(), operation["query_time"]?.GetValue<long>() ?? time);
                    steps.Add(FieldCases.Canonical(new Dictionary<string, object?> { ["handled"]=handled, ["state"]=Project(state),
                        ["query"]=query is null ? null : Snapshot(query) }));
                }
                results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                    ["passed"]=JsonNode.DeepEquals(steps, test["expected"]), ["actual"]=steps });
                continue;
            }
            else throw new InvalidDataException("Unknown observation case: "+kind);
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"]=test["name"]!.GetValue<string>(),
                ["passed"]=JsonNode.DeepEquals(actual, test["expected"]), ["actual"]=actual });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(item => !item!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Observation differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
