using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectRegistryCases
{
    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var original = EvidenceJsonSignature.Sorted(config);
            var record = config.Get("record") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            var entry = config.Get("entry") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
            object? result;
            try
            {
                switch (test["kind"]!.GetValue<string>())
                {
                    case "rate":
                        var rate = EffectRegistryRules.RuntimeRate((EvidenceObject)config.Get("spec"), record);
                        result = new Dictionary<string, object?> { ["record"] = rate.Record, ["result"] = new object?[] { rate.Rate, rate.BlackboardKey } };
                        break;
                    case "zones":
                        var zones = EffectRegistryRules.ZoneEffects(record, entry);
                        result = new Dictionary<string, object?> { ["record"] = zones.Record, ["result"] = zones.Effects };
                        break;
                    case "validate":
                        var validation = EffectRegistryRules.Validate(entry, record);
                        result = new Dictionary<string, object?> { ["record"] = validation.Record, ["result"] = validation.Error };
                        break;
                    case "ignored": result = EffectRegistryRules.IgnoredBlackboardKeys(entry).Order(PythonDisplay.CodePointComparer).ToArray(); break;
                    case "unknown": result = EffectRegistryRules.UnknownBlackboardKeys(entry, record); break;
                    case "classify":
                        var roots = (EvidenceObject)config.Get("roots");
                        EffectStructureCatalog catalog = new(roots.Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value));
                        result = catalog.Classify(record);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(result), FieldCases.Canonical(catalog.Classify(record))))
                            throw new InvalidOperationException("Classification cache changed its result");
                        break;
                    case "zone-config": result = DamageZoneCatalog.Project(config.Get("payload") is EvidenceNull ? null : config.Get("payload")); break;
                    case "damage-zone":
                    case "condition":
                    case "semantic":
                    case "specification":
                    case "dynamic-specification":
                        var semanticRoots = config.Get("roots") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
                        var typed = semanticRoots.Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value);
                        var zoneConfig = config.Get("zones") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>());
                        var numbers = (config.Get("numbers") as EvidenceObject)?.Fields.ToDictionary(pair => pair.Key, pair => CatalogValuesText(pair.Value)) ?? [];
                        EffectApproval approval = new(config.Get("registry") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>()), typed,
                            numbers, new Dictionary<string, string>());
                        SemanticEffectCatalog semantics = new(typed, zoneConfig.Fields.Where(pair => pair.Value is EvidenceObject).ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value), approval);
                        var kind = test["kind"]!.GetValue<string>();
                        if (kind == "damage-zone")
                        {
                            var zone = semantics.DamageZone((EvidenceObject)config.Get("effect"));
                            result = zone is null ? null : new[] { zone.Value.Zone, zone.Value.Element };
                        }
                        else if (kind == "condition") result = semantics.DamageCondition("buff", (EvidenceObject)config.Get("effect"),
                            config.Get("bb_values") as EvidenceObject ?? new EvidenceObject(new Dictionary<string, EvidenceValue>()));
                        else
                        {
                            EffectSpecificationCatalog composition = new(approval, semantics, new(typed));
                            var mappings = (config.Get("mappings") as EvidenceObject)?.Fields.Where(pair => pair.Value is EvidenceObject)
                                .ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value) ?? [];
                            var mechanisms = (config.Get("mechanisms") as EvidenceObject)?.Fields.Where(pair => pair.Value is EvidenceArray)
                                .ToDictionary(pair => pair.Key, pair => (IReadOnlyList<EvidenceObject>)((EvidenceArray)pair.Value).Items.OfType<EvidenceObject>().ToArray()) ?? [];
                            var semantic = kind switch
                            {
                                "specification" => composition.CollectStatic(record),
                                "dynamic-specification" => new DynamicEffectSpecificationCatalog(approval, composition, typed,
                                    new(mappings, mechanisms, numbers)).Collect(record),
                                _ => semantics.Collect(record),
                            };
                            result = new Dictionary<string, object?> { ["record"] = semantic.Record, ["result"] = semantic.Effects };
                        }
                        break;
                    default: throw new InvalidOperationException("Unknown effect registry case");
                }
            }
            catch (Exception error) when (error is InvalidCastException or InvalidOperationException or FormatException or OverflowException or InvalidDataException)
            {
                result = new Dictionary<string, object?> { ["error"] = error is OverflowException ? "OverflowError" : error is FormatException ? "ValueError" : error is InvalidDataException ? "AttributeError" : "TypeError" };
            }
            var actual = FieldCases.Canonical(result);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && original == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Effect registry differential: {cases.Count} cases, {failed} differences");
        return failed == 0 ? 0 : 1;
    }

    private static string CatalogValuesText(EvidenceValue value) => value is EvidenceText text ? text.Value : throw new InvalidDataException("Expected a number mapping string");
}
