using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class DamageLedgerSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject input, params (string Key, EvidenceValue Value)[] changes)
    {
        var fields = new Dictionary<string, EvidenceValue>(input.Fields);
        foreach (var (key, value) in changes) fields[key] = value;
        return new(fields);
    }
    private static ReportHitInput Input(EvidenceObject hit) => new(hit, new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    public static void Run(Action<bool, string> check)
    {
        AllocationDebug debug = new(key => key);
        HitAllocator allocator = new(new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>())),
            new(new Dictionary<string, EvidenceObject>()), new(new Dictionary<string, EvidenceObject>()), new(debug), new(debug), new(debug, row => new(row, [])));
        var roots = new Dictionary<string, EvidenceObject> { [InkProvenanceStream.Buff] = InkProvenanceSpecs.Root() };
        DamageShareLedger ledger = new(allocator, roots);
        var normal = Obj("""{"character_key":"attacker","target_enemy_key":"enemy","source_actor_id":"1","target_actor_id":"3","hit_value":120,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell"}""");
        var window = Obj("""{"uid":"u","event_key":"buff","source_character_key":"support","target_character_key":"attacker","target_actor_id":"1","start_ts_ms":900,"end_ts_ms":1100,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":0.2}]}""");
        var before = EvidenceJsonSignature.Sorted(normal) + EvidenceJsonSignature.Sorted(window);
        var first = ledger.Compute([Input(normal)], [window]);
        check(Math.Abs(first.Totals["attacker"] - 100) < 1e-12 && Math.Abs(first.Totals["support"] - 20) < 1e-12,
            "The report ledger sums the hand-calculated 120/1.2 baseline and 20 external damage");
        check(first.InkSummary.Fields.Count == 0 && first.Hits[0].Evidence.Get("rdps_contributions") is EvidenceObject,
            "Ordinary report hits expose canonical contributions without an ink summary");
        var hits = new[] { 1200, 1000, 900, 899 }.Select(stamp => Input(Change(normal, ("ts_ms", new EvidenceInteger(stamp))))).ToArray();
        var backwards = ledger.Compute(hits, [window]);
        check(Math.Abs(backwards.Totals["attacker"] - 440) < 1e-10 && Math.Abs(backwards.Totals["support"] - 40) < 1e-10,
            "Backward time resets candidate cursors while inclusive starts retain the same accounting");
        check(before == EvidenceJsonSignature.Sorted(normal) + EvidenceJsonSignature.Sorted(window), "Ordered report accounting never mutates caller evidence");
        WindowState(check, allocator, ledger, normal, window);
        var records = new[] { Obj("""{"uid":"a","target_character_key":"attacker","ts_ms":900,"end_ts_ms":2000,"raw_duration_ms":100}"""),
            Obj("""{"uid":"b","target_character_key":"attacker","ts_ms":850,"end_ts_ms":950}"""),
            Obj("""{"uid":"invalid-bool","target_character_key":"attacker","ts_ms":true}"""),
            Obj("""{"uid":"invalid-fraction","target_character_key":"attacker","ts_ms":1.5}""") };
        AllocationConditionIndex conditions = new(records);
        check(conditions.At("attacker", 900).Select(row => ((EvidenceText)row.Get("uid")).Value).SequenceEqual(["a", "b"]),
            "Condition candidates retain original input order and reject boolean or fractional timestamps");
        check(conditions.At("attacker", 1000).Count == 1 && conditions.At("attacker", 1001).Count == 0 && conditions.At("attacker", 900).Count == 2,
            "Duration caps are inclusive and backward queries reconstruct expired conditions");
        var snapshotRecord = Obj("""{"uid":"snapshot","target_character_key":"attacker","target_actor_id":"1","ts_ms":900,"line_no":1,"snapshot_end_ts_ms":1000,"snapshot_end_line_no":20,"event_key":"observed"}""");
        var previousSnapshot = Change(snapshotRecord, ("uid", new EvidenceText("previous")), ("snapshot_end_ts_ms", new EvidenceText("950")));
        var uncapped = Change(snapshotRecord, ("uid", new EvidenceText("unknown")), ("snapshot_end_ts_ms", EvidenceNull.Value));
        AllocationConditionIndex snapshots = new([snapshotRecord, previousSnapshot, uncapped]);
        check(snapshots.At("attacker", 1000).SequenceEqual([snapshotRecord, uncapped])
            && snapshots.At("attacker", 1001).SequenceEqual([uncapped])
            && snapshots.At("attacker", 900).SequenceEqual([snapshotRecord, previousSnapshot, uncapped]),
            "Snapshot bounds expire historical candidates, retain unknown ends and restore original order after a backward query");
        var snapshotHit = Change(normal, ("line_no", new EvidenceInteger(19)),
            ("packet_modifier_uids", Obj("""{"attacker":["snapshot"]}""")));
        check(PacketAllocationEvidence.ActiveTargetBuffs(snapshotHit, snapshots.At("attacker", 1000), "attacker").SetEquals(["observed"])
            && PacketAllocationEvidence.ActiveTargetBuffs(Change(snapshotHit, ("line_no", new EvidenceInteger(20))),
                snapshots.At("attacker", 1000), "attacker").Count == 0
            && PacketAllocationEvidence.ActiveTargetBuffs(Change(snapshotHit, ("line_no", new EvidenceInteger(0))),
                snapshots.At("attacker", 1000), "attacker").Count == 0,
            "The inclusive snapshot candidate leaves same-millisecond packet line ordering and unknown-line exclusion to the evaluator");
        AllocationConditionIndex cappedSnapshots = new([Change(records[0], ("snapshot_end_ts_ms", new EvidenceInteger(950))),
            Change(records[0], ("snapshot_end_ts_ms", new EvidenceInteger(1500)))]);
        check(cappedSnapshots.At("attacker", 950).Count == 2 && cappedSnapshots.At("attacker", 951).Count == 1
            && cappedSnapshots.At("attacker", 1001).Count == 0,
            "Snapshot expiry takes the earliest known bound without extending the original duration cap");
        AllocationConditionIndex malformedSnapshots = new([Change(snapshotRecord, ("snapshot_end_ts_ms", new EvidenceReal(950.5))),
            Change(snapshotRecord, ("snapshot_end_ts_ms", new EvidenceBoolean(true)))]);
        check(malformedSnapshots.At("attacker", 1001).Count == 2,
            "Inexact or boolean snapshot bounds remain candidates for the original semantic validation");
        AllocationWindowIndex index = new([Change(window, ("start_ts_ms", new EvidenceText("900"))), window]);
        check(index.At(899).SequenceEqual([0]) && index.At(900).SequenceEqual([0, 1]) && index.At(1101).Count == 0,
            "Window indexing treats only exact integer bounds as known, leaving semantic validation to the evaluator");
        var scenario = InkProvenanceSpecs.Scenario();
        var source = Change(scenario.Hits[0], ("ts_ms", new EvidenceInteger(1000)), ("target_enemy_key", new EvidenceText("enemy")),
            ("hit_value", new EvidenceInteger(200)), ("source_actor_id", new EvidenceText("1")), ("damage_element", new EvidenceText("fire")));
        var explosion = Change(scenario.Hits[1], ("ts_ms", new EvidenceInteger(1000)), ("target_enemy_key", new EvidenceText("enemy")));
        var factorTwo = Change(window, ("zone_effects", ((EvidenceArray)Obj("""{"effects":[{"zone":"dmg_inc","element":"all","rate":1}]}""").Get("effects"))));
        var ink = ledger.Compute([Input(source), Input(explosion)], [factorTwo], scenario.Records, string.Join('\n', scenario.Lines));
        check(Math.Abs(ink.Totals["attacker"] - 100) < 2e-12 && Math.Abs(ink.Totals["support"] - 150) < 2e-12
            && Math.Abs(ink.Totals[InkProvenanceStream.Owner] - 50) < 2e-12,
            "The complete chain computes source 100/100 first, then gives 50/50 of the effective ink explosion to its recording and external zones");
        check(Math.Abs(ink.Totals.Values.Sum() - 300) < 2e-12 && ink.InkSummary.Get("resolved") is EvidenceInteger resolved && resolved.Value == 1,
            "The connected source-to-explosion report conserves all 300 effective damage and resolves the provenance");
        check(((EvidenceObject)ink.Hits[1].Evidence.Get("rdps_contributions")).Get("attacker") is EvidenceNull,
            "Explosion-time buffs cannot give the source attacker an invented reserved baseline");
        var empty = ledger.Compute([], []);
        check(empty.Hits.Count == 0 && empty.Totals.Count == 0 && empty.Windows.Count == 0, "Empty report allocation has no fabricated totals");
    }

    private static void WindowState(Action<bool, string> check, HitAllocator allocator, DamageShareLedger ledger,
        EvidenceObject normal, EvidenceObject window)
    {
        (EvidenceObject[] Hits, IReadOnlyList<EvidenceObject> Windows) FullReset(IReadOnlyList<ReportHitInput> inputs, IReadOnlyList<EvidenceObject> windows)
        {
            IReadOnlyList<EvidenceObject> current = windows.Select(value => (EvidenceObject)EvidenceJson.Clone(value)).ToArray();
            AllocationWindowIndex index = new(windows);
            List<EvidenceObject> hits = [];
            foreach (var input in inputs)
            {
                var result = allocator.Allocate(new(input, current, WindowIndices: index.At(EffectIdentity.Integer(input.Evidence.Get("ts_ms")))));
                hits.Add(Change(result.Hit, ("rdps_contributions", result.Allocation.Get("contributions_map"))));
                current = result.Windows;
            }
            return (hits.ToArray(), current);
        }
        void Compare(IReadOnlyList<ReportHitInput> inputs, IReadOnlyList<EvidenceObject> windows, string message)
        {
            var signature = windows.Select(EvidenceJsonSignature.Sorted).ToArray();
            var reference = FullReset(inputs, windows);
            var result = ledger.Compute(inputs, windows);
            check(result.Hits.Select(row => EvidenceJsonSignature.Sorted(row.Evidence)).SequenceEqual(reference.Hits.Select(EvidenceJsonSignature.Sorted))
                && result.Windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(reference.Windows.Select(EvidenceJsonSignature.Sorted)), message);
            check(windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(signature), "Window evaluation and reset keep caller evidence isolated");
            var transferred = ledger.ComputeOwned(inputs.Select(input => input with
                { Evidence = (EvidenceObject)EvidenceJson.Clone(input.Evidence) }).ToArray(),
                windows.Select(window => (EvidenceObject)EvidenceJson.Clone(window)).ToArray(), [], null, null, null);
            check(transferred.Hits.Select(row => EvidenceJsonSignature.Sorted(row.Evidence)).SequenceEqual(result.Hits.Select(row => EvidenceJsonSignature.Sorted(row.Evidence)))
                && transferred.Windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(result.Windows.Select(EvidenceJsonSignature.Sorted))
                && transferred.Totals.OrderBy(pair => pair.Key).SequenceEqual(result.Totals.OrderBy(pair => pair.Key)),
                "Private uncached reports preserve per-hit evidence, windows and totals across ordinary, recorded-ink and arts-provenance allocation");
        }
        var unresolved = Change(window, ("uid", new EvidenceText("unobserved")), ("requires_enable_observation", new EvidenceBoolean(true)));
        var independentlyAllocated = allocator.Allocate(new(Input(normal), new[] { unresolved }));
        var retainedWindows = independentlyAllocated.Windows.Select(EvidenceJsonSignature.Sorted).ToArray();
        var laterAllocation = allocator.Allocate(new(Input(Change(normal, ("ts_ms", new EvidenceInteger(1200)))), independentlyAllocated.Windows));
        check(independentlyAllocated.Windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(retainedWindows)
            && laterAllocation.Windows[0].Get("_buff_enabled_at_hit") is EvidenceNull,
            "A public per-hit allocation retains its window snapshot after another hit resets transient state");
        var retainedReport = ledger.Compute([Input(normal)], [unresolved]);
        var retainedReportSignature = retainedReport.Windows.Select(EvidenceJsonSignature.Sorted).ToArray();
        var laterReport = ledger.Compute([Input(Change(normal, ("ts_ms", new EvidenceInteger(1200))))], retainedReport.Windows);
        check(retainedReport.Windows.Select(EvidenceJsonSignature.Sorted).SequenceEqual(retainedReportSignature)
            && laterReport.Windows[0].Get("_buff_enabled_at_hit") is EvidenceNull,
            "A report owns its complete window buffer independently of later reports that use its output as input");
        var packetHit = Change(normal, ("packet_modifier_seen", new EvidenceBoolean(true)),
            ("packet_modifier_uids", Obj("""{"defender":["u"]}""")));
        var defender = Change(window, ("target_character_key", new EvidenceText("enemy")), ("target_actor_id", new EvidenceText("3")));
        Compare(new[] { 1000, 1200, 1000, 899 }.Select((stamp, index) => Input(Change(packetHit,
            ("ts_ms", new EvidenceInteger(stamp)), ("line_no", new EvidenceInteger(index + 10))))).ToArray(), [window, unresolved, defender],
            "Tracked resets match independent full resets across active, expired and backward hits with packet evaluation and persistent quality flags");
        var recorded = Change(normal, ("ts_ms", new EvidenceInteger(1200)), ("line_no", new EvidenceInteger(20)),
            ("_ink_allocation", Obj("""{"attacker":120}""")), ("ink_provenance", Obj("{}")));
        Compare([Input(normal), Input(recorded), Input(Change(normal, ("ts_ms", new EvidenceInteger(1201))))], [unresolved],
            "Recorded ink between ordinary hits does not discard the previous windows' transient reset state");
        var debuff = Change(defender, ("start_ts_ms", new EvidenceInteger(1000)),
            ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"vuln_taken","element":"all","rate":0.2,"arts_strength_provenance":true}]""")));
        var historicalArts = Change(window, ("uid", new EvidenceText("arts")), ("source_character_key", new EvidenceText("helper")),
            ("target_character_key", new EvidenceText("support")), ("start_ts_ms", new EvidenceInteger(800)), ("end_ts_ms", new EvidenceInteger(1000)),
            ("zone_effects", (EvidenceArray)EvidenceJson.Parse("""[{"zone":"arts_strength","element":"all","rate":30}]""")));
        var artsObserved = ledger.Compute([Input(Change(normal, ("ts_ms", new EvidenceInteger(1050))))], [debuff, historicalArts]);
        check(artsObserved.Windows[1].Get("_buff_enabled_at_hit") is EvidenceBoolean { Value: true },
            "The provenance fixture actually evaluates the expired arts window at debuff application time");
        Compare([Input(Change(normal, ("ts_ms", new EvidenceInteger(1050)))), Input(Change(normal, ("ts_ms", new EvidenceInteger(1200))))],
            [debuff, historicalArts], "Arts provenance evaluated outside current hit candidates is fully reset on the following hit");
        var cachedInputs = new[] { 1000, 1200, 1300 }.Select((stamp, index) => Input(Change(normal,
            ("ts_ms", new EvidenceInteger(stamp)), ("line_no", new EvidenceInteger(index * 10 + 10))))).ToArray();
        LiveAllocationCache cache = new();
        ledger.Compute(cachedInputs[..2], [window], cache: cache);
        var appended = ledger.Compute(cachedInputs, [window], cache: cache);
        check(cache.Diagnostics.ReusedHits > 0 && appended.Windows.Select(EvidenceJsonSignature.Sorted)
            .SequenceEqual(FullReset(cachedInputs, [window]).Windows.Select(EvidenceJsonSignature.Sorted)),
            "A reused hit prefix and newly evaluated suffix retain the same final transient window state");
    }
}
