using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveHitAccountingSpecs
{
    private static ReportHitInput Input(string json) => new((EvidenceObject)FrozenEvidence.Capture(EvidenceJson.Parse(json)),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    private static ReportHitInput Change(ReportHitInput row, string key, EvidenceValue value)
        => row with { Evidence = (EvidenceObject)FrozenEvidence.Capture(new EvidenceObject(new Dictionary<string, EvidenceValue>(row.Evidence.Fields) { [key] = value })) };

    public static void Run(Action<bool, string> check)
    {
        BasisCheckpoints(check);
        var one = Input("""{"ts_ms":1000,"line_no":10,"seq":1,"hit_value":100,"rdps_contributions":{"a":80,"b":20},"packet_hit_value":100,"damage_element":"fire","damage_element_source":"official_action_unit","damage_school":"spell","target_enemy_key":"eny_test"}""");
        var two = Change(Change(one, "ts_ms", new EvidenceInteger(2000)), "line_no", new EvidenceInteger(20));
        var three = Change(Change(one, "ts_ms", new EvidenceInteger(3000)), "line_no", new EvidenceInteger(30));
        LiveAllocationCache cache = new();
        cache.FinishOwned([one, two]); var initial = cache.ContributionTotalsOwned([one, two]);
        var prepared = cache.HitAccounting.PreparedHits;
        cache.FinishOwned([one, two, three]); var appended = cache.ContributionTotalsOwned([one, two, three]);
        check(cache.HitAccounting.PreparedHits == prepared + 1 && cache.HitAccounting.UnchangedPrefix == 2
            && cache.Diagnostics.FinalizedHits == 2 && cache.Diagnostics.PendingStartLine == 30
            && appended["a"] == 240 && initial["a"] == 160 && cache.HitAccounting.BlockerCount == 0,
            "An append prepares only its new immutable hit, advances the pending frame and leaves older contribution snapshots unchanged");
        var revised = Change(two, "rdps_contributions", EvidenceJson.Parse("""{"a":10,"c":90}"""));
        cache.FinishOwned([one, revised, three]); var changed = cache.ContributionTotalsOwned([one, revised, three]);
        check(cache.HitAccounting.UnchangedPrefix == 1 && changed["a"] == 170 && changed["b"] == 40 && changed["c"] == 90
            && cache.Maxima["c"] == 90 && appended["a"] == 240,
            "A late contribution revision retracts the affected suffix and maxima without changing an earlier published total");
        cache.FinishOwned([one]); var shortened = cache.ContributionTotalsOwned([one]);
        cache.FinishOwned([]); var empty = cache.ContributionTotalsOwned([]);
        check(shortened["a"] == 80 && !shortened.ContainsKey("c") && empty.Count == 0 && cache.Maxima.Count == 0
            && cache.Diagnostics.FinalizedHits == 0 && cache.Diagnostics.PendingStartLine is null,
            "Truncation and an empty selection retract contribution, maximum and finalization checkpoints together");
        var unresolved = Change(two, "rdps_unresolved_effect_conditions", new EvidenceBoolean(true));
        cache.FinishOwned([one, unresolved, three]);
        check(cache.Diagnostics.FinalizedHits == 1 && cache.HitAccounting.BlockerCount == 1,
            "An unresolved middle hit keeps its following suffix pending and retains the exact semantic blocker count");
        var staticOnly = Change(one, "rdps_unresolved_static_multiplier_sources", EvidenceJson.Parse("""[{"source":"unobserved"}]"""));
        cache.FinishOwned([staticOnly, two, three]);
        check(cache.Diagnostics.FinalizedHits == 2 && cache.HitAccounting.BlockerCount == 1,
            "Static source uncertainty remains visible to preflight without changing the existing finalization exception");
        cache.FinishOwned([one, two, three]);
        check(cache.HitAccounting.BlockerCount == 0 && cache.Diagnostics.FinalizedHits == 2,
            "A later correction removes obsolete blockers and restores the exact finalization frontier");
        var multiple = Change(unresolved, "rdps_unresolved_target_binding", new EvidenceBoolean(true));
        foreach (var hits in new ReportHitInput[][] { [staticOnly, multiple], [staticOnly, multiple, three],
            [one, multiple, three], [one], [], [multiple, staticOnly] })
        {
            cache.FinishOwned(hits);
            check(cache.HitAccounting.BlockerCount == hits.Sum(row => AllocationPreflight.HitBlockers(row.Evidence).Count),
                "Blocker checkpoints equal complete hit evidence after append, late correction, truncation, clear and reordered input");
        }

        var sameTime = Change(three, "ts_ms", new EvidenceInteger(2000));
        var backdated = Change(three, "ts_ms", new EvidenceInteger(500));
        foreach (var hits in new ReportHitInput[][] { [one, two, sameTime], [one, backdated, two], [three, one, two], [], [one] })
        {
            LiveAllocationCache reference = new(); reference.Finish(hits); cache.FinishOwned(hits);
            check(reference.Diagnostics.FinalizedHits == cache.Diagnostics.FinalizedHits && reference.Diagnostics.PendingStartLine == cache.Diagnostics.PendingStartLine,
                "Finalization preserves the first maximum-time boundary, original row order and empty-range semantics");
        }
        var floating = Change(one, "ts_ms", new EvidenceReal(1000.5));
        cache.FinishOwned([floating, two]); LiveAllocationCache fallback = new(); fallback.Finish([floating, two]);
        check(cache.HitAccounting.FinalizedCount is null && cache.Diagnostics.FinalizedHits == fallback.Diagnostics.FinalizedHits,
            "Noninteger timestamps retain the original comparison algorithm rather than silently truncating evidence");
        cache.Finish([one]); cache.ContributionTotals([one]); cache.FinishOwned([two]);
        check(cache.ContributionTotalsOwned([two])["a"] == 80 && cache.HitAccounting.UnchangedPrefix == 0,
            "Interleaving a public allocation invalidates the private accounting frontier");

        long AppendCost(int count)
        {
            var hits = Enumerable.Range(0, count + 1).Select(index => Change(one, "ts_ms", new EvidenceInteger(index))).ToArray();
            LiveAllocationCache sized = new(); sized.FinishOwned(hits[..count]);
            var before = sized.HitAccounting.PreparedHits; sized.FinishOwned(hits);
            return sized.HitAccounting.PreparedHits - before;
        }
        check(AppendCost(8) == 1 && AppendCost(1024) == 1,
            "The same append evaluates one hit-local verdict after short or long completed history");
    }

    private static void BasisCheckpoints(Action<bool, string> check)
    {
        var one = Input("""{"ts_ms":1,"line_no":1,"hit_value":100,"rdps_contributions":{"a":80,"b":20},"packet_hit_value":0,"packet_final_value":-120,"packet_raw_value":-150,"overkill_damage":20}""");
        var two = Change(Change(one, "ts_ms", new EvidenceInteger(2)), "line_no", new EvidenceInteger(2));
        var three = Change(Change(one, "ts_ms", new EvidenceInteger(3)), "line_no", new EvidenceInteger(3));
        LiveAllocationCache cache = new();
        EvidenceObject Analyze(params ReportHitInput[] hits)
        {
            cache.FinishOwned(hits);
            var totals = cache.ContributionTotalsOwned(hits);
            var actual = cache.HitAccounting.BuildBasis(totals);
            var expected = DamageBasis.Build(hits.Select(row => row.Evidence).ToArray(),
                totals.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value)),
                EndfieldLogs.Core.Effects.EffectIdentity.Integer(PythonNumericSum.Sum(hits.Select(row => row.Evidence.Fields["hit_value"]))));
            check(EvidenceJsonSignature.Sorted(actual) == EvidenceJsonSignature.Sorted(expected),
                "Incremental packet counts, sums and conservation verdicts equal a complete report after an append or retraction");
            return actual;
        }
        Analyze(one, two);
        var prepared = cache.HitAccounting.BasisPreparedHits;
        var appended = Analyze(one, two, three);
        check(cache.HitAccounting.BasisPreparedHits == prepared + 1
            && appended.Get("total_packet_final_value") is EvidenceReal { Value: -360 }
            && appended.Get("packet_grounded_hit_count") is EvidenceInteger { Value: var count } && count == 3,
            "Appending one immutable hit updates one checkpoint while preserving grounded zero and signed packet values");
        Analyze(one, Change(two, "rdps_contributions", EvidenceJson.Parse("""{"a":50}""")), three);
        Analyze(one);
        Analyze();
        Analyze(one, two);
        var unchanged = cache.HitAccounting.BasisPreparedHits;
        Analyze(one, two);
        check(cache.HitAccounting.BasisPreparedHits == unchanged,
            "An unchanged summary does not rescan old packet or conservation fields");

        ReportHitInput FloatingHit(double value, int index)
        {
            var row = Change(Change(one, "ts_ms", new EvidenceInteger(index)), "hit_value", new EvidenceReal(value));
            return Change(row, "rdps_contributions", new EvidenceObject(new Dictionary<string, EvidenceValue> { ["a"] = new EvidenceReal(value) }));
        }
        var cancel = new[] { 1e16, 1, -1e16 }.Select(FloatingHit).ToArray();
        Analyze(cancel[..1]); Analyze(cancel[..2]);
        check(Analyze(cancel).Get("total_damage") is EvidenceInteger { Value: var total } && total == 1,
            "A resumed numeric sum retains compensation rather than adding rounded prefix totals");
        var nonfinite = Change(Change(one, "packet_final_value", new EvidenceReal(double.NaN)), "packet_raw_value", new EvidenceReal(double.PositiveInfinity));
        Analyze(nonfinite); Analyze(nonfinite, two);
        var huge = BigInteger.Pow(10, 100);
        var wide = Change(one, "hit_value", new EvidenceInteger(huge));
        var opposite = Change(two, "hit_value", new EvidenceInteger(-huge));
        Analyze(wide, opposite);
        check(Analyze(wide, opposite, Change(three, "hit_value", new EvidenceReal(.5))).Get("total_damage") is EvidenceInteger { Value.IsZero: true },
            "Exact wide integer cancellation precedes the first real value and keeps existing total-damage truncation");

        long Cost(int length)
        {
            var hits = Enumerable.Range(0, length + 1).Select(index => Change(one, "ts_ms", new EvidenceInteger(index))).ToArray();
            LiveAllocationCache sized = new();
            sized.FinishOwned(hits[..length]); sized.HitAccounting.BuildBasis(sized.ContributionTotalsOwned(hits[..length]));
            var old = sized.HitAccounting.BasisPreparedHits;
            sized.FinishOwned(hits); sized.HitAccounting.BuildBasis(sized.ContributionTotalsOwned(hits));
            return sized.HitAccounting.BasisPreparedHits - old;
        }
        check(Cost(8) == 1 && Cost(1024) == 1,
            "Packet summary work for the same append is independent of the completed history length");
    }
}
