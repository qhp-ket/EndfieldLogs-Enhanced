using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class AllocationContextSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row, params (string Key, EvidenceValue Value)[] values)
    {
        var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal);
        foreach (var (key, value) in values) fields[key] = value;
        return new(fields);
    }
    private static ReportHitInput Hit(EvidenceObject evidence) => new(evidence, new Dictionary<BigInteger, EvidenceValue>(),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());

    public static void Run(Action<bool, string> check)
    {
        AllocationContextBuilder builder = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<EndfieldLogs.Core.Catalog.SkillDamageUnit>>()));
        var hit = Obj("""{"character_key":"chr_a","target_enemy_key":"enemy","source_actor_id":"a1","target_actor_id":"e1","hit_value":100,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell","packet_attr_details":{"defender":["98:20,20","98:20","32:0.2"]}}""");
        var before = EvidenceJsonSignature.Sorted(hit);
        var state = builder.Prepare(new(Hit(hit), []));
        check(state.Attacker == "chr_a" && state.Target == "enemy" && state.HitValue == 100 && state.TimestampMs == 1000
            && state.LineNumber == 10 && state.Attack.Kind == AttackDependence.Linear,
            "Allocation preparation derives the hit coordinates and preserves the legacy calculation contract");
        check(state.ResistanceAttribute == 98 && state.ResistanceRows.Count == 2 && state.EffectiveResistance == 20
            && state.ResistanceNumerator == 80 && state.ResistanceSource == "PKT_ATTR.defender.attr98",
            "Only consistent operation-local resistance observations produce the numerator");
        check(state.DefenderAllowedEffects.SetEquals(new[] { ("dmg_inc", "all") })
            && state.Hit.Get("attack_damage_dependency") is EvidenceText { Value: "linear" }
            && state.Hit.Get("_active_target_buff_ids") is EvidenceArray { Items.Count: 0 },
            "Prepared packet guards and active condition evidence are committed to the owned hit");
        check(EvidenceJsonSignature.Sorted(hit) == before && !ReferenceEquals(hit, state.Hit),
            "Per-hit preparation keeps caller evidence unchanged");
        var conflict = builder.Prepare(new(Hit(Change(hit, ("packet_attr_conflict", new EvidenceBoolean(true)))), []));
        check(conflict.EffectiveResistance is null && conflict.ResistanceNumerator is null,
            "Packet attribute conflict blocks resistance even when textual values agree");
        var disagreement = Change(hit, ("packet_attr_details", Obj("""{"defender":["98:20,21"]}""")));
        check(builder.Prepare(new(Hit(disagreement), [])).EffectiveResistance is null
            && builder.Prepare(new(Hit(Change(hit, ("packet_attr_details", Obj("""{"defender":["98:nan"]}""")))), [])).EffectiveResistance is null,
            "Disagreement and nonfinite resistance remain unknown");
        var anomaly = builder.Prepare(new(Hit(Change(hit, ("damage_decorate_mask", new EvidenceInteger(0x40000008)))), []));
        check(anomaly.ArtsStrength is { Observed: true, FactorCount: 2 } && anomaly.Hit.Get("arts_strength_damage_kind") is EvidenceText { Value: "mixed_anomaly" },
            "The prepared hit carries independently observed physical and spell anomaly factors");
        var record = Obj("""{"uid":"u1","target_enemy_key":"enemy","target_actor_id":"e1","ts_ms":900,"raw_duration_ms":500,"event_key":"debuff"}""");
        var withRecords = builder.Prepare(new(Hit(hit), [], new[] { record }));
        var indexedEmpty = builder.Prepare(new(Hit(hit), [], new[] { record }, new Dictionary<string, IReadOnlyList<EvidenceObject>>()));
        check(withRecords.ActiveTargetBuffIds.Contains("debuff") && indexedEmpty.ActiveTargetBuffIds.Count == 0,
            "An explicit target index is authoritative and does not fall back to unrelated records");
        var window = Obj("""{"uid":"u1","target_character_key":"enemy","start_ts_ms":900,"end_ts_ms":1100,"zone_effects":[{"zone":"vuln_taken","rate":0.2}]}""");
        var packetHit = Change(hit, ("packet_modifier_seen", new EvidenceBoolean(true)), ("packet_modifier_uids", Obj("""{"attacker":["a"],"defender":["u1"]}""")));
        var selected = builder.Prepare(new(Hit(packetHit), new[] { window }, WindowIndices: new[] { 0 }));
        check(selected.MatchedDefenderSignatures.Count == 1 && selected.Windows[0].Get("_buff_enabled_at_hit") is EvidenceBoolean { Value: true }
            && selected.AttackerModifierUids.Contains("a") && selected.DefenderModifierUids.Contains("u1"),
            "Selected packet windows are evaluated and mapped back to the real allocation state");
        check(builder.Prepare(new(Hit(packetHit), new[] { window }, WindowIndices: Array.Empty<int>())).MatchedDefenderSignatures.Count == 0
            && builder.Prepare(new(Hit(hit), new[] { window })).Windows[0].Get("_buff_enabled_at_hit") is EvidenceNull,
            "An empty selection and absent packet-observation flag each suppress guard matching");
        ((Dictionary<string, EvidenceValue>)selected.Hit.Fields)["marker"] = new EvidenceText("first");
        var next = builder.Prepare(new(Hit(packetHit), new[] { window }));
        check(next.Hit.Get("marker") is EvidenceNull && window.Get("_buff_enabled_at_hit") is EvidenceNull
            && !ReferenceEquals(next.Hit, selected.Hit), "Consecutive allocations own their hit changes and leave shared source windows intact");
        var root = Path.Combine(Path.GetTempPath(), "endfield-allocation-context-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var resources = BattleIngestionResources.Load(new(root));
            BattleIngestionStream stream = new(resources);
            stream.Accept(1, "[00:00:00.900] BUFF_START uid=7 id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11 dur=2");
            stream.Accept(2, "[00:00:01.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=100");
            stream.Accept(3, "[00:00:01.010] BASELINE #1 32=0.2");
            var captured = ReportHitInput.Capture(stream.Hits.Hits.Single());
            AllocationContextBuilder production = new(new AttackDependenceClassifier(resources.DamageUnits));
            var prepared = production.Prepare(new(captured, [], stream.Buffs.Records.Select(BuffReportEvidence.Project).ToArray()));
            check(prepared.Attacker == "chr_0001_alpha" && prepared.ActiveTargetBuffIds.Contains("buff_test")
                && prepared.Attack.Kind == AttackDependence.Unknown && prepared.NumericBaseline[32] is EvidenceReal { Value: 0.2 },
                "Real typed ingestion, report projection and resource lookups feed the production allocation context");
            stream.Accept(4, "[00:00:01.020] BASELINE #1 32=0.8");
            check(prepared.NumericBaseline[32] is EvidenceReal { Value: 0.2 }
                && stream.Hits.Hits.Single().Packet.Baseline?[32] == 0.8,
                "Late packet updates are isolated from the already prepared allocation baseline");
        }
        finally { Directory.Delete(root, true); }
    }
}
