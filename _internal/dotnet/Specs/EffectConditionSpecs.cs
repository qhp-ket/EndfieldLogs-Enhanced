using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectConditionSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        var root = Obj("""{"damageModifier":[{"condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[{"isEnable":true,"$type":"CheckDamageType","damageType":"Fire"}]}}]}""");
        ModifierConditionCatalog first = new(new Dictionary<string, EvidenceObject> { ["a"] = root });
        ModifierConditionCatalog second = new(new Dictionary<string, EvidenceObject> { ["a"] = Obj("{}") });
        var observed = first.For("a");
        check(observed.Count == 1 && second.For("a").Count == 0, "Condition caches belong to their own resource catalogs");
        check(ReferenceEquals(observed, first.For("a")), "Repeated condition lookup reuses its decoded rows");
        for (var index = 0; index < 5000; index++) first.For("missing-" + index);
        check(first.CachedCount == 4096 && !ReferenceEquals(observed, first.For("a")) && first.CachedCount == 4096,
            "Condition cache bounds unknown templates and evicts least recently used rows");
        var tasks = Enumerable.Range(0, 32).Select(_ => Task.Run(() => first.For("a"))).ToArray();
        Task.WaitAll(tasks);
        check(tasks.All(task => ReferenceEquals(task.Result, first.For("a"))), "Concurrent condition lookups share one complete result");
        var effect = Obj("""{"element":"physical"}""");
        var attached = EffectConditions.AttachBlackboardCondition(effect, "physical_res_down");
        check(!effect.Fields.ContainsKey("condition") && attached.Get("condition") is EvidenceObject,
            "Derived blackboard guard leaves source declaration unchanged");
        var required = Obj("""{"condition":{"type":"damage_decorate_mask","mask":4,"check":"HasAll"}}""");
        var staticHit = Obj("""{"static_damage_decorate_mask":4,"static_damage_decorate_mask_source":"current_typed_skill_or_buff_exact_unit_generation_only"}""");
        var absentHit = Obj("""{"static_damage_decorate_mask":0,"static_damage_decorate_mask_source":"current_typed_skill_or_buff_exact_unit_generation_only"}""");
        check(EffectConditions.Failure(required, staticHit) is null
            && EffectConditions.Failure(required, absentHit)?.Get("reason_group") is EvidenceText { Value: "condition_unobservable" },
            "Static generation proves known positive categories without proving absent runtime bits");
        var window = Obj("""{"start_ts_ms":1000,"end_ts_ms":2000,"requires_enable_observation":true,"zone_effects":[{"zone":"amp","rate":0.2}]}""");
        var before = EvidenceJsonSignature.Sorted(window);
        var unresolved = EffectWindowEvaluation.At(window, new(1500));
        check(unresolved.Effects.Count == 0 && unresolved.Window.Get("_enable_state_unobserved_at_hit") is EvidenceBoolean { Value: true }
            && before == EvidenceJsonSignature.Sorted(window), "Effect evaluation returns quality state without mutating source evidence");
        var stopped = EffectWindowEvaluation.At(unresolved.Window, new(999));
        check(stopped.Window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: false }
            && stopped.Window.Get("rdps_unresolved_enable_evidence") is EvidenceBoolean { Value: true },
            "Per-hit flags reset while persistent quality evidence remains available");
        var points = Obj("""{"dynamic_effects":[{"zone":"amp","base_rate":0.1,"condition":{"type":"always"}}]}""");
        var evaluated = EffectWindowEvaluation.At(points, new(1500));
        var sourceCondition = ((EvidenceObject)((EvidenceArray)points.Get("dynamic_effects")).Items[0]).Get("condition");
        check(evaluated.Effects.Count == 1 && !ReferenceEquals(((EvidenceObject)evaluated.Effects[0]).Get("condition"), sourceCondition),
            "Computed effects own deep-copied condition evidence");
    }
}
