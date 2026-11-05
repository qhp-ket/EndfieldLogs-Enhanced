using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class ReportAccountingSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool, string> check)
    {
        var hit = Obj("""{"hit_value":100,"packet_hit_value":0,"packet_final_value":-120,"packet_raw_value":-150,"overkill_damage":20,"rdps_contributions":{"a":80,"b":20}}""");
        var basis = DamageBasis.Build([hit], Obj("""{"a":80,"b":20}""").Fields, 100);
        check(basis.Get("rdps_conservation_ok") is EvidenceBoolean { Value: true } && basis.Get("total_rdps_contribution") is EvidenceReal { Value: 100 },
            "The hand-calculated 80+20 contribution split conserves 100 effective HP loss");
        check(basis.Get("packet_grounded_hit_count") is EvidenceInteger count && count.Value == 1
            && basis.Get("overkill_capped_hit_count") is EvidenceInteger capped && capped.Value == 1,
            "An observed zero packet hit remains grounded and overkill is counted separately");
        check(basis.Get("total_packet_final_value") is EvidenceReal { Value: -120 } && basis.Get("total_packet_raw_value") is EvidenceReal { Value: -150 },
            "Packet raw and final values retain their signs and remain separate from effective damage");
        var mismatch = DamageBasis.Build([Obj("""{"hit_value":50,"rdps_contributions":{"a":80}}"""), Obj("""{"hit_value":50,"rdps_contributions":{"a":20}}""")],
            Obj("""{"a":100}""").Fields, 100);
        check(mismatch.Get("rdps_conservation_delta") is EvidenceReal { Value: 0 } && mismatch.Get("rdps_conservation_ok") is EvidenceBoolean { Value: false }
            && mismatch.Get("hit_conservation_mismatch_count") is EvidenceInteger mismatches && mismatches.Value == 2
            && mismatch.Get("max_hit_conservation_delta") is EvidenceReal { Value: 30 },
            "Opposite per-hit errors cannot hide behind a matching battle total");
        var unknown = DamageBasis.Build([Obj("""{"hit_value":100,"rdps_contributions":{"a":100.009}}""")], Obj("""{"a":100.009}""").Fields, 100);
        check(unknown.Get("rdps_conservation_ok") is EvidenceBoolean { Value: true } && unknown.Get("total_packet_raw_value") is EvidenceNull
            && unknown.Get("total_packet_final_value") is EvidenceNull,
            "The existing one-cent conservation budget does not fabricate missing packet values");
        var empty = DamageBasis.Build([], new Dictionary<string, EvidenceValue>(), 0);
        check(empty.Get("rdps_conservation_ok") is EvidenceBoolean { Value: true } && empty.Get("max_hit_conservation_delta") is EvidenceReal { Value: 0 },
            "An empty report has exact zero conservation error");
        AllocationDebug debug = new(key => key);
        HitAllocator allocator = new(new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>())),
            new(new Dictionary<string, EvidenceObject>()), new(new Dictionary<string, EvidenceObject>()), new(debug), new(debug), new(debug, row => new(row, [])));
        var source = Obj("""{"character_key":"a","target_enemy_key":"enemy","source_actor_id":"1","target_actor_id":"3","hit_value":120,"ts_ms":1000,"line_no":10,"damage_element":"fire"}""");
        var window = Obj("""{"uid":"u","event_key":"buff","source_character_key":"b","target_character_key":"a","target_actor_id":"1","start_ts_ms":900,"end_ts_ms":1100,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":0.2}]}""");
        var input = new ReportHitInput(source, new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
        var before = EvidenceJsonSignature.Sorted(source) + EvidenceJsonSignature.Sorted(window);
        var builder = new DebugHitDetails(allocator);
        var detailed = builder.Build([input], [window], []);
        var contributions = ((EvidenceArray)detailed.Hits[0].Get("rdps_contributions")).Items.Cast<EvidenceObject>().ToArray();
        check(contributions.Length == 2 && contributions[0].Get("character_key") is EvidenceText { Value: "a" } && contributions[0].Get("value") is EvidenceReal value && Math.Abs(value.Value - 100) < 1e-12,
            "The detailed view presents the same independently calculated 100/20 split as canonical allocation");
        check(detailed.Hits[0].Get("zones") is EvidenceArray { Items.Count: 1 } && detailed.Hits[0].Get("zone_summary") is EvidenceText { Value: "增伤 x1.2000" },
            "Detailed rows retain the actual zone evidence and compact Chinese summary");
        check(before == EvidenceJsonSignature.Sorted(source) + EvidenceJsonSignature.Sorted(window),
            "Building detailed rows leaves the caller's report hit and windows untouched");
        var expected = EvidenceJsonSignature.Sorted(detailed.Hits.Single());
        ((Dictionary<string, EvidenceValue>)detailed.Hits.Single().Fields)["rdps_contributions"] = EvidenceNull.Value;
        check(EvidenceJsonSignature.Sorted(builder.Build([input], [window], []).Hits.Single()) == expected,
            "Reusing the same detail builder preserves complete evidence after a caller edits an earlier result");
        check(new DebugHitDetails(allocator).Build([], [window], []).Hits.Count == 0, "Empty hit detail projection retains no fabricated hit");
    }
}
