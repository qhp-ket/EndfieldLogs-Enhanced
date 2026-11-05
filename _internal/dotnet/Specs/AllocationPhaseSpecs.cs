using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class AllocationPhaseSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row, params (string Key, EvidenceValue Value)[] changes)
    {
        var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal);
        foreach (var (key, value) in changes) fields[key] = value;
        return new(fields);
    }
    private static readonly EvidenceObject Base = Obj("""{"character_key":"chr_a","target_enemy_key":"enemy","source_actor_id":"a1","target_actor_id":"e1","hit_value":100,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell","damage_decorate_mask":256}""");
    private static HitAllocation Prepare(EvidenceObject hit, IReadOnlyList<EvidenceObject>? windows = null,
        IReadOnlyList<EvidenceObject>? records = null, IReadOnlyDictionary<BigInteger, EvidenceValue>? numeric = null,
        IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? byUid = null)
    {
        AllocationContextBuilder context = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        return context.Prepare(new(new(hit, numeric ?? new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(),
            new Dictionary<BigInteger, EvidenceValue>()), windows ?? [], records, ConditionsByUid: byUid, IncludeDebug: true));
    }

    public static void Run(Action<bool, string> check)
    {
        AllocationDebug debug = new(key => key == "chr_a" ? "甲" : key);
        AllocationBaselines baselines = new(debug);
        var observed = Prepare(Change(Base, ("baseline", Obj("""{"32":0.3,"51":0.1,"9":0.5,"2":0.8}"""))));
        observed.CapturedByAttribute[32] = .1;
        baselines.AttachObserved(observed);
        check(Math.Abs(observed.SelfByZone["dmg_inc"] - .3) < 1e-15 && !observed.SelfByZone.ContainsKey("crit") && !observed.SelfByZone.ContainsKey("atk"),
            "Observed skill and elemental bonuses subtract captured effects while attack and crit use dedicated models");
        check(observed.ContributorsByZone["dmg_inc"].Count == 2
            && observed.ContributorsByZone["dmg_inc"][0].Get("baseline_captured") is EvidenceReal { Value: .1 }
            && observed.ContributorsByZone["dmg_inc"][0].Get("event_name") is EvidenceText { Value: "自身属性基线（增伤 / attrType=32）" },
            "Observed-baseline explanations expose the exact attribute and captured share in Chinese");
        var unknown = Prepare(Change(Base, ("damage_decorate_mask", EvidenceNull.Value), ("baseline", Obj("""{"32":0.2,"51":0.1}"""))));
        baselines.AttachObserved(unknown);
        check(unknown.SelfByZone["dmg_inc"] == .1 && unknown.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true },
            "An exact fire attribute applies without a category mask; a generic skill attribute stays unresolved");
        var negative = Prepare(Change(Base, ("baseline", Obj("""{"32":0.1}"""))));
        negative.CapturedByAttribute[32] = .2;
        baselines.AttachObserved(negative);
        check(negative.SelfByZone.Count == 0 && negative.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true },
            "Captured effects cannot turn an insufficient final attribute into a negative self bonus");
        var typed = Prepare(Change(Base, ("baseline", Obj("""{"32":0.3}"""))), numeric: new Dictionary<BigInteger, EvidenceValue> { [32] = new EvidenceReal(.2) });
        baselines.AttachObserved(typed);
        check(typed.SelfByZone["dmg_inc"] == .5 && typed.ContributorsByZone["dmg_inc"].Count == 2,
            "Genuine text and integer baseline keys retain their independent Python dictionary semantics");
        var flat = Prepare(Change(Base, ("static_flat_attack", new EvidenceInteger(20)), ("base_attack_for_percent", new EvidenceInteger(100))));
        baselines.ResolveAttack(flat);
        check(flat.SelfByZone["atk"] == .2 && flat.AttackBaselineError is null,
            "Twenty fixed attack over a hundred base attack supplies a 0.2 self attack ratio");
        var calculation = Obj("""{"source":"current_typed_damage_unit","simpleCalculation":false,"sourceProof":{"resourceId":"owner_buff"},"atkCalculation":{"$type":"Beyond.Gameplay.Core.MultiplyAttributeCalculation","attributeType":"Atk","valueSource":"AttackerOrHealer","multiplier":{"useBlackboardKey":true,"blackboardKey":"m"},"addition":{"useBlackboardKey":true,"blackboardKey":"a"}}}""");
        var affineHit = Change(Base, ("event_inst_id", new EvidenceText("owner")), ("damage_calculation", calculation),
            ("static_flat_attack", new EvidenceInteger(20)), ("base_attack_for_percent", new EvidenceInteger(100)), ("attack_ability_factor", new EvidenceReal(1.5)));
        var owner = Obj("""{"uid":"owner","event_key":"owner_buff","ts_ms":900,"line_no":1,"bb_values":{"m":2,"a":60}}""");
        var affine = Prepare(affineHit, records: [owner]);
        baselines.ResolveAttack(affine);
        check(affine.Attack.Kind == AttackDependence.Affine && affine.AttackBaselineError is null && affine.SelfByZone["atk"] == .4,
            "The affine fixed term adds 60/(100*1.5*2) to the independent 20/100 flat attack ratio");
        var duplicate = Prepare(affineHit, records: [owner, owner]);
        duplicate.ExternalByZone["atk"] = [new("chr_b", .2, null)];
        baselines.ResolveAttack(duplicate);
        check(duplicate.AttackBaselineError == "missing_damage_base_addition" && !duplicate.SelfByZone.ContainsKey("atk")
            && duplicate.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true }
            && duplicate.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "missing_damage_base_addition" },
            "Ambiguous owners cannot manufacture a fixed damage baseline or credit an external attack source");
        var indexed = Prepare(affineHit, records: [owner], byUid: new Dictionary<string, IReadOnlyList<EvidenceObject>>());
        baselines.ResolveAttack(indexed);
        check(indexed.AttackBaselineError == "missing_damage_base_addition" && indexed.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceNull,
            "An explicitly empty owner index is authoritative; a missing self term alone does not blame external attack");
        var ended = Prepare(affineHit, records: [Change(owner, ("end_ts_ms", new EvidenceInteger(1000)), ("end_line_no", new EvidenceInteger(10)))]);
        baselines.ResolveAttack(ended);
        check(ended.AttackBaselineError == "missing_damage_base_addition", "The exact owner end line is exclusive for affine parameters");
        var arts = Prepare(Change(Base, ("damage_decorate_mask", new EvidenceInteger(0x4000)),
            ("static_arts_strength_entries", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"arts_strength","rate":120},{"zone":"arts_strength","rate":"bad"}]"""))));
        baselines.CheckRemaining(arts);
        check(arts.SelfByZone["arts_strength"] == 120 && arts.InvalidNumericAllocation, "Anomaly hits retain valid arts points and flag malformed static points");
        var residual = Prepare(Change(Base, ("dpd_raw", Obj("""{"atk_zones":[1,1.3,1,1,1]}"""))));
        residual.SelfByZone["dmg_inc"] = .2;
        residual.ExternalByZone["dmg_inc"] = [new("chr_b", .1, null)];
        baselines.CheckRemaining(residual);
        check(residual.Hit.Get("rdps_unresolved_dpd_residual") is EvidenceNull, "A fully explained DPD bucket preserves resolved quality");
        residual.ExternalByZone["dmg_inc"] = [];
        baselines.CheckRemaining(residual);
        check(residual.Hit.Get("rdps_unresolved_dpd_residual") is EvidenceBoolean { Value: true }, "A missing 0.1 DPD source remains explicitly unresolved");
        check(PythonFloatSum.Sum([1e16, 1, -1e16]) == 1 && PythonFloatSum.Sum([]) == 0,
            "The Python sum retains a unit contribution between cancelling large rates");
        check(AllocationDebug.Round4(new EvidenceReal(1.23445)) is EvidenceReal { Value: 1.2345 }
            && AllocationDebug.Round4(new EvidenceText("bad")) is EvidenceNull,
            "Explanation rounding follows the binary64 reference rather than decimal midpoint assumptions");
        var effect = Obj("""{"zone":"amp","rate":0.123456,"condition":{"type":"all","conditions":[]},"rdps_whitelist_keys":["proof"]}""");
        var row = debug.Applicable(Obj("""{"source_character_key":"chr_a","uid_aliases":["u1"]}"""), effect, "external");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)effect.Get("condition")).Fields)["changed"] = new EvidenceBoolean(true);
        check(row.Get("source_character_name") is EvidenceText { Value: "甲" }
            && ((EvidenceObject)row.Get("condition")).Get("changed") is EvidenceNull,
            "Explanation rows resolve names and own nested condition evidence");
        check(debug.ContributionRows(new Dictionary<string, double> { ["b"] = 10, ["a"] = 10, ["zero"] = 0 }, true)
            .Select(value => value.Get("character_key")).OfType<EvidenceText>().Select(value => value.Value).SequenceEqual(["a", "b"]),
            "Contribution rows omit zero credit and break equal numeric ranks by character key");
        Resistance(check);
        Ingestion(check, baselines);
    }

    private static void Resistance(Action<bool, string> check)
    {
        var hit = Change(Base, ("target_resistance_points", Obj("""{"fire":20}""")), ("target_stats_snapshot_ts_ms", new EvidenceInteger(800)),
            ("target_stats_snapshot_line_no", new EvidenceInteger(1)), ("packet_attribute_report_present", new EvidenceBoolean(true)));
        var window = Obj("""{"uid":"u1","event_key":"buff","source_character_key":"chr_b","target_character_key":"enemy","target_actor_id":"e1","start_ts_ms":900,"start_line_no":1,"end_ts_ms":1100,"end_line_no":20,"dynamic_effects":[{"zone":"res","element":"fire","parameter_keys":["res"],"external_rdps_allowed":true,"rdps_whitelist_keys":["proof"],"parameter_snapshots":[{"ts_ms":900,"line_no":2,"operation_seq":1,"status":"attribute_parameters_observed","bb_values":{"res":-10}}]}]}""");
        HitAllocation Selected(EvidenceObject evidence, IReadOnlyList<EvidenceObject>? records = null)
        {
            var state = Prepare(evidence, [window], records);
            state.SelectStackEffects(new(new Dictionary<string, EvidenceObject>()));
            return state;
        }
        AllocationResistance resistance = new(new Dictionary<string, EvidenceObject>());
        var state = Selected(hit);
        resistance.Resolve(state);
        check(state.EffectiveResistance == 10 && state.ResistanceNumerator == 90
            && state.ResistanceSource == "ENTITY_STATS+packet_bb_refresh+complete_instant_report",
            "A clean 20-point entity baseline and observed ten-point persistent reduction prove effective resistance ten");
        check(state.EffectsAtHit[0].Single() is EvidenceObject effect && effect.Get("resistance_point_source") is EvidenceText { Value: "packet_bb_update_and_refresh" }
            && window.Get("_buff_enabled_at_hit") is EvidenceNull,
            "Real stack selection feeds evaluated refresh evidence into the state without mutating source windows");
        var contaminated = Selected(Change(hit, ("target_stats_snapshot_ts_ms", new EvidenceInteger(950))));
        resistance.Resolve(contaminated);
        check(contaminated.EffectiveResistance is null, "Stats sampled inside the persistent BUFF cannot supply its pre-BUFF baseline");
        var noReport = Selected(Change(hit, ("packet_attribute_report_present", new EvidenceInteger(1))));
        resistance.Resolve(noReport);
        check(noReport.EffectiveResistance is null, "A numeric one does not prove a complete instantaneous packet attribute report");
        var instantaneous = Selected(Change(hit, ("packet_attr_details", Obj("""{"defender":["98:7"]}"""))));
        resistance.Resolve(instantaneous);
        check(instantaneous.EffectiveResistance == 7 && instantaneous.ResistanceSource == "PKT_ATTR.defender.attr98", "Exact operation-local resistance takes precedence over entity stats");
        var hidden = Obj("""{"uid":"other","event_key":"hidden","target_actor_id":"e1","ts_ms":850,"line_no":1,"end_ts_ms":1200}""");
        AllocationResistance withRoots = new(new Dictionary<string, EvidenceObject> { ["hidden"] = Obj("""{"attributeModifier":{"attributeModifiers":[{"attributeType":"FireResistance"}]}}""") });
        var unmodeled = Selected(hit, [hidden]);
        withRoots.Resolve(unmodeled);
        check(unmodeled.EffectiveResistance is null, "A second observed persistent resistance modifier prevents unsupported subtraction");
        var covered = Selected(hit, [Change(hidden, ("uid", new EvidenceText("u1")), ("ts_ms", new EvidenceInteger(900)), ("line_no", new EvidenceInteger(1)))]);
        withRoots.Resolve(covered);
        check(covered.EffectiveResistance == 10, "The same UID and raw start coordinates identify an already modeled persistent instance");
    }

    private static void Ingestion(Action<bool, string> check, AllocationBaselines baselines)
    {
        var folder = Path.Combine(Path.GetTempPath(), "endfield-allocation-phases-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            var resources = BattleIngestionResources.Load(new(folder));
            BattleIngestionStream stream = new(resources);
            stream.Accept(1, "[00:00:01.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=100");
            stream.Accept(2, "[00:00:01.010] BASELINE #1 32=0.3");
            var captured = ReportHitInput.Capture(stream.Hits.Hits.Single());
            captured = captured with { Evidence = Change(captured.Evidence, ("damage_decorate_mask", new EvidenceInteger(256))) };
            AllocationContextBuilder builder = new(new AttackDependenceClassifier(resources.DamageUnits));
            var state = builder.Prepare(new(captured, [], IncludeDebug: true));
            baselines.AttachObserved(state);
            check(captured.BaselineProjectionIsNumeric && state.SelfByZone["dmg_inc"] == .3 && state.ContributorsByZone["dmg_inc"].Count == 1,
                "Typed ingestion's JSON text-key projection aliases its numeric baseline and is counted once");
            stream.Accept(3, "[00:00:01.020] BASELINE #1 32=0.9");
            check(state.SelfByZone["dmg_inc"] == .3 && state.NumericBaseline[32] is EvidenceReal { Value: .3 }
                && stream.Hits.Hits.Single().Packet.Baseline?[32] == .9,
                "A later packet cannot mutate the already evaluated self baseline or the captured report evidence");
        }
        finally { Directory.Delete(folder, true); }
    }
}
