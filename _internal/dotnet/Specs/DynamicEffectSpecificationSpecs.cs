using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class DynamicEffectSpecificationSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        DynamicEffectSpecificationCatalog Catalog(string registry, Dictionary<string, EvidenceObject>? roots = null)
        {
            roots ??= [];
            EffectApproval approval = new(Obj(registry), roots, new Dictionary<string, string>(), new Dictionary<string, string>());
            return new(approval, new(approval, new(roots, new Dictionary<string, EvidenceObject>(), approval), new(roots)), roots,
                new(new Dictionary<string, EvidenceObject>(), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), new Dictionary<string, string>()));
        }
        const string registry = """
            {"verified_effects":{"buff":{"dynamic":true,"dynamic_effects":[{"zone":"res","element":"fire",
              "base_bb_key":"rate","base_bb_keys":["alias","rate"]}]}}}
            """;
        var record = Obj("""{"event_key":"buff","bb_values":{"rate":-20,"alias":-20},"rdps_unresolved_dynamic_effect":true}""");
        var original = EvidenceJsonSignature.Sorted(record);
        var bound = Catalog(registry).Collect(record);
        var transferred = Catalog(registry).CollectOwned((EvidenceObject)EvidenceJson.Clone(record));
        check(EvidenceJsonSignature.Sorted(transferred.Record) == EvidenceJsonSignature.Sorted(bound.Record)
            && transferred.Effects.Select(EvidenceJsonSignature.Sorted).SequenceEqual(bound.Effects.Select(EvidenceJsonSignature.Sorted)),
            "Private report ownership preserves dynamic alias binding, rates and unresolved-state removal");
        check(bound.Effects is [var effect] && effect.Get("base_rate") is EvidenceReal { Value: 20 }
            && effect.Get("bb_key") is EvidenceText { Value: "alias" }
            && effect.Get("rdps_whitelist_keys") is EvidenceArray { Items: [EvidenceText { Value: "buff" }] }
            && bound.Record.Get("rdps_unresolved_dynamic_effect") is EvidenceNull,
            "Resistance parameters use observed magnitudes and retain the first matching declared alias");
        check(EvidenceJsonSignature.Sorted(record) == original && record.Get("rdps_unresolved_dynamic_effect") is EvidenceBoolean { Value: true },
            "Dynamic composition returns owned evidence and leaves caller quality state unchanged");
        var conflict = Catalog(registry).Collect(Obj("""{"event_key":"buff","bb_values":{"rate":-20,"alias":-30}}"""));
        check(conflict.Effects.Count == 0 && conflict.Record.Get("rdps_unresolved_dynamic_effect") is EvidenceBoolean { Value: true },
            "Conflicting runtime aliases fail closed instead of selecting an arbitrary operand");
        var tick = Catalog("""{"verified_effects":{"buff":{"dynamic":true,"dynamic_effects":[{"zone":"amp","element":"all","tick_bb_key":"tick"}]}}}""")
            .Collect(Obj("""{"event_key":"buff","bb_values":{"tick":0.2}}"""));
        check(tick.Effects.Count == 0 && tick.Record.Get("rdps_unresolved_dynamic_effect") is EvidenceBoolean { Value: true },
            "A configured nonzero tick is never integrated without explicit observed refresh evidence");
        var undeclared = Catalog(registry).Collect(Obj("""
            {"event_key":"buff","bb_values":{"other":20},
             "packet_mapping":{"dynamic_effects":[{"zone":"res","element":"fire","base_bb_key":"other"}]}}
            """));
        check(undeclared.Effects.Count == 0 && undeclared.Record.Get("rdps_whitelist_rejection") is EvidenceText { Value: "dynamic_operand_not_declared" },
            "A packet hint cannot authorize an operand absent from the reviewed formula");
        var literal = Catalog(registry).Collect(Obj("""
            {"event_key":"buff","packet_mapping":{"allow_static_rate":true,
             "dynamic_effects":[{"zone":"res","element":"fire","base_rate":20}]}}
            """));
        check(literal.Effects.Count == 0 && literal.Record.Get("rdps_whitelist_rejection") is EvidenceText { Value: "dynamic_literal_not_declared" },
            "A constant permission alone does not authorize an undeclared literal");
        var absent = Catalog("{}").Collect(record);
        check(absent.Effects.Count == 0 && absent.Record.Get("rdps_unresolved_dynamic_effect") is EvidenceNull,
            "Reevaluation clears stale dynamic quality state when no dynamic approval applies");

        const string key = "buff_common_natural_fire_triggered";
        var root = Obj("""
            {"attributeModifier":{"attributeModifiers":[
              {"attributeType":"FireResistance","formulaItem":"BaseAddition","modifyAttributeType":"Specific",
               "param":{"useBlackboardKey":true,"blackboardKey":"r"}},
              {"attributeType":"FireResistance","formulaItem":"BaseAddition","modifyAttributeType":"Specific",
               "param":{"useBlackboardKey":true,"blackboardKey":"extra"}}]}}
            """);
        var refresh = Obj("""
            {"event_key":"buff_common_natural_fire_triggered","attribute_refresh_snapshots":[
              {"ts_ms":1100,"line_no":2,"operation_seq":7,"session_id":"s","status":"attribute_parameters_observed",
               "bb_values":{"r":-20,"extra":-5}}],
             "resistance_parameter_snapshots":[{"bb_values":{"r":-99,"extra":-99}}]}
            """);
        var refreshCatalog = Catalog("""
            {"verified_effects":{"buff_common_natural_fire_triggered":{"dynamic":true,"effects":[
              {"zone":"res","bb_key":"r"},{"zone":"res","bb_key":"extra"}]}}}
            """, new() { [key] = root });
        var specs = refreshCatalog.Collect(refresh);
        check(specs.Effects is [var resistance] && resistance.Get("parameter_keys") is EvidenceArray
            { Items: [EvidenceText { Value: "r" }, EvidenceText { Value: "extra" }] }
            && EvidenceJson.PythonEquals(resistance.Get("parameter_snapshots"), refresh.Get("attribute_refresh_snapshots"))
            && !ReferenceEquals(resistance.Get("parameter_snapshots"), refresh.Get("attribute_refresh_snapshots")),
            "Typed resistance bindings group by element and prefer owned explicit refresh snapshots over legacy data");
        var window = new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["start_ts_ms"] = new EvidenceInteger(1000), ["end_ts_ms"] = new EvidenceInteger(2000),
            ["dynamic_effects"] = new EvidenceArray(specs.Effects.Cast<EvidenceValue>().ToArray()),
        });
        var hit = EffectWindowEvaluation.At(window, new(1500, 3, 8, "s"));
        check(hit.Effects is [EvidenceObject resolved] && resolved.Get("rate") is EvidenceReal { Value: 25 }
            && resolved.Get("resistance_point_source") is EvidenceText { Value: "packet_bb_update_and_refresh" },
            "Constructed specifications feed exact hit evaluation: two observed reductions total 25 resistance points");
        var otherSession = EffectWindowEvaluation.At(window, new(1500, 3, 8, "other"));
        check(otherSession.Effects.Count == 0 && otherSession.Window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: true },
            "A constructed resistance specification cannot supply another session's hit");
        var before = EffectWindowEvaluation.At(window, new(1050, 1, 6, "s"));
        check(before.Effects.Count == 0 && before.Window.Get("_effect_state_unresolved_at_hit") is EvidenceBoolean { Value: true },
            "A hit preceding the observed refresh remains unresolved instead of inheriting a future value");
    }
}
