using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class AllocationPhaseCases
{
    internal static HitAllocator CreateAllocator(EvidenceObject config)
    {
        var roots = (config.Get("roots") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) ?? [];
        var names = config.Get("names") as EvidenceObject;
        AllocationDebug debug = new(key => string.IsNullOrEmpty(key) ? null : names?.Get(key) is EvidenceText name ? name.Value : key);
        AllocationContextBuilder context = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        AllocationExplanation explanation = new(debug, row => new(row, (row.Get("test_labels") as EvidenceArray)?.Items.Select(Text).ToArray() ?? []));
        return new(context, new(roots), new(roots), new(debug), new(debug), explanation);
    }
    private static EvidenceObject Object(EvidenceValue value) => (EvidenceObject)value;
    private static string Text(EvidenceValue value) => PythonDisplay.String(value);
    private static IReadOnlyList<EvidenceObject>? Rows(EvidenceValue value) => value is EvidenceNull ? null : ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    private static IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? Index(EvidenceValue value) => (value as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => Rows(pair.Value)!);
    private static Dictionary<BigInteger, EvidenceValue> Numeric(EvidenceValue value) => Object(value).Fields.ToDictionary(pair => BigInteger.Parse(pair.Key), pair => pair.Value);
    private static double Float(EvidenceValue value) => EffectIdentity.Float(value);
    private static object External(HitAllocation state) => state.ExternalByZone.ToDictionary(pair => pair.Key,
        pair => pair.Value.Select(row => new object?[] { row.Provider, row.Rate, row.Evidence }).ToArray());

    internal static HitAllocation Prepare(EvidenceObject config)
    {
        AllocationContextBuilder builder = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        var state = builder.Prepare(new(new ReportHitInput(Object(config.Get("hit")), Numeric(config.Get("numeric_baseline")), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>()),
            Rows(config.Get("windows"))!, Rows(config.Get("records")), ConditionsByUid: Index(config.Get("by_uid")),
            ConditionsByActor: Index(config.Get("by_actor")), WindowIndices: (config.Get("indices") as EvidenceArray)?.Items.Select(item => (int)((EvidenceInteger)item).Value).ToArray(),
            IncludeDebug: config.Get("debug") is EvidenceBoolean { Value: true }));
        foreach (var (key, value) in Object(config.Get("self")).Fields) state.SelfByZone[key] = Float(value);
        if (config.Get("self_factors") is EvidenceObject factors)
            foreach (var (key, value) in factors.Fields) state.SelfFactorByZone[key] = Float(value);
        foreach (var (key, value) in Object(config.Get("captured")).Fields) state.CapturedByAttribute[BigInteger.Parse(key)] = Float(value);
        foreach (var (key, value) in Object(config.Get("external")).Fields)
            state.ExternalByZone[key] = ((EvidenceArray)value).Items.Cast<EvidenceArray>().Select(row => new ExternalEffectContribution(Text(row.Items[0]), Float(row.Items[1]),
                row.Items[2] is EvidenceObject record ? (EvidenceObject)BuffEvidence.Clone(record) : null)).ToList();
        return state;
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = Object(EvidenceJson.Parse(test!["config_json"]!.GetValue<string>()));
            var before = EvidenceJsonSignature.Sorted(config);
            var names = Object(config.Get("names"));
            AllocationDebug debug = new(key => string.IsNullOrEmpty(key) ? null : names.Get(key) is EvidenceText name ? name.Value : key);
            var operation = Text(config.Get("operation"));
            object? result;
            try
            {
                if (operation.StartsWith("debug-", StringComparison.Ordinal))
                {
                    var hit = Object(config.Get("hit"));
                    var parameters = config.Get("parameters") as EvidenceObject;
                    result = operation switch
                    {
                        "debug-round" => AllocationDebug.Round4(config.Get("value")),
                        "debug-applicable" => debug.Applicable(Object(config.Get("window")), Object(config.Get("effect")), Text(config.Get("scope")),
                            config.Get("credit") is EvidenceNull ? null : Float(config.Get("credit"))),
                        "debug-baseline" => debug.Baseline(hit, EffectIdentity.Integer(parameters!.Get("attr_type")), Text(parameters.Get("zone")),
                            Text(parameters.Get("element")), Float(parameters.Get("rate")), Float(parameters.Get("final_value")), Float(parameters.Get("captured"))),
                        "debug-static" => debug.Static(hit, Object(config.Get("entry"))),
                        "debug-dpd" => debug.DpdResidual(hit, Text(config.Get("zone")), Float(config.Get("rate"))),
                        "debug-arts" => debug.ArtsProvenance(Object(config.Get("window")), Object(config.Get("effect")), Text(config.Get("source")),
                            Float(config.Get("rate")), config.Get("provenance") as EvidenceObject, Text(config.Get("scope"))),
                        "debug-rows" => debug.ContributionRows(Object(config.Get("contributions")).Fields.ToDictionary(pair => pair.Key, pair => Float(pair.Value)), config.Get("sort") is EvidenceBoolean { Value: true }),
                        "debug-zones" => debug.SortZones(Rows(config.Get("rows"))!),
                        _ => throw new InvalidDataException("Unknown debug operation"),
                    };
                }
                else if (operation == "allocate")
                {
                    var allocator = CreateAllocator(config);
                    var input = new AllocationEvidenceInput(new(Object(config.Get("hit")), Numeric(config.Get("numeric_baseline")), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>()),
                        Rows(config.Get("windows"))!, Rows(config.Get("records")), Index(config.Get("by_target")), Index(config.Get("by_uid")), Index(config.Get("by_actor")),
                        Index(config.Get("buff_records")), (config.Get("indices") as EvidenceArray)?.Items.Select(item => (int)((EvidenceInteger)item).Value).ToArray(),
                        config.Get("debug") is EvidenceBoolean { Value: true });
                    var allocated = allocator.Allocate(input);
                    result = new Dictionary<string, object?> { ["allocation"] = allocated.Allocation,
                        ["hit"] = new EvidenceObject(allocated.Hit.Fields.Where(pair => pair.Key != "baseline").ToDictionary()), ["windows"] = allocated.Windows };
                }
                else if (operation == "arts-attribution")
                {
                    var attributed = ArtsEffectAttribution.Attribute(Object(config.Get("window")), Object(config.Get("effect")), Rows(config.Get("windows"))!);
                    result = new Dictionary<string, object?> { ["sources"] = attributed.Sources.Select(row => new object?[] { row.Provider, row.Rate, row.Provenance }).ToArray(),
                        ["windows"] = attributed.Windows };
                }
                else
                {
                    var state = Prepare(config);
                    var roots = (config.Get("roots") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => Object(pair.Value)) ?? [];
                    if (operation is "resistance" or "baseline-connected" or "collect") state.SelectStackEffects(new(roots));
                    Dictionary<string, object?> projected;
                    if (operation == "collect")
                    {
                        new AllocationResistance(roots).Resolve(state);
                        new EffectContributorCollection(debug).Collect(state);
                        projected = new()
                        {
                            ["self"] = state.SelfByZone, ["self_factors"] = state.SelfFactorByZone, ["captured"] = state.CapturedByAttribute,
                            ["contributors"] = state.ContributorsByZone, ["ignored"] = state.IgnoredEffects, ["invalid"] = state.InvalidNumericAllocation,
                            ["windows"] = state.Windows,
                        };
                        if (config.Get("complete_phases") is EvidenceBoolean { Value: true })
                        {
                            AllocationBaselines baselines = new(debug);
                            baselines.AttachObserved(state);
                            baselines.ResolveAttack(state);
                            baselines.CheckRemaining(state);
                            AllocationMultipliers.Compute(state);
                            var allocation = LogMarginalAllocation.Allocate(state);
                            projected["invalid"] = state.InvalidNumericAllocation;
                            projected["multipliers"] = state.Multipliers;
                            projected["sums"] = state.ExternalSums;
                            projected["product"] = allocation.ProductExternal;
                            projected["attacker_share"] = allocation.AttackerShare;
                            projected["pool"] = allocation.ExternalPool;
                            projected["contributions"] = allocation.Contributions;
                        }
                        projected["external"] = External(state);
                    }
                    else if (operation == "multipliers")
                    {
                        state.ResistanceNumerator = config.Get("numerator") is EvidenceNull ? null : Float(config.Get("numerator"));
                        state.AttackBaselineError = (config.Get("attack_error") as EvidenceText)?.Value;
                        state.InvalidNumericAllocation = config.Get("invalid") is EvidenceBoolean { Value: true };
                        AllocationMultipliers.Compute(state);
                        var allocation = LogMarginalAllocation.Allocate(state);
                        projected = new()
                        {
                            ["multipliers"] = state.Multipliers, ["sums"] = state.ExternalSums, ["self"] = state.SelfByZone,
                            ["self_factors"] = state.SelfFactorByZone, ["external"] = External(state),
                            ["ignored"] = state.IgnoredEffects, ["invalid"] = state.InvalidNumericAllocation,
                            ["product"] = allocation.ProductExternal, ["attacker_share"] = allocation.AttackerShare,
                            ["pool"] = allocation.ExternalPool, ["contributions"] = allocation.Contributions,
                        };
                    }
                    else if (operation == "resistance")
                    {
                        new AllocationResistance(roots).Resolve(state);
                        projected = new()
                        {
                            ["effective"] = state.EffectiveResistance, ["numerator"] = state.ResistanceNumerator, ["source"] = state.ResistanceSource,
                            ["windows"] = state.Windows, ["effects"] = state.EffectsAtHit.ToDictionary(pair => pair.Key.ToString(), pair => pair.Value),
                            ["zones"] = state.UnresolvedStackZones.Order(PythonDisplay.CodePointComparer).ToArray(), ["ignored"] = state.IgnoredEffects,
                        };
                    }
                    else
                    {
                        AllocationBaselines baselines = new(debug);
                        if (operation is "observed" or "baseline-connected") baselines.AttachObserved(state);
                        if (operation is "attack" or "baseline-connected") baselines.ResolveAttack(state);
                        if (operation is "remaining" or "baseline-connected") baselines.CheckRemaining(state);
                        projected = new()
                        {
                            ["self"] = state.SelfByZone, ["contributors"] = state.ContributorsByZone, ["ignored"] = state.IgnoredEffects,
                            ["invalid"] = state.InvalidNumericAllocation, ["attack_error"] = state.AttackBaselineError,
                        };
                    }
                    projected["hit"] = new EvidenceObject(state.Hit.Fields.Where(pair => pair.Key != "baseline").ToDictionary());
                    result = projected;
                }
            }
            catch (Exception error) when (error is InvalidCastException or InvalidDataException or FormatException or OverflowException)
            {
                result = new Dictionary<string, object?> { ["error"] = error switch { InvalidCastException => "TypeError", InvalidDataException => "AttributeError", OverflowException => "OverflowError", _ => "ValueError" } };
            }
            var actual = FieldCases.Canonical(result);
            var expected = test["expected"]?.DeepClone();
            // This intermediate map has numeric attribute identity: Python False/True keys equal 0/1.
            // Preserve the frozen fixture and normalize only that numeric-key comparison boundary.
            // Original boolean evidence in hits, effects and explanation rows is still compared verbatim.
            if (expected is JsonObject projection && projection["captured"] is JsonObject captured)
                foreach (var (boolean, number) in new[] { ("False", "0"), ("True", "1") })
                    if (captured.Remove(boolean, out var value)) captured[number] = value;
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, expected) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Allocation phases differential: {results.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }
}
