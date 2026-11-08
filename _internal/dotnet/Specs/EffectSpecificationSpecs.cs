using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectSpecificationSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        var root = Obj("""
            {"damageModifier":[{"enableSide":"Attacker",
              "condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[]},
              "damageProcessors":[{"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Attacker","zoneName":"NormalCalcZone",
                "addition":{"useBlackboardKey":true,"blackboardKey":"rate"}}]}],
             "attributeModifier":{"isConvertedAttribute":false,"attributeModifiers":[]}}
            """);
        var record = Obj("""{"event_key":"buff","bb_values":{"rate":0.2}}""");
        var roots = new Dictionary<string, EvidenceObject> { ["buff"] = root };
        var zones = new Dictionary<string, EvidenceObject> { ["NormalCalcZone"] = Obj("{}") };
        EffectSpecificationCatalog Catalog(EvidenceObject registry)
        {
            EffectApproval approval = new(registry, roots, new Dictionary<string, string>(), new Dictionary<string, string>());
            return new(approval, new(roots, zones, approval), new(roots));
        }
        var original = EvidenceJsonSignature.Sorted(record);
        var self = Catalog(Obj("{}")).CollectStatic(record);
        check(self.Effects is [var own] && own.Get("external_rdps_allowed") is EvidenceBoolean { Value: false }
            && own.Get("rdps_whitelist_keys") is EvidenceArray { Items.Count: 0 },
            "A current typed effect can enter its own baseline without authorizing external allocation");
        var registry = Obj("""
            {"verified_effects":{"buff":{"effects":[
              {"zone":"dmg_inc","element":"fire","bb_key":"rate"},
              {"zone":"dmg_inc","element":"pulse","bb_key":"rate"}]}}}
            """);
        var approved = Catalog(registry).CollectStatic(record);
        var transferred = Catalog(registry).CollectStaticOwned((EvidenceObject)EvidenceJson.Clone(record));
        check(EvidenceJsonSignature.Sorted(transferred.Record) == EvidenceJsonSignature.Sorted(approved.Record)
            && transferred.Effects.Select(EvidenceJsonSignature.Sorted).SequenceEqual(approved.Effects.Select(EvidenceJsonSignature.Sorted)),
            "Private report ownership preserves exact static scopes, typed conditions and quality evidence");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)approved.Record.Get("bb_values")).Fields)["rate"] = new EvidenceReal(.9);
        check(((EvidenceObject)record.Get("bb_values")).Get("rate") is EvidenceReal { Value: .2 },
            "The public static-effect boundary still detaches nested blackboard values from caller evidence");
        check(approved.Effects.Count == 1 && approved.Effects[0].Get("rate") is EvidenceReal { Value: 0.2 }
            && approved.Effects[0].Get("external_rdps_allowed") is EvidenceBoolean { Value: true },
            "Two approved element rows authorize one current branch once");
        var condition = (EvidenceObject)approved.Effects[0].Get("condition");
        var terms = (EvidenceArray)condition.Get("conditions");
        var union = (EvidenceObject)terms.Items[1];
        var branches = (EvidenceArray)union.Get("conditions");
        check(condition.Get("source") is EvidenceText { Value: "typed_and_whitelist" }
            && union.Get("type") is EvidenceText { Value: "any" } && branches.Items.Count == 2,
            "Approved scopes form a union intersected with the original typed condition");
        var conflict = Obj("""{"event_key":"buff","bb_values":{"rate":0.2},"rdps_live_identity_conflict":true}""");
        var rejected = Catalog(registry).CollectStatic(conflict);
        check(rejected.Effects.Count == 0 && rejected.Record.Get("rdps_unresolved_semantic_condition") is EvidenceArray
            { Items: [EvidenceText { Value: "conflicting_live_buff_identity" }] },
            "Conflicting identity rejects effects with an explicit quality reason");
        check(EvidenceJsonSignature.Sorted(record) == original && conflict.Get("rdps_unresolved_semantic_condition") is EvidenceNull,
            "Composition returns owned evidence without changing caller records");
        roots["conduct"] = Obj("""
            {"damageModifier":[
              {"enableSide":"Defender","condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[
                {"$type":"Beyond.Gameplay.Core.Conditions.CheckDamageTypeMask.Data","isEnable":true,"damageTypeMask":92}]},
               "damageProcessors":[{"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Defender","zoneName":"NormalCalcZone","addition":{"useBlackboardKey":true,"blackboardKey":"rate"}}]},
              {"enableSide":"Defender","condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[
                {"$type":"Beyond.Gameplay.Core.Conditions.CheckDamageTypeMask.Data","isEnable":true,"damageTypeMask":129},
                {"$type":"Beyond.Gameplay.Core.CompareFloat.Data","isEnable":true,"compare":"Equals","valueA":{"useBlackboardKey":true,"blackboardKey":"enhanced"},"valueB":{"useBlackboardKey":false,"value":1}}]},
               "damageProcessors":[{"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Defender","zoneName":"NormalCalcZone","addition":{"useBlackboardKey":true,"blackboardKey":"rate"}}]}],
             "attributeModifier":{"isConvertedAttribute":false,"attributeModifiers":[]}}
            """);
        var conductCatalog = Catalog(Obj("""{"verified_effects":{"conduct":{"effects":[{"zone":"vuln_taken","element":"all","bb_key":"rate"}]}}}"""));
        foreach (var flag in new[] { "1", "0", "null" })
        {
            var observedConduct = Obj("{\"event_key\":\"conduct\",\"bb_values\":{\"rate\":0.2,\"enhanced\":" + flag + "}}");
            var conductEffects = conductCatalog.CollectStatic(observedConduct).Effects;
            check(conductEffects.Count == 2, "Both exact conduct branches retain their original predicates");
            foreach (var element in new[] { "pulse", "physical", "ether", "real" })
            {
                var damage = Obj("{\"damage_element\":\"" + element + "\"}");
                var matching = conductEffects.Count(effect => EffectConditions.Failure(effect, damage) is null);
                check(matching == (element == "pulse" || flag == "1" && element is "physical" or "ether" ? 1 : 0),
                    "Conduct applies once, with observed enhancement and exact element mask: " + flag + "/" + element);
            }
        }
    }
}
