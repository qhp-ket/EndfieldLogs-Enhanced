using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveAllocationSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject input, params (string Key, EvidenceValue Value)[] changes)
    {
        var fields = new Dictionary<string, EvidenceValue>(input.Fields);
        foreach (var (key, value) in changes) fields[key] = value;
        return new(fields);
    }
    private static ReportHitInput Input(EvidenceObject hit) => new(hit, new Dictionary<BigInteger, EvidenceValue>(),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    public static void Run(Action<bool, string> check)
    {
        ContributionRewind(check);
        UnboundedTimes(check);
        LiveHitAccountingSpecs.Run(check);
        AllocationDebug debug = new(key => key);
        HitAllocator allocator = new(new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>())),
            new(new Dictionary<string, EvidenceObject>()), new(new Dictionary<string, EvidenceObject>()), new(debug), new(debug), new(debug, row => new(row, [])));
        DamageShareLedger ledger = new(allocator, new Dictionary<string, EvidenceObject>());
        var one = Obj("""{"character_key":"attacker","target_enemy_key":"enemy","source_actor_id":"1","target_actor_id":"3","hit_value":120,"ts_ms":1000,"line_no":10,"damage_element":"fire","damage_school":"spell"}""");
        var two = Change(one, ("ts_ms", new EvidenceInteger(2000)), ("line_no", new EvidenceInteger(20)));
        var three = Change(one, ("ts_ms", new EvidenceInteger(3000)), ("line_no", new EvidenceInteger(30)));
        var window = Obj("""{"uid":"u","event_key":"buff","source_character_key":"support","target_character_key":"attacker","target_actor_id":"1","start_ts_ms":900,"end_ts_ms":4000,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":0.2}]}""");
        OwnedReportReuse(check, ledger, one, two, three, window);
        OwnedSuffixRewind(check, ledger, one, two, three, window);
        LiveAllocationCache cache = new();
        ledger.Compute([Input(one), Input(two)], [window], cache: cache);
        var appended = ledger.Compute([Input(one), Input(two), Input(three)], [window], cache: cache);
        check(cache.Diagnostics is { AllocatedHits: 1, ReusedHits: 2, FinalizedHits: 2, PendingStartLine: var line } && line == 30
            && Math.Abs(appended.Totals["support"] - 60) < 1e-11,
            "Appending one hit reuses the exact prefix while keeping the newest observed frame pending");
        var changed = Change(window, ("zone_effects", new EvidenceArray([Obj("""{"zone":"dmg_inc","element":"all","rate":0.5}""")])));
        var revised = ledger.Compute([Input(one), Input(two), Input(three)], [changed], cache: cache);
        check(cache.Diagnostics is { AllocatedHits: 3, ReusedHits: 0, Replays: 1 }
            && Math.Abs(revised.Totals["support"] - 120) < 1e-11 && Math.Abs(revised.Totals["attacker"] - 240) < 1e-11,
            "A changed multiplier behind the frontier retracts old credit and recomputes the hand-calculated 120/1.5 baseline");
        var late = Change(one, ("ts_ms", new EvidenceInteger(1500)), ("line_no", new EvidenceInteger(40)));
        ledger.Compute([Input(one), Input(two), Input(three), Input(late)], [changed], cache: cache);
        check(cache.Diagnostics is { Replays: 2, LastReplayReason: "late damage arrived behind the finalized frontier" },
            "Late damage behind a finalized frame replays allocations without reparsing the trace");
        var baselineChange = Input(one) with { Baseline = new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceReal(1) } };
        ledger.Compute([baselineChange, Input(two), Input(three)], [changed], cache: cache);
        check(cache.Diagnostics is { Replays: 3, LastReplayReason: "finalized hit identity or hit-time context changed" },
            "Integer-key baseline changes invalidate reuse even when the display JSON did not change");
        var nanInput = Input(one) with { Baseline = new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceReal(double.NaN) } };
        LiveAllocationCache nanCache = new();
        ledger.Compute([nanInput, Input(two)], [], cache: nanCache);
        var nanResult = ledger.Compute([nanInput, Input(two), Input(three)], [], cache: nanCache);
        var nanReference = ledger.Compute([nanInput, Input(two), Input(three)], []);
        check(nanCache.Diagnostics is { Replays: 1, LastReplayReason: "finalized hit identity or hit-time context changed" }
            && nanResult.Hits.Zip(nanReference.Hits).All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "A scalar NaN baseline invalidates finalized reuse even when callers retain the same numeric map");
        ledger.Compute([Input(one)], [], cache: cache);
        check(Math.Abs(cache.Maxima["attacker"] - 120) < 1e-11 && !cache.Maxima.ContainsKey("support"),
            "Contribution prefix retraction removes obsolete support maxima as well as totals");
        ((Dictionary<string, double>)cache.Maxima)["attacker"] = -1;
        check(cache.Maxima["attacker"] == 120, "Consumers cannot mutate the cached contribution maxima");
        var output = ledger.Compute([Input(one)], [], cache: cache);
        ((Dictionary<string, EvidenceValue>)output.Hits[0].Evidence.Fields)["hit_value"] = new EvidenceInteger(-1);
        check(ledger.Compute([Input(one)], [], cache: cache).Hits[0].Evidence.Get("hit_value") is EvidenceInteger { Value: var value } && value == 120,
            "Editing a returned allocation cannot change a later reused hit");
        LiveAllocationCache detached = new();
        var mutableWindow = (EvidenceObject)EvidenceJson.Clone(window);
        ledger.Compute([Input(one), Input(two)], [mutableWindow], cache: detached);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)mutableWindow.Get("zone_effects")).Items[0]).Fields)["rate"] = new EvidenceReal(.5);
        var afterMutation = ledger.Compute([Input(one), Input(two), Input(three)], [mutableWindow], cache: detached);
        check(detached.Diagnostics.Replays == 1 && Math.Abs(afterMutation.Totals["support"] - 120) < 1e-11,
            "Unchanged dependency reuse remains detached from later in-place caller changes and replays affected finalized credit");
        var nested = Obj("""{"values":[1,2]}""");
        var mutableNumbers = new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceReal(1) };
        var retainedInput = Input(Change(one, ("observation_details", nested))) with
        {
            Baseline = new System.Collections.ObjectModel.ReadOnlyDictionary<BigInteger, EvidenceValue>(mutableNumbers),
        };
        LiveAllocationCache retained = new();
        ledger.Compute([retainedInput, Input(two)], [], cache: retained);
        ((IList<EvidenceValue>)((EvidenceArray)nested.Get("values")).Items)[0] = new EvidenceInteger(9);
        mutableNumbers[999] = new EvidenceReal(2);
        var retainedNext = ledger.Compute([retainedInput, Input(two), Input(three)], [], cache: retained);
        var retainedReference = ledger.Compute([retainedInput, Input(two), Input(three)], []);
        check(retained.Diagnostics is { Replays: 1, LastReplayReason: "finalized hit identity or hit-time context changed" }
            && retainedNext.Hits.Zip(retainedReference.Hits).All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "Remembered inputs detach nested caller evidence and readonly wrappers around mutable numeric maps before detecting late edits");
        ((IList<EvidenceValue>)((EvidenceArray)((EvidenceObject)retainedNext.Hits[0].Evidence.Get("observation_details")).Get("values")).Items)[0] = EvidenceNull.Value;
        var retainedAgain = ledger.Compute([retainedInput, Input(two), Input(three)], [], cache: retained);
        check(retained.Diagnostics.ReusedHits == 3 && retainedAgain.Hits.Zip(retainedReference.Hits)
            .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "Public cached results remain independently mutable after their original inputs are retained as immutable snapshots");
        var unknown = Change(one, ("rdps_unresolved_actor", new EvidenceBoolean(true)));
        LiveAllocationCache unresolved = new();
        ledger.Compute([Input(unknown), Input(two)], [], cache: unresolved);
        check(unresolved.Diagnostics is { FinalizedHits: 0, PendingStartLine: var pending } && pending == 10,
            "An unresolved first hit keeps the entire following suffix pending");
        DependencyTransitions(check, ledger, one, two, three, window);
        var scenario = InkProvenanceSpecs.Scenario();
        LiveAllocationCache ink = new();
        var roots = new Dictionary<string, EvidenceObject> { [InkProvenanceStream.Buff] = InkProvenanceSpecs.Root() };
        var relevant = scenario.Lines.Select((line, index) => line.Replace(index == 1 ? " SOURCE" : index == 6 ? " EXPLOSION" : " UNMATCHED",
            index is 1 or 6 ? " HP_V2 synthetic" : " UNMATCHED", StringComparison.Ordinal)).ToArray();
        ink.ApplyInk(string.Join('\n', relevant.Take(4)), [Input(scenario.Hits[0])], scenario.Records, roots);
        var complete = ink.ApplyInk(string.Join('\n', relevant), scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        var shares = (EvidenceObject)complete.Hits[1].Get("rdps_contributions");
        check(shares.Get("support") is EvidenceReal { Value: var support } && Math.Abs(support - 50) < 1e-10
            && complete.Summary.Get("resolved") is EvidenceInteger { Value: var resolved } && resolved == 1,
            "A source recorded before the next snapshot remains available to the continuing frozen ink release");
        var repeated = ink.ApplyInk(string.Join('\n', relevant), scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        check(EvidenceJson.PythonEquals(repeated.Hits[1], complete.Hits[1]) && EvidenceJson.PythonEquals(repeated.Summary, complete.Summary),
            "Re-reading an explosion restores its cached evidence without consuming the projectile twice");
        StructuredInk(check, roots, allocator);
    }

    private static void ContributionRewind(Action<bool, string> check)
    {
        ReportHitInput Row(string fields) => Input(new EvidenceObject(new Dictionary<string, EvidenceValue>
            { ["rdps_contributions"] = Obj(fields) }));
        var first = Row("""{"alpha":1}""");
        LiveAllocationCache cache = new();
        var original = cache.ContributionTotals([first, Row("""{"alpha":1e16,"removed":2}"""),
            Row("""{"alpha":-1e16,"removed":3,"last":4}""")]);
        var truncated = cache.ContributionTotals([first]);
        check(truncated.Keys.SequenceEqual(["alpha"]) && truncated["alpha"] == 1 && cache.Maxima["alpha"] == 1
            && original["alpha"] == 0 && original["removed"] == 5 && original["last"] == 4,
            "Contribution rewind restores the exact earlier floating sum and maxima without subtracting large cancelling credits or mutating published totals");
        var replacement = Row("""{"zeta":2,"beta":3,"alpha":-5}""");
        var revised = cache.ContributionTotals([first, replacement]);
        ((Dictionary<string, double>)revised)["alpha"] = 99;
        var again = cache.ContributionTotals([first, replacement]);
        check(again.Keys.SequenceEqual(["alpha", "zeta", "beta"]) && cache.Maxima.Keys.SequenceEqual(again.Keys)
            && again["alpha"] == -4 && cache.Maxima["alpha"] == 1 && !again.ContainsKey("removed"),
            "Replacing a retracted suffix keeps first-appearance order and independent editable snapshots while discarding obsolete contributors");
        var cleared = cache.ContributionTotals([]);
        check(cleared.Count == 0 && cache.Maxima.Count == 0 && again["alpha"] == -4,
            "An empty contribution history retracts every retained statistic without changing older snapshots");
    }

    private static void UnboundedTimes(Action<bool, string> check)
    {
        var finite = Input((EvidenceObject)FrozenEvidence.Capture(Obj("""{"ts_ms":1000,"line_no":1}""")));
        var infinite = Input((EvidenceObject)FrozenEvidence.Capture(Obj("""{"ts_ms":Infinity,"line_no":1}""")));
        LiveAllocationCache Cache(ReportHitInput input)
        {
            LiveAllocationCache cache = new();
            cache.Begin([input], [], []); cache.Remember(input, input.Evidence); cache.Finish([input]);
            return cache;
        }
        var changed = Cache(finite);
        changed.BeginOwned([infinite], [], []);
        check(changed.ReuseOwned(infinite) is null,
            "An unbounded private prefix still compares input identity when an integer timestamp changes to infinity");
        var nonfinite = Cache(infinite);
        nonfinite.BeginOwned([infinite], [], []);
        check(nonfinite.ReuseOwned(infinite) is null,
            "A retained infinite timestamp keeps the original cutoff comparison rather than using integer-time reuse");
    }

    private static void OwnedReportReuse(Action<bool, string> check, DamageShareLedger ledger,
        EvidenceObject one, EvidenceObject two, EvidenceObject three, EvidenceObject window)
    {
        ReportHitInput Protect(EvidenceObject hit) => Input((EvidenceObject)FrozenEvidence.Capture(hit)) with
        {
            Baseline = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceInteger(1) }),
            BasicAttributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
            Attributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
        };
        ReportHitInput[] source = [Protect(one), Protect(two), Protect(three)];
        LiveAllocationCache cache = new();
        DamageShareResult Calculate(ReportHitInput[] hits, EvidenceObject[] windows) => ledger.ComputeOwned(hits,
            windows, [], null, cache, null, summary: true);
        Calculate(source[..2], [window]);
        var stable = Calculate(source[..2], [window]);
        var unchanged = Calculate(source[..2], [window]);
        check(cache.Diagnostics is { ReusedHits: 2, AllocatedHits: 0 }
            && ReferenceEquals(stable.Hits[0], unchanged.Hits[0]) && ReferenceEquals(stable.Hits[1], unchanged.Hits[1]),
            "Unchanged private summaries reuse complete immutable hit projections without allocating new wrappers");
        var appended = Calculate(source, [window]);
        var cold = ledger.Compute(source, [window]);
        check(cache.Diagnostics is { ReusedHits: 2, AllocatedHits: 1 }
            && ReferenceEquals(stable.Hits[0], appended.Hits[0]) && ReferenceEquals(stable.Hits[1], appended.Hits[1])
            && appended.Hits.Zip(cold.Hits).All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence))
            && appended.Totals.All(pair => cold.Totals[pair.Key] == pair.Value) && source[0].Evidence.Get("rdps_contributions") is EvidenceNull,
            "Appending to a reused summary still prepares the new allocation indexes and equals a cold public report without modifying its source");
        var newMap = source[0] with
        {
            Baseline = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceReal(1) }),
        };
        var replaced = Calculate([newMap, source[1], source[2]], [window]);
        check(cache.Diagnostics.ReusedHits == 3 && ReferenceEquals(replaced.Hits[0].Baseline, newMap.Baseline)
            && replaced.Hits[0].Baseline[999] is EvidenceReal && stable.Hits[0].Baseline[999] is EvidenceInteger
            && !ReferenceEquals(replaced.Hits[0], appended.Hits[0]),
            "An equal replacement numeric map keeps its current scalar type and ownership rather than retaining an older cached wrapper");
        var changed = Change(window, ("zone_effects", EvidenceJson.Parse("""[{"zone":"dmg_inc","element":"all","rate":0.5}]""")));
        var revised = Calculate(source, [changed]);
        var expected = ledger.Compute(source, [changed]);
        check(cache.Diagnostics.Replays == 1 && revised.Hits.Zip(expected.Hits)
            .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence))
            && stable.Totals["support"] == 40 && revised.Totals["support"] == 120,
            "Late multiplier changes invalidate reused projections and preserve previously published contribution snapshots");
        var editable = ledger.Compute(source, [window], cache: cache);
        ((Dictionary<string, EvidenceValue>)editable.Hits[0].Evidence.Fields)["hit_value"] = new EvidenceInteger(-1);
        var restored = Calculate(source, [window]);
        check(restored.Hits.Zip(cold.Hits).All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence))
            && restored.Hits[0].Evidence.Fields is not Dictionary<string, EvidenceValue>,
            "Switching between editable public reports and private summaries cannot expose or poison retained immutable projections");
        var nan = source[0] with
        {
            Baseline = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue> { [999] = new EvidenceReal(double.NaN) }),
        };
        LiveAllocationCache nanCache = new();
        ledger.ComputeOwned([nan, source[1]], [], [], null, nanCache, null, summary: true);
        var nanResult = ledger.ComputeOwned([nan, source[1], source[2]], [], [], null, nanCache, null, summary: true);
        var nanExpected = ledger.Compute([nan, source[1], source[2]], []);
        check(nanCache.Diagnostics.Replays == 1 && nanResult.Hits.Zip(nanExpected.Hits)
            .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "Even an identical recursively immutable input retains scalar NaN invalidation rather than skipping its numeric comparison");
    }

    private static void OwnedSuffixRewind(Action<bool, string> check, DamageShareLedger ledger,
        EvidenceObject one, EvidenceObject two, EvidenceObject three, EvidenceObject window)
    {
        ReportHitInput Protect(EvidenceObject hit) => Input((EvidenceObject)FrozenEvidence.Capture(hit)) with
        {
            Baseline = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
            BasicAttributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
            Attributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
        };
        var four = Change(one, ("ts_ms", new EvidenceInteger(4000)), ("line_no", new EvidenceInteger(40)));
        ReportHitInput[] hits = [Protect(one), Protect(two), Protect(three), Protect(four)];
        LiveAllocationCache cache = new();
        DamageShareResult Calculate(ReportHitInput[] source, params EvidenceObject[] windows) =>
            ledger.ComputeOwned(source, windows, [], null, cache, null, summary: true);
        void MatchesCold(DamageShareResult actual, ReportHitInput[] source, params EvidenceObject[] windows)
        {
            var cold = ledger.Compute(source, windows);
            check(actual.Hits.Count == cold.Hits.Count && actual.Hits.Zip(cold.Hits)
                .All(pair => EvidenceJsonSignature.Sorted(pair.First.Evidence) == EvidenceJsonSignature.Sorted(pair.Second.Evidence))
                && actual.Totals.Count == cold.Totals.Count && actual.Totals.All(pair => cold.Totals[pair.Key] == pair.Value),
                "A private suffix rewind preserves complete hit evidence, contribution order and totals from a cold allocation");
        }
        var original = Change(window, ("end_ts_ms", new EvidenceInteger(2500)));
        Calculate(hits, original);
        var stable = Calculate(hits, original);
        var extended = Change(original, ("end_ts_ms", new EvidenceInteger(3500)));
        var afterExtension = Calculate(hits, extended);
        check(cache.Diagnostics is { Replays: 1, ReusedHits: 2, AllocatedHits: 2, FinalizedHits: 3 }
            && ReferenceEquals(stable.Hits[0], afterExtension.Hits[0]) && ReferenceEquals(stable.Hits[1], afterExtension.Hits[1])
            && stable.Totals["support"] == 40 && afterExtension.Totals["support"] == 60,
            "Extending a past window retracts from its old end and preserves earlier finalized immutable hits and published totals");
        MatchesCold(afterExtension, hits, extended);
        var contracted = Change(original, ("end_ts_ms", new EvidenceInteger(1500)));
        var afterContraction = Calculate(hits, contracted);
        check(cache.Diagnostics is { Replays: 2, ReusedHits: 1, AllocatedHits: 3 }
            && afterContraction.Totals["support"] == 20 && cache.Maxima["attacker"] == 120,
            "An earlier end retracts the newly affected finalized suffix, including contribution maxima");
        MatchesCold(afterContraction, hits, contracted);
        var changed = hits[1] with
        {
            Evidence = (EvidenceObject)FrozenEvidence.Capture(Change(two, ("hit_value", new EvidenceInteger(240)))),
        };
        ReportHitInput[] revised = [hits[0], changed, hits[2], hits[3]];
        var afterIdentityChange = Calculate(revised, contracted);
        check(cache.Diagnostics is { Replays: 3, ReusedHits: 1, AllocatedHits: 3 },
            "A changed finalized hit preserves only the preceding verified inputs and reallocates the complete following suffix");
        MatchesCold(afterIdentityChange, revised, contracted);
        var late = Protect(Change(one, ("ts_ms", new EvidenceInteger(1500)), ("line_no", new EvidenceInteger(50))));
        ReportHitInput[] backdated = [.. revised, late];
        var afterLateDamage = Calculate(backdated, contracted);
        check(cache.Diagnostics is { Replays: 4, ReusedHits: 0, AllocatedHits: 5,
            LastReplayReason: "late damage arrived behind the finalized frontier" },
            "Backdated appended damage retains the conservative complete reset rather than assuming timestamp order");
        MatchesCold(afterLateDamage, backdated, contracted);

        var early = Change(contracted, ("uid", new EvidenceText("early")), ("start_ts_ms", new EvidenceInteger(100)),
            ("end_ts_ms", new EvidenceInteger(500)));
        Calculate(hits, early, contracted);
        var reordered = Calculate(hits, contracted, early);
        check(cache.Diagnostics.ReusedHits == 0 && cache.Diagnostics.LastReplayReason == "semantic evidence changed behind the finalized frontier",
            "Reordered dependencies with an unbounded cutoff still reset every allocation");
        MatchesCold(reordered, hits, contracted, early);
    }

    private static void DependencyTransitions(Action<bool, string> check, DamageShareLedger ledger,
        EvidenceObject one, EvidenceObject two, EvidenceObject three, EvidenceObject window)
    {
        var future = Change(window, ("uid", new EvidenceText("future")), ("start_ts_ms", new EvidenceInteger(9000)),
            ("end_ts_ms", new EvidenceInteger(10000)));
        ReportHitInput[] hits = [Input(one), Input(two), Input(three)];
        LiveAllocationCache cache = new();
        ledger.Compute(hits[..2], [window], cache: cache);
        ledger.Compute(hits, [window, future], cache: cache);
        var identities = cache.DependencyIdentitiesBuilt;
        var comparisons = cache.ComparedHitInputs;
        ledger.Compute(hits, [window, future], cache: cache);
        check(cache.Diagnostics is { Replays: 0, ReusedHits: 3 } && cache.DependencyIdentitiesBuilt == identities
            && cache.ComparedHitInputs - comparisons == 3,
            "Unchanged dependency identities retain their index and each cached hit is compared only once");
        ledger.Compute(hits, [window], cache: cache);
        var replaced = Change(future, ("uid", new EvidenceText("replacement")));
        ledger.Compute(hits, [window, replaced], cache: cache);
        ledger.Compute(hits, [window, future], cache: cache);
        check(cache.Diagnostics is { Replays: 0, ReusedHits: 3 },
            "Removing, adding or replacing a future dependency preserves the unaffected finalized prefix");
        ledger.Compute(hits, [future, window], cache: cache);
        check(cache.Diagnostics is { Replays: 1, LastReplayReason: "semantic evidence changed behind the finalized frontier" },
            "Dependency reordering retains the original conservative replay even after suffix index entries were replaced");
        ledger.Compute(hits, [future, window, window], cache: cache);
        var repeated = ledger.Compute(hits, [future, window, window], cache: cache);
        check(cache.Diagnostics is { Replays: 2, ReusedHits: 3 }
            && repeated.Hits.Zip(ledger.Compute(hits, [future, window, window]).Hits)
                .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "Adding a duplicate identity replays conservatively; unchanged duplicate evidence can subsequently be reused");
        var revised = Change(window, ("zone_effects", new EvidenceArray([Obj("""{"zone":"dmg_inc","element":"all","rate":0.5}""")])));
        var changed = ledger.Compute(hits, [future, revised, window], cache: cache);
        check(cache.Diagnostics.Replays == 3 && changed.Hits.Zip(ledger.Compute(hits, [future, revised, window]).Hits)
                .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
            "Changing one duplicate retains complete evidence comparison and retracts the old contribution");

        (long Identities, long Rebuilds) AppendCost(int count)
        {
            var records = Enumerable.Range(0, count).Select(index => Obj($"{{\"uid\":\"r{index}\",\"ts_ms\":9000}}")).ToArray();
            LiveAllocationCache bounded = new();
            ledger.Compute(hits, [], records, cache: bounded);
            ledger.Compute(hits, [], records, cache: bounded);
            var oldIdentities = bounded.DependencyIdentitiesBuilt;
            var oldRebuilds = bounded.DependencyIndexRebuilds;
            ledger.Compute(hits, [], [.. records, Obj("""{"uid":"new","ts_ms":10000}""")], cache: bounded);
            return (bounded.DependencyIdentitiesBuilt - oldIdentities, bounded.DependencyIndexRebuilds - oldRebuilds);
        }
        check(AppendCost(8) == (1, 0) && AppendCost(512) == (1, 0),
            "The same appended dependency builds one identity and no complete index after either short or long completed history");
    }

    private static void StructuredInk(Action<bool, string> check, IReadOnlyDictionary<string, EvidenceObject> roots, HitAllocator allocator)
    {
        var scenario = InkProvenanceSpecs.Scenario();
        var events = InkProvenanceSpecs.Events();
        InkObservationLog log = new();
        LiveAllocationCache cache = new();
        for (var index = 0; index < 4; index++) log.Observe(index + 1, events[index]);
        var prefix = log.Capture();
        cache.ApplyInk(prefix, [Input(scenario.Hits[0])], scenario.Records, roots);
        for (var index = 4; index < events.Length; index++) log.Observe(index + 1, events[index]);
        var input = log.Capture();
        var complete = cache.ApplyInk(input, scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        var expected = InkProvenanceStream.Apply(string.Join('\n', scenario.Lines), scenario.Hits, scenario.Records, roots);
        ReportHitInput FrozenInput(EvidenceObject hit) => Input((EvidenceObject)FrozenEvidence.Capture(hit));
        LiveAllocationCache deferred = new();
        var ordinary = deferred.ApplyInkOwned(prefix, [FrozenInput(scenario.Hits[0])], [], roots);
        check(ordinary.Summary.Fields.Count == 0 && EvidenceJsonSignature.Sorted(ordinary.Hits.Single()) == EvidenceJsonSignature.Sorted(scenario.Hits[0]),
            "A summary without ink records or explosions retains ordinary source evidence unchanged");
        var lateInk = deferred.ApplyInkOwned(input, scenario.Hits.Select(FrozenInput).ToArray(), scenario.Records, roots);
        check(EvidenceJsonSignature.Sorted(lateInk.Hits[1]) == EvidenceJsonSignature.Sorted(expected.Hits[1])
            && EvidenceJsonSignature.Sorted(lateInk.Summary) == EvidenceJsonSignature.Sorted(expected.Summary),
            "First ink evidence replays earlier structured source observations even after ordinary-only summaries");
        LiveAllocationCache missingBinding = new();
        missingBinding.ApplyInkOwned(prefix, [FrozenInput(scenario.Hits[0])], [], roots);
        var unbound = missingBinding.ApplyInkOwned(input, scenario.Hits.Select(FrozenInput).ToArray(), [], roots);
        var expectedUnbound = InkProvenanceStream.Apply(input, scenario.Hits, [], roots);
        check(EvidenceJsonSignature.Sorted(unbound.Hits[1]) == EvidenceJsonSignature.Sorted(expectedUnbound.Hits[1])
            && EvidenceJsonSignature.Sorted(unbound.Summary) == EvidenceJsonSignature.Sorted(expectedUnbound.Summary),
            "An explosion without its binding still receives the complete unresolved ink evidence");
        ReportHitInput OwnedInput(EvidenceObject hit) => Input((EvidenceObject)EvidenceJson.Clone(hit));
        LiveAllocationCache transferred = new();
        var transferredPrefix = transferred.ApplyInkOwned(prefix, [OwnedInput(scenario.Hits[0])], scenario.Records, roots);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)transferredPrefix.Hits[0].Get("rdps_contributions")).Fields).Clear();
        var transferredResult = transferred.ApplyInkOwned(input, scenario.Hits.Select(OwnedInput).ToArray(), scenario.Records, roots);
        check(transferred.Diagnostics.InkReplays == 0 && EvidenceJson.PythonEquals(transferredResult.Hits[1], expected.Hits[1]),
            "The continuing ink ledger detaches consumed source evidence even when it accepts report ownership");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)transferredResult.Hits[1].Get("rdps_contributions")).Fields).Clear();
        var transferredAgain = transferred.ApplyInkOwned(input, scenario.Hits.Select(OwnedInput).ToArray(), scenario.Records, roots);
        check(transferred.Diagnostics.InkReplays == 0 && EvidenceJson.PythonEquals(transferredAgain.Hits[1], expected.Hits[1]),
            "Owned replay of a completed explosion restores protected cached contributions after report-local mutation");
        check(prefix.Count == 3 && input.Count == 6 && cache.Diagnostics.InkReplays == 0
            && EvidenceJson.PythonEquals(complete.Hits[1], expected.Hits[1]) && EvidenceJson.PythonEquals(complete.Summary, expected.Summary),
            "Persistent structured prefixes advance only new observations with the same frozen source-time allocation");
        ((Dictionary<string, EvidenceValue>)complete.Hits[1].Fields).Clear();
        var repeated = cache.ApplyInk(input, scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        check(cache.Diagnostics.InkReplays == 0 && EvidenceJson.PythonEquals(repeated.Hits[1], expected.Hits[1])
            && EvidenceJson.PythonEquals(repeated.Summary, expected.Summary),
            "A repeated structured read restores explosion evidence without replay or exposing cached containers");
        var revised = Change(scenario.Hits[0], ("rdps_contributions", Obj("""{"attacker":200}""")));
        var changedHits = new[] { revised, scenario.Hits[1] };
        var changed = cache.ApplyInk(input, changedHits.Select(Input).ToArray(), scenario.Records, roots);
        var changedExpected = InkProvenanceStream.Apply(input, changedHits, scenario.Records, roots);
        check(cache.Diagnostics is { InkReplays: 1, LastInkReplayReason: "original contribution changed" }
            && EvidenceJson.PythonEquals(changed.Hits[1], changedExpected.Hits[1]),
            "Late normal contribution corrections replay the structured ink ledger and retract old credit");
        var rebound = Change(scenario.Records[0], ("source_actor_id", new EvidenceText("another")));
        var reboundResult = cache.ApplyInk(input, changedHits.Select(Input).ToArray(), [rebound], roots);
        check(cache.Diagnostics is { InkReplays: 2, LastInkReplayReason: "ink binding changed" }
            && EvidenceJson.PythonEquals(reboundResult.Hits[1], InkProvenanceStream.Apply(input, changedHits, [rebound], roots).Hits[1]),
            "Late structured binding changes cannot retain the previous projectile allocation");
        cache.ApplyInk(prefix, [Input(scenario.Hits[0])], scenario.Records, roots);
        var replayed = cache.ApplyInk(input, scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        check(cache.Diagnostics.InkReplays == 3 && EvidenceJson.PythonEquals(replayed.Hits[1], expected.Hits[1]),
            "Reading an earlier immutable prefix retracts future release state and subsequent appends recover exact results");
        InkObservationLog other = new();
        for (var index = 0; index < events.Length; index++) other.Observe(index + 1, events[index]);
        cache.ApplyInk(other.Capture(), scenario.Hits.Select(Input).ToArray(), scenario.Records, roots);
        check(cache.Diagnostics is { InkReplays: 4, LastInkReplayReason: "ink input prefix changed" },
            "A different ingestion owner explicitly resets ink history even when observation counts match");

        var source = Change(scenario.Hits[0], ("hit_value", new EvidenceInteger(200)), ("ts_ms", new EvidenceInteger(1000)),
            ("source_actor_id", new EvidenceText("1")), ("target_enemy_key", new EvidenceText("enemy")),
            ("damage_element", new EvidenceText("fire")), ("damage_school", new EvidenceText("spell")));
        var explosion = Change(scenario.Hits[1], ("ts_ms", new EvidenceInteger(1100)), ("target_enemy_key", new EvidenceText("enemy")));
        var window = Obj("""{"uid":"boost","event_key":"boost","source_character_key":"support","target_character_key":"attacker","target_actor_id":"1","start_ts_ms":900,"end_ts_ms":1200,"zone_effects":[{"zone":"dmg_inc","element":"all","rate":1.0}]}""");
        DamageShareLedger ledger = new(allocator, roots);
        var allocated = ledger.Compute([Input(source), Input(explosion)], [window], scenario.Records, inkInput: input);
        var legacy = ledger.Compute([Input(source), Input(explosion)], [window], scenario.Records, string.Join('\n', scenario.Lines));
        check(allocated.InkSummary.Get("resolved") is EvidenceInteger { Value: var resolved } && resolved == 1
            && EvidenceJson.PythonEquals(allocated.Hits[1].Evidence, legacy.Hits[1].Evidence)
            && Math.Abs(allocated.Totals["support"] - 150) < 1e-10 && Math.Abs(allocated.Totals[InkProvenanceStream.Owner] - 50) < 1e-10,
            "The report ledger enables ink explosion handling from captured observations with no legacy text");

        ReportHitInput Protected(EvidenceObject hit) => Input((EvidenceObject)FrozenEvidence.Capture(hit)) with
        {
            Baseline = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
            BasicAttributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
            Attributes = FrozenEvidence.CaptureNumbers(new Dictionary<BigInteger, EvidenceValue>()),
        };
        var earlyHit = Change(source, ("ts_ms", new EvidenceInteger(500)), ("line_no", new EvidenceInteger(1)),
            ("packet_seq_id", new EvidenceInteger(50)), ("target_actor_id", new EvidenceText("unrelated")));
        var finalHit = Change(source, ("ts_ms", new EvidenceInteger(1500)), ("line_no", new EvidenceInteger(9)),
            ("packet_seq_id", new EvidenceInteger(200)));
        ReportHitInput[] ordered = [Protected(earlyHit), Protected(source), Protected(explosion), Protected(finalHit)];
        LiveAllocationCache rewound = new();
        var shortWindow = Change(window, ("end_ts_ms", new EvidenceInteger(950)));
        var extendedWindow = Change(window, ("end_ts_ms", new EvidenceInteger(1050)));
        ledger.ComputeOwned(ordered, [shortWindow], scenario.Records, null, rewound, input, summary: true);
        var beforeRewind = ledger.ComputeOwned(ordered, [shortWindow], scenario.Records, null, rewound, input, summary: true);
        var afterRewind = ledger.ComputeOwned(ordered, [extendedWindow], scenario.Records, null, rewound, input, summary: true);
        var coldRewind = ledger.Compute(ordered, [extendedWindow], scenario.Records, inkInput: input);
        check(rewound.Diagnostics is { Replays: 1, ReusedHits: 1, AllocatedHits: 3 }
            && ReferenceEquals(beforeRewind.Hits[0], afterRewind.Hits[0]),
            "An ink source revision retains the unrelated finalized prefix while rewinding allocations from the changed source");
        check(afterRewind.Hits.Zip(coldRewind.Hits).All(pair => EvidenceJsonSignature.Sorted(pair.First.Evidence) == EvidenceJsonSignature.Sorted(pair.Second.Evidence))
            && EvidenceJsonSignature.Sorted(afterRewind.InkSummary) == EvidenceJsonSignature.Sorted(coldRewind.InkSummary),
            "A partial rewind rebuilds complete ink recording and explosion evidence from the cold reference");
        check(afterRewind.Totals.All(pair => coldRewind.Totals[pair.Key] == pair.Value)
            && beforeRewind.Totals.GetValueOrDefault("support") == 0 && Math.Abs(afterRewind.Totals["support"] - 150) < 1e-10,
            "Revised ink source credit retracts old recording weights and preserves published totals");
    }
}
