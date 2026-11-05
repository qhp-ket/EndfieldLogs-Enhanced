using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

internal static class HitAllocatorSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject value, params (string Key, EvidenceValue Value)[] changes)
    {
        var fields = new Dictionary<string, EvidenceValue>(value.Fields);
        foreach (var (key, field) in changes) fields[key] = field;
        return new(fields);
    }
    private static ReportHitInput Input(EvidenceObject hit) => new(hit, new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    public static void Run(Action<bool, string> check)
    {
        AllocationDebug debug = new(key => key == "chr_a" ? "甲" : key == "chr_b" ? "乙" : key);
        AllocationContextBuilder context = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        HitAllocator allocator = new(context, new(new Dictionary<string, EvidenceObject>()), new(new Dictionary<string, EvidenceObject>()),
            new(debug), new(debug), new(debug, row => new(row, ["增伤"])));
        var hit = Obj("""{"character_key":"chr_a","target_enemy_key":"enemy","source_actor_id":"a1","target_actor_id":"e1","hit_value":225,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell","damage_decorate_mask":256,"baseline":{"32":0.5},"packet_modifier_uids":{"attacker":["u1"],"defender":[]}}""");
        var window = Obj("""{"uid":"u1","event_key":"buff","source_character_key":"chr_b","target_character_key":"chr_a","target_actor_id":"a1","start_ts_ms":900,"end_ts_ms":1100,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":0.2,"attr_type":32}]}""");
        var record = Obj("""{"uid":"u1","event_key":"buff","source_character_key":"chr_b","source_character_name":"乙","target_character_key":"chr_a","target_character_name":"甲","ts_ms":900,"line_no":1,"bb_values":{"rate":0.2},"bb_keys":["z","a","z"]}""");
        var index = new Dictionary<string, IReadOnlyList<EvidenceObject>> { ["u1"] = new[] { record } };
        var before = EvidenceJsonSignature.Sorted(hit) + EvidenceJsonSignature.Sorted(window) + EvidenceJsonSignature.Sorted(record);
        var allocated = allocator.Allocate(new(Input(hit), [window], BuffRecordsByUid: index, IncludeDebug: true));
        var shares = (EvidenceObject)allocated.Allocation.Get("contributions_map");
        check(shares.Get("chr_a") is EvidenceReal own && Math.Abs(own.Value - 195) < 1e-12 && shares.Get("chr_b") is EvidenceReal external && Math.Abs(external.Value - 30) < 1e-12,
            "The public per-hit allocator connects observed evidence to the independently calculated 195/30 split");
        check(allocated.Allocation.Get("zone_summary") is EvidenceText { Value: "增伤 x1.1538" }
            && allocated.Allocation.Get("buff_source_summary") is EvidenceText { Value: "乙 +30.0" },
            "Detailed allocation formats compact Chinese zone and source summaries from computed values");
        var modifier = (EvidenceObject)((EvidenceArray)allocated.Allocation.Get("packet_modifier_details")).Items.Single();
        check(modifier.Get("event_name") is EvidenceText { Value: "增伤" } && modifier.Get("target_name") is EvidenceText { Value: "甲" }
            && ((EvidenceArray)modifier.Get("bb_keys")).Items.OfType<EvidenceText>().Select(value => value.Value).SequenceEqual(["a", "z"]),
            "Packet modifier detail uses the injected catalog labels and sorted distinct observed blackboard keys");
        var source = (EvidenceObject)((EvidenceArray)allocated.Allocation.Get("external_sources")).Items.Single();
        check(source.Get("effect_count") is EvidenceInteger count && count.Value == 1 && source.Get("rdps_credit") is EvidenceReal { Value: 30 },
            "Source summaries count the real retained effect and its rounded explanation credit");
        check(before == EvidenceJsonSignature.Sorted(hit) + EvidenceJsonSignature.Sorted(window) + EvidenceJsonSignature.Sorted(record)
            && !ReferenceEquals(hit, allocated.Hit), "Full allocation owns its hit changes and leaves report inputs unchanged");
        var brief = allocator.Allocate(new(Input(hit), [window]));
        check(brief.Allocation.Fields.Count == 4 && EvidenceJsonSignature.Sorted(brief.Allocation.Get("contributions_map")) == EvidenceJsonSignature.Sorted(shares),
            "Debug projection does not change accounting; the brief result carries just its four protocol fields");
        var ended = Change(record, ("end_ts_ms", new EvidenceInteger(1000)), ("end_line_no", new EvidenceInteger(10)));
        var closed = allocator.Allocate(new(Input(hit), [window], BuffRecordsByUid: new Dictionary<string, IReadOnlyList<EvidenceObject>> { ["u1"] = new[] { ended } }, IncludeDebug: true));
        check(((EvidenceObject)((EvidenceArray)closed.Allocation.Get("packet_modifier_details")).Items.Single()).Get("event_key") is EvidenceText { Value: "" },
            "An expired modifier is shown as unknown at its exact exclusive end line");
        var inkShares = Obj("""{"chr_a":70,"chr_b":30}""");
        var ink = Change(hit, ("_ink_allocation", inkShares), ("ink_provenance", Obj("""{"status":"observed","sources":[1,2]}""")));
        var frozen = allocator.Allocate(new(Input(ink), [window], IncludeDebug: true));
        check(frozen.Allocation.Get("allocation_policy") is EvidenceText { Value: "whole_ink_damage_log_zones_v1" }
            && ((EvidenceObject)frozen.Allocation.Get("contributions_map")).Get("chr_b") is EvidenceInteger credit && credit.Value == 30
            && frozen.Allocation.Get("external_pool") is EvidenceInteger pool && pool.Value == 30,
            "Recorded ink shares bypass explosion-time multipliers and preserve integer evidence at the compatibility boundary");
        check(frozen.Allocation.Get("product_external_multiplier") is EvidenceNull && frozen.Allocation.Get("zones") is EvidenceArray { Items.Count: 0 }
            && frozen.Allocation.Get("zone_summary") is EvidenceObject { Fields.Count: 0 },
            "A recorded release never invents one explosion-time multiplier for its source-time distribution");
        ((Dictionary<string, EvidenceValue>)inkShares.Fields)["chr_b"] = new EvidenceInteger(90);
        check(((EvidenceObject)frozen.Allocation.Get("contributions_map")).Get("chr_b") is EvidenceInteger preserved && preserved.Value == 30,
            "A frozen ink result owns its share map independently of later caller changes");
        var exact = PythonNumericSum.Sum([new EvidenceInteger(BigInteger.Pow(10, 100)), new EvidenceInteger(-BigInteger.Pow(10, 100)), new EvidenceReal(.5)]);
        check(exact is EvidenceReal { Value: .5 } && PythonNumericSum.Sum([]) is EvidenceInteger zero && zero.Value.IsZero,
            "Leading integer cancellation remains exact before switching the compatibility sum to floating point");
        var folder = Path.Combine(Path.GetTempPath(), "endfield-hit-allocator-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            var production = HitAllocator.Load(new(folder));
            var actual = production.Allocate(new(Input(hit), [window]));
            check(EvidenceJsonSignature.Sorted(actual.Allocation.Get("contributions_map")) == EvidenceJsonSignature.Sorted(shares),
                "The production resource factory constructs the complete per-hit chain without GUI or native capture dependencies");
        }
        finally { Directory.Delete(folder, true); }
    }
}
