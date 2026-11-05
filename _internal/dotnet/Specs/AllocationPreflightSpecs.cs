using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class AllocationPreflightSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static IReadOnlyList<EvidenceObject> Blockers(AllocationPreflightResult result) => ((EvidenceArray)result.Summary.Get("blockers")).Items.Cast<EvidenceObject>().ToArray();
    public static void Run(Action<bool, string> check)
    {
        AllocationPreflight Gate(string registry = "{}", Dictionary<string, EvidenceObject>? roots = null)
        {
            roots ??= [];
            EffectApproval approval = new(Obj(registry), roots, new Dictionary<string, string>(), new Dictionary<string, string>());
            EffectStructureCatalog structure = new(roots);
            EffectSpecificationCatalog specifications = new(approval, new(roots, new Dictionary<string, EvidenceObject> { ["NormalCalcZone"] = Obj("{}") }, approval), structure);
            return new(roots, approval, structure, specifications, new(approval, specifications, roots,
                new(new Dictionary<string, EvidenceObject>(), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), new Dictionary<string, string>())));
        }
        var gate = Gate();
        var empty = gate.Build([], [], 1000, 2000);
        check(empty.Summary.Get("ok") is EvidenceBoolean { Value: true } && Blockers(empty).Count == 0, "An empty battle has no fabricated evidence blockers");
        var hit = Obj("""{"seq":1,"line_no":2,"damage_element":"fire","damage_element_source":"official_action_unit","damage_school":"arts","target_enemy_key":"eny_target","packet_hit_value":0}""");
        check(gate.Build([], [], 1000, 2000, [hit]).Summary.Get("ok") is EvidenceBoolean { Value: true }, "An observed zero HP loss is valid packet evidence");
        var missing = gate.Build([], [], 1000, 2000, [Obj("""{"seq":1,"target_enemy_key":"eny_0000_unknown"}""")]);
        check(Blockers(missing) is [var unresolved] && unresolved.Get("missing") is EvidenceArray { Items.Count: 4 }, "Missing action, school, target and packet HP loss are all reported");
        check(gate.Overlaps(Obj("""{"ts_ms":500,"raw_duration_ms":500}"""), 1000, 2000)
            && !gate.Overlaps(Obj("""{"ts_ms":500,"raw_duration_ms":499.5}"""), 1000, 2000), "Lifecycle overlap keeps inclusive endpoints and fractional durations");
        check(!gate.Overlaps(Obj("""{"ts_ms":1500,"snapshot_end_ts_ms":999}"""), 1000, 2000)
            && gate.Overlaps(Obj("""{"ts_ms":500}"""), 1000, 2000), "Snapshot termination excludes stale records while an unended observation remains a candidate");
        var observed = gate.Build([], [], 1000, 2000, unresolvedBuffActions: [Obj("""{"ts_ms":1500,"uid_observation_only":true}""")],
            unresolvedHits: [Obj("""{"ts_ms":999,"reason":"outside"}"""), Obj("""{"ts_ms":2000,"reason":"inside","detail":[1,2]}""")]);
        check(Blockers(observed) is [var boundary] && boundary.Get("reason") is EvidenceText { Value: "inside" } && boundary.Get("detail") is EvidenceArray { Items.Count: 2 },
            "Unresolved hits retain their complete payload at the battle boundary; observation-only actions are excluded");
        var many = gate.Build([], [], 1000, 2000, unresolvedBuffActions: Enumerable.Range(0, 300).Select(index => Obj($"{{\"ts_ms\":1500,\"uid\":\"{index}\",\"reason\":\"missing\"}}")).ToArray());
        check(Blockers(many).Count == 300 && ((EvidenceObject)many.Summary.Get("blocker_reason_counts")).Get("missing") is EvidenceInteger { Value: var count } && count == 300,
            "The audit retains all 300 blockers and their complete reason count");
        var unknown = Obj("""{"uid":"u","event_key":"999","ts_ms":1500,"source_character_key":"chr_a","target_character_key":"chr_a"}""");
        var before = EvidenceJsonSignature.Sorted(unknown);
        var own = gate.Build([unknown], [], 1000, 2000);
        check(Blockers(own) is [var semantic] && semantic.Get("reason") is EvidenceText { Value: "unresolved_semantic_condition" },
            "Unresolved own multipliers are diagnosed even without an external provider or UI windows");
        check(before == EvidenceJsonSignature.Sorted(unknown) && own.Records[0].Get("rdps_unresolved_semantic_condition") is EvidenceArray,
            "Preflight returns updated owned evidence without mutating the ingestion snapshot");
        var marker = Obj("""{"$type":"Beyond.Gameplay.Core.BuffData","attributeModifier":{"attributeModifiers":[]},"damageModifier":[]}""");
        var proven = Gate(roots: new() { ["marker"] = marker }).Build([Obj("""{"event_key":"marker","ts_ms":1500,"rdps_unresolved_semantic_condition":["stale"]}""")], [], 1000, 2000);
        check(proven.Summary.Get("accepted_non_rdps_buff_count") is EvidenceInteger { Value: var accepted } && accepted == 1
            && proven.Summary.Get("ok") is EvidenceBoolean { Value: true } && proven.Records[0].Get("rdps_unresolved_semantic_condition") is EvidenceNull,
            "A current typed structural proof accepts a marker and clears stale semantic failure");
        const string registry = """{"verified_effects":{"buff":{"effects":[{"zone":"dmg_inc","element":"all","bb_key":"rate"}]}}}""";
        var root = Obj("""
            {"damageModifier":[{"enableSide":"Attacker","condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[]},
              "damageProcessors":[{"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Attacker","zoneName":"NormalCalcZone","addition":{"useBlackboardKey":true,"blackboardKey":"rate"}}]}],
             "attributeModifier":{"isConvertedAttribute":false,"attributeModifiers":[]}}
            """);
        var approvedGate = Gate(registry, new() { ["buff"] = root });
        var approved = Obj("""{"uid":"u","event_key":"buff","ts_ms":1500,"source_character_key":"chr_b","target_character_key":"chr_a","bb_values":{"rate":0.2}}""");
        var lifecycle = approvedGate.Build([approved], [], 1000, 2000);
        check(Blockers(lifecycle) is [var missingLife] && missingLife.Get("reason") is EvidenceText { Value: "unresolved_buff_lifecycle" }, "Approval alone cannot supply a missing lifetime");
        var timed = new EvidenceObject(new Dictionary<string, EvidenceValue>(approved.Fields) { ["raw_duration_ms"] = new EvidenceInteger(500) });
        var valid = approvedGate.Build([timed], [], 1000, 2000);
        EffectRecordCache ownedCache = new();
        AllocationPreflightResult Owned(EvidenceObject source, int start = 1000, int end = 2000) =>
            approvedGate.BuildOwned([source], [], start, end, [], [], [], ownedCache);
        var ownedFirst = Owned(timed);
        var ownedNext = Owned(timed);
        check(EvidenceJson.PythonEquals(valid.Summary, ownedNext.Summary)
            && EvidenceJson.PythonEquals(valid.Records[0], ownedNext.Records[0])
            && ReferenceEquals(ownedFirst.Records[0].Get("bb_values"), ownedNext.Records[0].Get("bb_values")),
            "Owned preflight preserves public results while sharing immutable cache descendants");
        EffectRecordCache frozenCache = new();
        AllocationPreflightResult Frozen(EvidenceObject source, int start = 1000, int end = 2000, bool included = false) =>
            approvedGate.BuildOwned([source], included ? [Obj("""{"uid":"u"}""")] : [], start, end,
                [], [], [], frozenCache, readOnlyRecords: true);
        var frozenFirst = Frozen(timed);
        var frozenNext = Frozen(timed);
        var prevented = false;
        try { ((IDictionary<string, EvidenceValue>)frozenNext.Records[0].Fields)["raw_duration_ms"] = new EvidenceInteger(1); }
        catch (NotSupportedException) { prevented = true; }
        check(prevented && ReferenceEquals(frozenFirst.Records[0], frozenNext.Records[0])
            && EvidenceJson.PythonEquals(valid.Summary, frozenNext.Summary) && EvidenceJson.PythonEquals(valid.Records[0], frozenNext.Records[0]),
            "Summary preflight reuses an immutable record without changing public evidence or exposing writable cache roots");
        var frozenExtra = new EvidenceObject(new Dictionary<string, EvidenceValue>(timed.Fields) { ["bb_keys"] = new EvidenceArray([new EvidenceText("undocumented")]) });
        var frozenRejected = Frozen(frozenExtra);
        var frozenIncluded = Frozen(frozenExtra, included: true);
        check(Blockers(frozenRejected)[0].Get("included_effect_window") is EvidenceBoolean { Value: false }
            && Blockers(frozenIncluded)[0].Get("included_effect_window") is EvidenceBoolean { Value: true }
            && frozenFirst.Summary.Get("ok") is EvidenceBoolean { Value: true }
            && EvidenceJson.PythonEquals(frozenIncluded.Summary, approvedGate.Build([frozenExtra], [Obj("""{"uid":"u"}""")], 1000, 2000).Summary),
            "A late record revision and current window membership update the summary without changing earlier verdicts");
        var frozenOutsideSource = (EvidenceObject)EvidenceJson.Clone(timed);
        var frozenOutside = Frozen(frozenOutsideSource, 3000, 4000);
        ((IDictionary<string, EvidenceValue>)frozenOutsideSource.Fields)["event_key"] = new EvidenceText("changed");
        check(frozenOutside.Summary.Get("checked_external_buff_count") is EvidenceInteger { Value.IsZero: true }
            && frozenOutside.Records[0].Get("event_key") is EvidenceText { Value: "buff" },
            "Out-of-window summary records remain detached from mutable callers even when no assessment runs");
        var input = Obj("""{"rate":0.4}""");
        var late = new EvidenceObject(new Dictionary<string,EvidenceValue>(timed.Fields) { ["bb_values"] = input });
        var updated = Owned(late);
        ((Dictionary<string,EvidenceValue>)input.Fields)["rate"] = new EvidenceReal(.8);
        var newer = Owned(late);
        check(((EvidenceObject)updated.Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value:.4 }
            && ((EvidenceObject)newer.Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value:.8 }
            && ((EvidenceObject)ownedFirst.Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value:.2 },
            "Late source mutations invalidate owned preflight without changing retained earlier evidence");
        ((Dictionary<string,EvidenceValue>)ownedNext.Records[0].Fields)["rdps_invalid_runtime_rate"] = new EvidenceBoolean(true);
        var ownedOutside = Owned(timed, 3000, 4000);
        check(Owned(timed).Records[0].Get("rdps_invalid_runtime_rate") is EvidenceNull
            && ownedOutside.Summary.Get("checked_external_buff_count") is EvidenceInteger { Value.IsZero:true },
            "Owned record roots and report-local overlap counts cannot pollute later preflight results");
        check(valid.Summary.Get("ok") is EvidenceBoolean { Value: true } && valid.Summary.Get("accepted_effect_buff_count") is EvidenceInteger { Value: var effects } && effects == 1,
            "Current typed effect, reviewed rate and observed lifetime pass without requiring window construction");
        var extra = new EvidenceObject(new Dictionary<string, EvidenceValue>(timed.Fields) { ["bb_keys"] = new EvidenceArray([new EvidenceText("undocumented")]) });
        var rejected = approvedGate.Build([extra], [], 1000, 2000);
        check(Blockers(rejected) is [var invalid] && invalid.Get("unknown_bb_keys") is EvidenceArray { Items: [EvidenceText { Value: "undocumented" }] },
            "Undeclared blackboard data retains the concrete key in the blocker");
        var blockedHit = Obj("""{"seq":3,"line_no":4,"dpd_raw":{"atk_zones":[null]},"rdps_unresolved_effect_conditions":true,"rdps_unresolved_whitelist_effect":true,"rdps_unresolved_static_multiplier_sources":[{"source":"unknown"}],"rdps_unresolved_target_binding":true,"rdps_unresolved_attacker_binding":true,"rdps_unresolved_dpd_residual":true}""");
        check(AllocationPreflight.HitBlockerCount(blockedHit) == 8 && AllocationPreflight.HitBlockers(blockedHit).Count == 8
            && AllocationPreflight.HitBlockerCount(hit) == 0,
            "Count-only hit readiness retains every independent blocker while observed zero HP loss stays valid");
        EffectRecordCache compactCache = new();
        void CompareSummary(EvidenceObject record, int start, int end, bool included)
        {
            EvidenceObject[] windowRows = included ? [Obj("""{"uid":"u","rdps_invalid_dynamic_evaluation":true,"rdps_unresolved_stack_evidence":true,"rdps_unresolved_enable_evidence":true,"rdps_snapshot_order_unresolved":true}""")] : [];
            EvidenceObject[] unresolvedHits = [Obj("""{"ts_ms":2000,"reason":"boundary_hit","detail":[1,2]}""")];
            EvidenceObject[] unresolvedActions = [Obj("""{"ts_ms":1500,"reason":"unknown_action"}"""), Obj("""{"ts_ms":1500,"uid_observation_only":true}""")];
            var full = approvedGate.Build([record], windowRows, start, end, [blockedHit], unresolvedHits, unresolvedActions);
            var compact = approvedGate.BuildSummaryOwned([record], windowRows, start, end, unresolvedHits, unresolvedActions,
                compactCache, AllocationPreflight.HitBlockerCount(blockedHit));
            check(new[] { "ok", "checked_external_buff_count", "accepted_effect_buff_count", "accepted_non_rdps_buff_count", "blocker_count" }
                    .All(field => EvidenceJson.PythonEquals(full.Summary.Get(field), compact.Summary.Get(field)))
                && EvidenceJson.PythonEquals(full.Records[0], compact.Records[0]),
                "Compact private readiness equals full counts and record analysis across late revisions, inclusion and battle bounds");
            EvidenceObject Quality(EvidenceObject summary) => SnapshotQuality.Build(BuffEvidence.Object(("rdps_preflight", summary)), includeEvidence: false);
            check(EvidenceJsonSignature.Sorted(Quality(full.Summary)) == EvidenceJsonSignature.Sorted(Quality(compact.Summary))
                && compact.Summary.Get("blockers") is EvidenceNull && Blockers(full).Count > 0,
                "Omitting private blocker rows preserves quality reasons and explicitly marks nonempty evidence as omitted");
        }
        CompareSummary(timed, 1000, 2000, false);
        CompareSummary(extra, 1000, 2000, true);
        CompareSummary(extra, 3000, 4000, false);
        CompareSummary(timed, 1000, 2000, false);
        var compactReady = approvedGate.BuildSummaryOwned([timed], [], 1000, 2000, [], [], compactCache, 0);
        check(compactReady.Summary.Get("ok") is EvidenceBoolean { Value: true } && Blockers(compactReady).Count == 0
            && compactReady.Summary.Get("blocker_count") is EvidenceInteger { Value.IsZero: true },
            "A corrected ready summary records known-empty evidence rather than unknown blockers");
        EffectRecordCache recordCache = new();
        var cached = approvedGate.Build([timed], [], 1000, 2000, recordCache: recordCache);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)cached.Records[0].Get("bb_values")).Fields)["rate"] = new EvidenceReal(999);
        var reused = approvedGate.Build([timed], [], 1000, 2000, recordCache: recordCache);
        check(recordCache.ReusedRecords > 0 && EvidenceJson.PythonEquals(valid.Summary, reused.Summary)
            && EvidenceJson.PythonEquals(valid.Records[0], reused.Records[0]),
            "Preflight reuses exact record analysis without exposing cached nested evidence to caller mutation");
        var changed = approvedGate.Build([extra], [], 1000, 2000, recordCache: recordCache);
        check(EvidenceJson.PythonEquals(rejected.Summary, changed.Summary)
            && EvidenceJson.PythonEquals(rejected.Records[0], changed.Records[0]),
            "New blackboard evidence under the same record identity invalidates preflight analysis");
        EffectRecordCache readinessCache = new();
        var blockedOnce = approvedGate.Build([extra], [], 1000, 2000, recordCache: readinessCache);
        ((EvidenceValue[])((EvidenceArray)Blockers(blockedOnce)[0].Get("unknown_bb_keys")).Items)[0] = new EvidenceText("edited");
        var blockedAgain = approvedGate.Build([extra], [], 1000, 2000, recordCache: readinessCache);
        check(readinessCache.AnalyzedRecords == 1 && readinessCache.ReusedRecords == 1
            && EvidenceJson.PythonEquals(rejected.Summary, blockedAgain.Summary),
            "A reused complete semantic verdict retains its blocker details after callers edit earlier results");
        var includedAgain = approvedGate.Build([extra], [Obj("""{"uid":"u"}""")], 1000, 2000, recordCache: readinessCache);
        check(readinessCache.AnalyzedRecords == 1 && Blockers(includedAgain)[0].Get("included_effect_window") is EvidenceBoolean { Value: true }
            && Blockers(blockedAgain)[0].Get("included_effect_window") is EvidenceBoolean { Value: false }
            && EvidenceJson.PythonEquals(includedAgain.Summary, approvedGate.Build([extra], [Obj("""{"uid":"u"}""")], 1000, 2000).Summary),
            "Window inclusion changes the current blocker without recomputing or retaining an earlier membership");
        EffectRecordCache hitCache = new();
        approvedGate.Build([timed], [], 1000, 2000, recordCache: hitCache);
        var withMissingHit = approvedGate.Build([timed], [], 1000, 2000, [Obj("""{"seq":2}""")], recordCache: hitCache);
        var withoutMissingHit = approvedGate.Build([timed], [], 1000, 2000, recordCache: hitCache);
        check(hitCache.AnalyzedRecords == 1 && Blockers(withMissingHit).Count == 1
            && withoutMissingHit.Summary.Get("ok") is EvidenceBoolean { Value: true },
            "Cached record readiness cannot hide new hit blockers or retain removed ones");
        var outside = approvedGate.Build([timed], [], 3000, 4000, recordCache: recordCache);
        check(outside.Summary.Get("checked_external_buff_count") is EvidenceInteger { Value.IsZero: true }
            && outside.Summary.Get("ok") is EvidenceBoolean { Value: true },
            "A cached record cannot retain a previous report's overlap or blocker counts");
        var differentOwner = gate.Build([timed], [], 1000, 2000, recordCache: recordCache);
        var uncachedOwner = gate.Build([timed], [], 1000, 2000);
        check(EvidenceJson.PythonEquals(differentOwner.Summary, uncachedOwner.Summary)
            && EvidenceJson.PythonEquals(differentOwner.Records[0], uncachedOwner.Records[0])
            && !EvidenceJson.PythonEquals(valid.Summary, differentOwner.Summary),
            "Preflight caches cannot transfer approvals between different resource owners");
        check(PacketBuffClassification.Classify(Obj("""{"event_key":"123","owner_raw":"eny_a","bb_keys":["Atk_Up","resist"]}""")).Get("class") is EvidenceText { Value: "rdps_effect" }
            && PacketBuffClassification.Classify(Obj("""{"event_key":"123","owner_raw":"eny_a","bb_keys":["duration"]}""")).Get("class") is EvidenceText { Value: "utility_or_marker" },
            "Packet diagnostics distinguish damage-shaped keys from utility keys without granting approval");
        check(PacketBuffClassification.Classify(Obj("""{"event_key":"123","bb_keys":["atk_up"]}""")).Get("class") is EvidenceText { Value: "orphan_actor" }
            && PacketBuffClassification.Classify(Obj("""{"event_key":"123","packet_mapping":{}}""")).Get("status") is EvidenceText { Value: "mapped" },
            "Explicit mappings take precedence and an absent actor remains a distinct diagnostic");
    }
}
