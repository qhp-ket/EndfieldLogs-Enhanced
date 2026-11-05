using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class LoadoutStateCases
{
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));
    private static EvidenceObject Rows(IReadOnlyDictionary<string, EvidenceObject> rows) => new(rows.ToDictionary(pair => pair.Key, pair => (EvidenceValue)pair.Value, StringComparer.Ordinal));
    internal static EvidenceObject Snapshot(LoadoutObservations state) => Object(
        ("loadouts", Rows(state.Party.Loadouts)),
        ("groups", new EvidenceArray(state.Groups.Select(group => (EvidenceValue)Object(
            ("ts_ms", new EvidenceInteger(group.TimestampMs)), ("line_no", new EvidenceInteger(group.LineNumber)),
            ("reason", new EvidenceText(group.Reason)), ("index", new EvidenceInteger(group.Index)), ("rows", Rows(group.Rows)))).ToArray())),
        ("current_group", state.CurrentGroup is null ? EvidenceNull.Value : new EvidenceInteger(state.CurrentGroup.Index)),
        ("active_weapons", new EvidenceObject(state.Party.ActiveWeapons.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceText(pair.Value)))),
        ("active_suits", new EvidenceObject(state.Party.ActiveSuits.ToDictionary(pair => pair.Key,
            pair => (EvidenceValue)new EvidenceArray(pair.Value.Order(StringComparer.Ordinal).Select(value => (EvidenceValue)new EvidenceText(value)).ToArray())))),
        ("skills", new EvidenceObject(state.CharacterSkills.ToDictionary(pair => pair.Key,
            pair => (EvidenceValue)new EvidenceObject(pair.Value.ToDictionary(item => item.Key, item => (EvidenceValue)new EvidenceInteger(item.Value)))))));

    private static string Error(Exception error) => error switch
    {
        FormatException => "ValueError", OverflowException => "OverflowError", InvalidCastException => "TypeError",
        InvalidDataException => "AttributeError", _ => throw error,
    };

    private static EvidenceArray Stream(EvidenceObject input, EvidenceObject config)
    {
        Dictionary<string, EvidenceObject> Objects(EvidenceObject value, string key) => value.Get(key) is EvidenceObject obj
            ? obj.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal) : [];
        Dictionary<string, string> Strings(EvidenceObject value, string key) => value.Get(key) is EvidenceObject obj
            ? obj.Fields.ToDictionary(pair => pair.Key, pair => ((EvidenceText)pair.Value).Value, StringComparer.Ordinal) : [];
        var names = Strings(config, "names");
        SkillIdentityCatalog skills = new(Strings(config, "skills"), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
        LoadoutSnapshotParser parser = new(Objects(config, "weapons"), Objects(config, "equipment"), Objects(config, "suits"),
            new(Objects(config, "refinement")), skills, key => names.GetValueOrDefault(key));
        LoadoutObservations state = new(parser, skills, overrides: Objects(input, "overrides"));
        void Squad(EvidenceObject value)
        {
            state.SquadActorKeys.Clear();
            foreach (var pair in Strings(value, "squad")) state.SquadActorKeys[pair.Key] = pair.Value;
        }
        Squad(input);
        List<EvidenceValue> results = [];
        foreach (var value in ((EvidenceArray)input.Get("operations")).Items)
        {
            var row = (EvidenceObject)value;
            if (row.Fields.ContainsKey("squad")) Squad(row);
            var text = (row.Get("text") as EvidenceText)?.Value ?? "";
            var time = row.Get("time") is EvidenceInteger timestamp ? (long)timestamp.Value : 100;
            var line = row.Get("line") is EvidenceInteger number ? (int)number.Value : results.Count+1;
            EvidenceValue consumed = EvidenceNull.Value, error = EvidenceNull.Value;
            try { consumed = new EvidenceBoolean(state.Observe(text, line, time)); }
            catch (Exception exception) when (exception is FormatException or OverflowException or InvalidCastException or InvalidDataException)
            { error = new EvidenceText(Error(exception)); }
            results.Add(Object(("consumed", consumed), ("state", Snapshot(state)), ("error", error)));
        }
        return new(results);
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var input = EvidenceJson.Parse(test!["input_json"]!.GetValue<string>());
            var config = (EvidenceObject)EvidenceJson.Parse(test["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(input)+EvidenceJsonSignature.Sorted(config);
            var obj = input as EvidenceObject;
            JsonNode result;
            try
            {
                var value = test["kind"]!.GetValue<string>() switch
                {
                    "integer_set" => (EvidenceValue)new EvidenceArray(PythonIntegerSetOrder.Distinct(((EvidenceArray)input).Items
                        .Select(item => ((EvidenceInteger)item).Value)).Select(item => (EvidenceValue)new EvidenceInteger(item)).ToArray()),
                    "source_ids" => new EvidenceArray(LoadoutMerging.WeaponSourceSkillIds(obj!).Select(item => (EvidenceValue)new EvidenceInteger(item)).ToArray()),
                    "merge" => LoadoutMerging.Merge((EvidenceObject)obj!.Get("base"), (EvidenceObject)obj.Get("update")),
                    "equips" => LoadoutMerging.MergeEquipment((EvidenceArray)obj!.Get("base"), (EvidenceArray)obj.Get("update")),
                    "weapon" => LoadoutMerging.WithWeapon((EvidenceObject)obj!.Get("base"), (EvidenceObject)obj.Get("update")),
                    "tracked" => LoadoutMerging.MergeTracked(obj!.Get("base") as EvidenceObject, (EvidenceObject)obj.Get("update")),
                    "stream" => Stream(obj!, config),
                    _ => throw new InvalidDataException("Unknown loadout state case"),
                };
                result = new JsonObject { ["value"] = FieldCases.Canonical(value), ["error"] = null };
            }
            catch (Exception error) when (error is FormatException or InvalidCastException or OverflowException or InvalidDataException)
            { result = new JsonObject { ["value"] = null, ["error"] = Error(error) }; }
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = result,
                ["passed"] = JsonNode.DeepEquals(result, test["expected"])
                    && original == EvidenceJsonSignature.Sorted(input)+EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Loadout state differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
