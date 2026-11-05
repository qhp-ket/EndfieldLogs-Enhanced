using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class AttackDependenceSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Hit(EvidenceValue calculation) => new(new Dictionary<string, EvidenceValue> { ["damage_calculation"] = calculation });
    private static SkillDamageUnit Unit(EvidenceObject? calculation, string attribute = "hp") =>
        new(new EvidenceInteger(0), "fire", attribute, null, null, calculation);

    public static void Run(Action<bool, string> check)
    {
        var linear = Obj("""{"source":"current_typed_damage_unit","simpleCalculation":false,"atkCalculation":{"$type":"Beyond.Gameplay.Core.AtkScaleCalculation"}}""");
        var independent = Obj("""{"source":"current_typed_damage_unit","simpleCalculation":false,"atkCalculation":{"$type":"Beyond.Gameplay.Core.DefiniteValueCalculation"}}""");
        var affine = Obj("""{"source":"current_typed_damage_unit","simpleCalculation":false,"atkCalculation":{"$type":"Beyond.Gameplay.Core.MultiplyAttributeCalculation","attributeType":"Atk","valueSource":"AttackerOrHealer"}}""");
        IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> units = new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> { [0] = new[] { Unit(independent) } };
        var calls = 0;
        AttackDependenceClassifier classifier = new(_ => { calls++; return units; });
        check(classifier.Classify(Obj("{}")) is { Kind: AttackDependence.Linear, Calculation: EvidenceNull } && calls == 0,
            "Legacy hits missing the calculation field remain linear without consulting resources");
        check(classifier.Classify(Hit(Obj("{}"))).Kind == AttackDependence.Unknown && calls == 0,
            "An explicitly empty calculation is exact unknown evidence and suppresses resource fallback");
        check(classifier.Classify(Hit(EvidenceNull.Value)).Kind == AttackDependence.Independent && calls == 1,
            "A present null calculation uses matching HP unit evidence");
        check(classifier.Classify(Hit(linear)).Kind == AttackDependence.Linear && classifier.Classify(Hit(independent)).Kind == AttackDependence.Independent,
            "Current typed attack-scale and definite-value calculations classify independently of resource fallback");
        var result = classifier.Classify(Hit(affine));
        check(result.Kind == AttackDependence.Affine && ReferenceEquals(result.Calculation, affine) && result.EvidenceKind == "affine",
            "Exact affine evidence retains its own blackboard parameters and public spelling");
        units = new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> { [0] = new[] { Unit(affine) } };
        check(classifier.Classify(Hit(EvidenceNull.Value)).Kind == AttackDependence.Unknown,
            "A template-only affine unit cannot supply hit-specific blackboard parameters");
        units = new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> { [0] = new[] { Unit(linear), Unit(independent) } };
        check(classifier.Classify(Hit(EvidenceNull.Value)).Kind == AttackDependence.Unknown,
            "Disagreeing HP unit dependencies stay unknown");
        units = new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> { [0] = new[] { Unit(linear), Unit(independent, "poise"), Unit(null) } };
        check(classifier.Classify(Hit(EvidenceNull.Value)).Kind == AttackDependence.Linear,
            "Non-HP and missing calculations do not vote in fallback consensus");
        check(classifier.Classify(Hit(Obj("""{"source":"current_typed_damage_unit","simpleCalculation":true,"atkCalculation":{"$type":"Beyond.Gameplay.Core.DefiniteValueCalculation"}}"""))).Kind == AttackDependence.Linear
            && classifier.Classify(Hit(Obj("""{"source":"current_typed_damage_unit","simpleCalculation":1}"""))).Kind == AttackDependence.Unknown,
            "Only an actual boolean simple flag is authoritative and overrides dormant custom mode");
        check(classifier.Classify(Hit(Obj("""{"source":"other","simpleCalculation":true}"""))).Kind == AttackDependence.Unknown,
            "Unproven calculation provenance cannot establish attack dependence");
        try
        {
            classifier.Classify(Hit(Obj("""{"source":"current_typed_damage_unit","simpleCalculation":true,"atkCalculation":"invalid"}""")));
            throw new InvalidOperationException("Malformed dormant calculation accepted");
        }
        catch (InvalidDataException) { check(true, "Malformed dormant custom evidence preserves the reference failure boundary"); }
        var before = EvidenceJsonSignature.Sorted(affine);
        classifier.Classify(Hit(affine));
        check(before == EvidenceJsonSignature.Sorted(affine) && affine.Get("attack_damage_dependency") is EvidenceNull,
            "Classification does not mutate caller evidence or template caches");
        var root = Path.Combine(Path.GetTempPath(), "endfield-attack-resources-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var resources = BattleIngestionResources.Load(new ResourceFiles(root));
            var production = new AttackDependenceClassifier(resources.DamageUnits);
            check(production.Classify(Obj("""{"skill_key":"unknown","damage_calculation":null}""")) is { Kind: AttackDependence.Unknown },
                "The production ingestion resource delegate preserves missing resource uncertainty");
        }
        finally { Directory.Delete(root, true); }
    }
}
