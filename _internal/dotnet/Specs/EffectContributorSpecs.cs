using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class EffectContributorSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row, params (string Key, EvidenceValue Value)[] changes)
    {
        var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal);
        foreach (var (key, value) in changes) fields[key] = value;
        return new(fields);
    }
    private static readonly EvidenceObject Hit = Obj("""{"character_key":"chr_a","target_enemy_key":"enemy","source_actor_id":"a1","target_actor_id":"e1","hit_value":225,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell","damage_decorate_mask":256,"baseline":{"32":0.5}}""");
    private static readonly EvidenceObject Window = Obj("""{"uid":"u1","event_key":"buff","source_character_key":"chr_b","target_character_key":"chr_a","target_actor_id":"a1","start_ts_ms":900,"start_line_no":1,"end_ts_ms":1100,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":0.2,"attr_type":32}]}""");
    private static HitAllocation Prepare(IReadOnlyList<EvidenceObject> windows, EvidenceObject? hit = null, EffectStackPolicy? policy = null)
    {
        AllocationContextBuilder builder = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        var state = builder.Prepare(new(new(hit ?? Hit, new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>()), windows, IncludeDebug: true));
        state.SelectStackEffects(policy ?? new(new Dictionary<string, EvidenceObject>()));
        return state;
    }

    public static void Run(Action<bool, string> check)
    {
        AllocationDebug debug = new(key => key);
        EffectContributorCollection collector = new(debug);
        var self = Change(Window, ("uid", new EvidenceText("self")), ("event_key", new EvidenceText("self_buff")), ("source_character_key", new EvidenceText("chr_a")),
            ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"dmg_inc","element":"all","rate":0.1,"attr_type":32}]""")));
        var state = Prepare([Window, self]);
        collector.Collect(state);
        check(state.CapturedByAttribute[32] == .2 + .1 && state.ExternalByZone["dmg_inc"].Single().Provider == "chr_b" && state.SelfByZone["dmg_inc"] == .1,
            "Retained self and external attribute effects enter captured totals while preserving their owners");
        AllocationBaselines baselines = new(debug);
        baselines.AttachObserved(state);
        baselines.ResolveAttack(state);
        baselines.CheckRemaining(state);
        AllocationMultipliers.Compute(state);
        var result = LogMarginalAllocation.Allocate(state);
        check(Math.Abs(result.Contributions["chr_a"] - 195) < 1e-12 && Math.Abs(result.Contributions["chr_b"] - 30) < 1e-12
            && Math.Abs(result.Contributions.Values.Sum() - 225) < 1e-12,
            "The full collector/baseline/multiplier chain gives 195 self and 30 external from a 0.5 final bonus including 0.2 external");
        check(ReferenceEquals(state.ContributorsByZone["dmg_inc"][0], state.ExternalByZone["dmg_inc"][0].Evidence)
            && state.ExternalByZone["dmg_inc"][0].Evidence!.Get("rdps_credit") is EvidenceReal { Value: 30 },
            "The same owned explanation record receives its computed credit");
        var rejectedWindow = Change(Window, ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"dmg_inc","element":"all","rate":0.2,"attr_type":32,"external_rdps_allowed":false}]""")));
        var rejected = Prepare([rejectedWindow, self]);
        collector.Collect(rejected);
        baselines.AttachObserved(rejected);
        check(!rejected.ExternalByZone.ContainsKey("dmg_inc") && rejected.CapturedByAttribute[32] == .1 && rejected.SelfByZone["dmg_inc"] == .5
            && rejected.Hit.Get("rdps_unresolved_whitelist_effect") is EvidenceBoolean { Value: true },
            "Rejected external effects remain in the observed self baseline and receive no credit");
        var mismatch = Prepare([Change(Window, ("target_actor_id", new EvidenceText("another")))], Change(Hit,
            ("packet_modifier_uids", Obj("""{"attacker":["u1"]}"""))));
        collector.Collect(mismatch);
        check(mismatch.ExternalByZone.Count == 0 && mismatch.Hit.Get("rdps_unresolved_target_binding") is EvidenceBoolean { Value: true }
            && mismatch.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "buff_owner_instance_mismatch" },
            "A matching packet UID cannot override an explicitly different actor instance");
        var defender = Change(Window, ("target_character_key", new EvidenceText("enemy")), ("target_actor_id", new EvidenceText("e1")),
            ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"vuln_taken","element":"all","rate":0.2,"bb_key":"v"}]""")));
        var guarded = Prepare([defender, Change(defender, ("uid", new EvidenceText("u2")), ("event_key", new EvidenceText("other_buff")))], Change(Hit,
            ("packet_modifier_seen", new EvidenceBoolean(true)), ("packet_modifier_uids", Obj("""{"defender":["u1"]}"""))));
        collector.Collect(guarded);
        check(guarded.ExternalByZone["vuln_taken"].Count == 1
            && guarded.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "packet_defender_uid_suppressed" },
            "The selected defender UID suppresses a same-parameter mirrored debuff without dropping the selected one");
        var unknown = Prepare([Change(Window, ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"atk","rate":0.2}]""")))],
            Change(Hit, ("damage_calculation", new EvidenceObject(new Dictionary<string, EvidenceValue>()))));
        collector.Collect(unknown);
        check(unknown.ExternalByZone.Count == 0 && unknown.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true }
            && unknown.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "attack_damage_calculation_unresolved" },
            "Unknown attack dependence blocks attack attribution and exposes missing calculation evidence");
        var unique = new EffectStackPolicy(new Dictionary<string, EvidenceObject> { ["buff"] = Obj("""{"stackingSettings":{"stackingType":"Unique","maxStackCnt":1,"useMaxStackCntKey":false}}""") });
        var ambiguous = Prepare([Window, Change(Window, ("uid", new EvidenceText("u2")))], policy: unique);
        collector.Collect(ambiguous);
        check(ambiguous.UnresolvedStackZones.Contains("dmg_inc") && ambiguous.ExternalByZone.Count == 0,
            "Unresolved unique-stack selection blocks every source in the affected zone");
        var boolAttribute = Prepare([Change(Window, ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"dmg_inc","rate":0.2,"attr_type":false}]""")))]);
        collector.Collect(boolAttribute);
        check(boolAttribute.CapturedByAttribute[0] == .2 && boolAttribute.ContributorsByZone["dmg_inc"].Count == 1,
            "Python boolean attribute keys share the numeric zero identity while the original effect evidence stays boolean");
        var sourceBefore = EvidenceJsonSignature.Sorted(Window);
        var next = Prepare([Window]);
        collector.Collect(next);
        check(next.ExternalByZone["dmg_inc"].Count == 1 && EvidenceJsonSignature.Sorted(Window) == sourceBefore
            && Window.Get("_buff_enabled_at_hit") is EvidenceNull, "Consecutive hit allocations do not share contributor records or mutate source windows");
        Arts(check, collector);
    }

    private static void Arts(Action<bool, string> check, EffectContributorCollection collector)
    {
        var effectWindow = Obj("""{"uid":"debuff","event_key":"debuff","source_character_key":"chr_b","target_character_key":"enemy","target_actor_id":"e1","start_ts_ms":900,"start_line_no":10,"end_ts_ms":1100,"source_static_arts_strength":100,"zone_effects":[{"zone":"vuln_taken","element":"all","rate":0.3,"arts_strength_provenance":true}]}""");
        var support = Obj("""{"uid":"arts","event_key":"support","source_character_key":"chr_a","target_character_key":"chr_b","target_actor_id":"b1","start_ts_ms":800,"start_line_no":1,"end_ts_ms":1100,"zone_effects":[{"zone":"arts_strength","rate":100,"rdps_whitelist_keys":["support"]}]}""");
        var effect = (EvidenceObject)((EvidenceArray)effectWindow.Get("zone_effects")).Items[0];
        var direct = ArtsEffectAttribution.Attribute(effectWindow, Change(effect, ("arts_strength_provenance", new EvidenceBoolean(false))), [support]);
        check(direct.Sources.Count == 1 && direct.Sources[0] is { Provider: "chr_b", Rate: .3, Provenance: null },
            "An ordinary debuff is never implicitly redistributed by arts strength");
        var attributed = ArtsEffectAttribution.Attribute(effectWindow, effect, [support]);
        check(attributed.Sources.Count == 2 && Math.Abs(attributed.Sources[0].Rate - .25) < 1e-15
            && Math.Abs(attributed.Sources[1].Rate - .05) < 1e-15,
            "Typed provenance splits 0.3 by the 1.5/1.8 effect multiplier into 0.25 owner and 0.05 support");
        check(attributed.Sources[1].Provenance!.Get("arts_strength_self_points") is EvidenceReal { Value: 100 }
            && attributed.Sources[1].Provenance!.Get("arts_strength_external_points") is EvidenceReal { Value: 100 }
            && support.Get("_buff_enabled_at_hit") is EvidenceNull, "Arts attribution owns its evaluation flags and preserves the exact point provenance");
        var state = Prepare([effectWindow, support]);
        collector.Collect(state);
        check(Math.Abs(state.SelfByZone["vuln_taken"] - .05) < 1e-15 && Math.Abs(state.ExternalByZone["vuln_taken"].Single().Rate - .25) < 1e-15,
            "The actual collector treats attacker-provided support as self and the debuff owner as external");
        check(state.ContributorsByZone["vuln_taken"].Single(row => row.Get("scope") is EvidenceText { Value: "self" })
            .Get("derived_from_zone") is EvidenceText { Value: "arts_strength" }, "Redistributed self credit retains its secondary arts origin in the explanation");
        var late = Change(support, ("start_ts_ms", new EvidenceInteger(950)));
        check(ArtsEffectAttribution.Attribute(effectWindow, effect, [late]).Sources.Count == 1,
            "A support BUFF that starts after debuff application cannot retroactively scale its source");
    }
}
