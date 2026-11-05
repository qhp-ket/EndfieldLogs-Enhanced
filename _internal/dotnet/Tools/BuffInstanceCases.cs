using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class BuffInstanceCases
{
    private static EvidenceObject Object(JsonNode? node) => (EvidenceObject)EvidenceJson.Parse(node?.ToJsonString() ?? "{}");
    private static Dictionary<string, EvidenceObject> Objects(EvidenceObject obj) => obj.Fields
        .Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal);
    private static Dictionary<string, string> Strings(EvidenceObject obj) => obj.Fields
        .ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal);

    // Python object_pairs_hook leaves unconsumed nested objects as ordered lists of pairs.
    private static EvidenceValue Hook(EvidenceValue value) => value switch
    {
        EvidenceObject { SourcePairs: { } pairs } => new EvidenceArray(pairs.Select(pair => (EvidenceValue)new EvidenceArray([new EvidenceText(pair.Key), Hook(pair.Value)])).ToArray()),
        EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => Hook(pair.Value), StringComparer.Ordinal)),
        EvidenceArray array => new EvidenceArray(array.Items.Select(Hook).ToArray()),
        _ => value,
    };

    private static object[] Rows(IEnumerable<BuffObservation> rows) => rows.Select(row => (object)Hook(row.Evidence)).ToArray();
    private static object Mod(BuffAttributeModifier row) => new Dictionary<string, object?>
    {
        ["attr_type"] = row.AttributeType, ["bb_key"] = row.BlackboardKey, ["use_key"] = row.UseKey, ["value"] = row.Value,
    };

    internal static EvidenceObject RecordFields(BuffRecord row)=>BuffReportEvidence.Project(row);

    private static object? Dynamic(BuffDynamicState? state) => state is null ? null : new Dictionary<string, object?>
    {
        ["context"] = new object[] { state.Context.SessionId, state.Context.OwnerId, state.Context.Generation },
        ["values"] = state.Values, ["value_sources"] = state.ValueSources, ["last_seq"] = state.LastSequence,
        ["operations"] = state.Operations.ToDictionary(pair => pair.Key.ToString(), pair => new object?[]
            { pair.Value.ActionType, pair.Value.ActionId, pair.Value.Key, pair.Value.Value, pair.Value.Identity }),
        ["invalid_keys"] = state.InvalidKeys.Order(StringComparer.Ordinal).ToArray(),
    };

    private static object? Legacy(BuffResistanceState? state) => state is null ? null : new Dictionary<string, object?>
    {
        ["values"] = state.Values, ["seen"] = state.Seen.ToDictionary(pair => pair.Key.ToString(),
            pair => new object?[] { pair.Value.Action, pair.Value.Key, pair.Value.Value }),
        ["last_seq"] = state.LastSequence, ["invalid"] = state.Invalid.Order(StringComparer.Ordinal).ToArray(),
    };

    private static object? KeywordUpdates(BuffRecord row) => row.KeywordSeenUpdates?.ToDictionary(pair => pair.Key.ToString(),
        pair => new object[] { pair.Value.Generation, pair.Value.AddedBuff, pair.Value.Rows });

    internal static JsonNode? Snapshot(BuffInstanceState state)
    {
        int? Index(BuffRecord? row) => row is null || state.Records.IndexOf(row) < 0 ? null : state.Records.IndexOf(row);
        return FieldCases.Canonical(new Dictionary<string, object?>
        {
            ["records"] = state.Records.Select(row =>
            {
                Dictionary<string, object?> fields = new()
                {
                    ["fields"] = RecordFields(row), ["observed"] = row.ObservedBlackboardValues,
                    ["invalid"] = row.DynamicUnresolvedKeys.Order(StringComparer.Ordinal).ToArray(), ["dynamic"] = Dynamic(row.DynamicState), ["legacy"] = Legacy(row.ResistanceState),
                    ["previous"] = Index(row.PreviousSnapshot), ["ends"] = new long[] { -1, 100, 1000, 10000 }.Select(end => state.EndAt(row, end)).ToArray(),
                };
                if (row.KeywordSeenUpdates is not null) fields["keyword_updates"] = KeywordUpdates(row);
                return fields;
            }).ToArray(),
            ["active"] = state.ActiveByUid.ToDictionary(pair => pair.Key, pair => Index(pair.Value)), ["pending"] = Index(state.PendingRecord),
            ["roster"] = state.Roster, ["numeric"] = state.RecentNumericBySource.ToDictionary(pair => pair.Key, pair => pair.Value.Select(Index).ToArray()),
            ["unresolved"] = Rows(state.UnresolvedActions),
            ["dynamic_events"] = Rows(state.DynamicEvents), ["refresh_events"] = Rows(state.AttributeRefreshEvents),
            ["history"] = state.CreationHistory.Select(pair => new Dictionary<string, object?>
            {
                ["key"] = new object[] { pair.Key.Context.SessionId, pair.Key.Context.OwnerId, pair.Key.Context.Generation, pair.Key.Sequence, pair.Key.Uid },
                ["record"] = Index(pair.Value.Record), ["observation"] = Hook(pair.Value.Observation.Evidence), ["instance"] = pair.Value.InstanceStartLineNumber,
            }).ToArray(),
            ["pending_modifiers"] = state.PendingModifiers.ToDictionary(pair => pair.Key, pair => pair.Value.Select(Mod).ToArray()),
            ["shared_enable"] = state.Records.Select(left => state.Records.Select(right => ReferenceEquals(left.EnableObservations, right.EnableObservations)).ToArray()).ToArray(),
            ["shared_refresh"] = state.Records.Select(left => state.Records.Select(right => ReferenceEquals(left.AttributeRefreshSnapshots, right.AttributeRefreshSnapshots)).ToArray()).ToArray(),
        });
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = test!["config_json"] is JsonNode rawConfig ? (EvidenceObject)EvidenceJson.Parse(rawConfig.GetValue<string>()) : Object(test["config"]);
            EvidenceObject Section(string key) => config.Get(key) as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            var numeric = Objects(Section("numeric"));
            var roots = Objects(Section("roots"));
            var numbers = Strings(Section("numbers"));
            var mechanisms = Section("mechanisms").Fields.ToDictionary(pair => pair.Key,
                pair => (IReadOnlyList<EvidenceObject>)((EvidenceArray)pair.Value).Items.OfType<EvidenceObject>().ToArray(), StringComparer.Ordinal);
            var names = Strings(Section("names"));
            string? Name(string? key) => key is null ? null : names.GetValueOrDefault(key);
            var state = new BuffInstanceState(new(numeric, mechanisms, numbers), roots, numbers, Name, Name);
            LiveBuffProjectionCache projections = new();
            EvidenceObject[] previousProjections = projections.Capture(state);
            var previousJson = FieldCases.Canonical(previousProjections)?.ToJsonString();
            var projectionMatches = true;
            void CheckProjections()
            {
                projectionMatches &= FieldCases.Canonical(previousProjections)?.ToJsonString() == previousJson;
                previousProjections = projections.Capture(state);
                var actual = FieldCases.Canonical(previousProjections);
                projectionMatches &= JsonNode.DeepEquals(actual, FieldCases.Canonical(state.Records.Select(BuffReportEvidence.Project).ToArray()));
                previousJson = actual?.ToJsonString();
            }
            foreach (var (key, value) in Strings(Section("weapons"))) state.ActiveWeapons[key] = value;
            foreach (var (key, value) in Section("suits").Fields)
                state.ActiveSuits[key] = ((EvidenceArray)value).Items.OfType<EvidenceText>().Select(item => item.Value).ToHashSet(StringComparer.Ordinal);
            var approval = new EffectApproval(Section("registry"), roots, numbers, Strings(Section("skills")), state.ActionIndices);
            var observations = new BuffPacketObservations(state, row => config.Get("use_approval") is EvidenceBoolean { Value: true }
                ? approval.Match(row) : config.Get("approval") as EvidenceObject);
            var metadata = Section("skill_metadata");
            var dynamicObservations = new BuffDynamicObservations(state, key => new("", "", "", metadata.Get(key) is EvidenceObject mapping
                ? mapping.Fields.ToDictionary(pair => BigInteger.Parse(pair.Key), pair => ((EvidenceText)pair.Value).Value) : new Dictionary<BigInteger, string>()));
            JsonArray steps = [];
            foreach (var item in test["events"]!.AsArray())
            {
                string? error = null;
                try
                {
                    if (item!["seed"] is JsonNode seed)
                    {
                        Seed(state, seed);
                        CheckProjections();
                        steps.Add(new JsonObject { ["error"] = null, ["state"] = Snapshot(state) });
                        continue;
                    }
                    var line = item!["text"]!.GetValue<string>();
                    var number = item["line"]!.GetValue<int>();
                    var time = item["ts"]!.GetValue<long>();
                    if (!observations.Observe(line, number, time) && !dynamicObservations.Observe(line, number, time) && !state.ObserveBlackboard(line)) state.ObserveLifecycle(line, number, time);
                }
                catch (FormatException) { error = "ValueError"; }
                catch (OverflowException) { error = "OverflowError"; }
                catch (InvalidDataException failure) when (failure.Message == "legacy_dynamic_observation_not_object") { error = "AttributeError"; }
                CheckProjections();
                steps.Add(new JsonObject { ["error"] = error, ["state"] = Snapshot(state) });
            }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = steps,
                ["projection_matches_every_step"] = projectionMatches,
                ["passed"] = projectionMatches && JsonNode.DeepEquals(steps, test["expected"]) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"BUFF instance differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }

    private static void Seed(BuffInstanceState state, JsonNode seed)
    {
        var record = state.ActiveByUid[seed["uid"]!.GetValue<string>()];
        state.MarkProjectionChanged(record);
        if (seed["_dynamic_pending_state"] is JsonObject pending)
        {
            var context = pending["context"]!.AsArray();
            var dynamic = new BuffDynamicState(new(context[0]!.GetValue<string>(), context[1]!.GetValue<string>(),
                EvidenceJson.Parse(context[2]?.ToJsonString() ?? "null"))) { LastSequence = pending["last_seq"]!.GetValue<int>() };
            foreach (var (key, value) in pending["values"]!.AsObject()) dynamic.Values[key] = value!.GetValue<double>();
            foreach (var (key, value) in Object(pending["value_sources"]).Fields) dynamic.ValueSources[key] = value;
            foreach (var value in pending["invalid_keys"]!.AsArray()) dynamic.InvalidKeys.Add(value!.GetValue<string>());
            if (pending["operations"]!.AsObject().Count > 0) throw new InvalidDataException("Fixtures seed pending operations through events");
            record.DynamicState = dynamic;
        }
        if (seed["_dynamic_unresolved_keys"] is JsonArray invalid)
            foreach (var value in invalid) record.DynamicUnresolvedKeys.Add(value!.GetValue<string>());
        if (seed["attribute_refresh_snapshots"] is JsonArray snapshots)
            record.AttributeRefreshSnapshots = snapshots.Select(value => new BuffObservation(Object(value))).ToList();
    }
}
