using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

public sealed record AllocationPreflightResult(EvidenceObject Summary, IReadOnlyList<EvidenceObject> Records);

/// <summary>Evaluate semantic readiness independently of display/window preparation, preserving every blocker.</summary>
public sealed class AllocationPreflight(IReadOnlyDictionary<string, EvidenceObject> roots, EffectApproval approval,
    EffectStructureCatalog structure, EffectSpecificationCatalog specifications, DynamicEffectSpecificationCatalog dynamics)
{
    public static AllocationPreflight Load(ResourceFiles files)
    {
        var roots = new BuffRootCatalog(files).Roots;
        SkillResourceCatalog skills = new(files);
        EffectApproval approval = new(EffectApprovalCatalog.Load(files), roots, skills.Buffs, skills.Skills);
        EffectStructureCatalog structure = new(roots);
        EffectSpecificationCatalog specifications = new(approval, new(roots, DamageZoneCatalog.Load(files), approval), structure);
        return new(roots, approval, structure, specifications, new(approval, specifications, roots, PacketBuffCatalog.Load(files, skills)));
    }
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static EvidenceArray Array(IEnumerable<EvidenceValue> values) => new(values.ToArray());
    private static BigInteger Integer(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    public static bool CouldAffectExternal(EvidenceObject record)
    {
        var source = Text(record.Get("source_character_key"));
        if (!source.StartsWith("chr_", StringComparison.Ordinal)) return Truth(record.Get("target_enemy_key")) || Truth(record.Get("target_character_key"));
        return Text(record.Get("target_enemy_key")).StartsWith("eny_", StringComparison.Ordinal)
            || Text(record.Get("target_character_key")) is var target && target.StartsWith("chr_", StringComparison.Ordinal) && target != source;
    }
    public bool Overlaps(EvidenceObject record, BigInteger start, BigInteger end)
    {
        var timestamp = Integer(record.Get("ts_ms"));
        if (record.Get("snapshot_end_ts_ms") is not EvidenceNull && Integer(record.Get("snapshot_end_ts_ms")) < start) return false;
        if (record.Get("end_ts_ms") is EvidenceNull && record.Get("raw_duration_ms") is EvidenceNull) return timestamp <= end;
        var observedEnd = record.Get("end_ts_ms");
        var duration = record.Get("raw_duration_ms");
        var infinite = roots.GetValueOrDefault(Text(CatalogValues.Or(record.Get("event_key"), new EvidenceText("unknown_buff"))))?.Get("lifeType") is EvidenceText { Value: "Infinity" };
        static bool AtLeast(EvidenceValue left, EvidenceValue right) => left is not EvidenceReal { Value: double.NaN }
            && right is not EvidenceReal { Value: double.NaN } && EffectIdentity.CompareKeys(left, right) >= 0;
        static EvidenceValue Min(EvidenceValue left, EvidenceValue right) => EffectIdentity.CompareKeys(right, left) < 0 ? right : left;
        static EvidenceValue Add(EvidenceValue left, EvidenceValue right, bool subtract = false)
        {
            if (left is EvidenceReal || right is EvidenceReal)
                return new EvidenceReal(EffectIdentity.Float(left) + (subtract ? -EffectIdentity.Float(right) : EffectIdentity.Float(right)));
            if (left is not (EvidenceInteger or EvidenceBoolean) || right is not (EvidenceInteger or EvidenceBoolean))
                throw new InvalidCastException("Buff time arithmetic requires numeric evidence");
            return new EvidenceInteger(EffectIdentity.Integer(left) + (subtract ? -EffectIdentity.Integer(right) : EffectIdentity.Integer(right)));
        }
        EvidenceInteger at = new(timestamp), zero = new(0), remaining = new(BigInteger.Max(end - timestamp, 0));
        var normalized = observedEnd is not EvidenceNull && AtLeast(observedEnd, at) ? Min(remaining, Add(observedEnd, at, true))
            : duration is not EvidenceNull && AtLeast(duration, zero) ? Min(remaining, duration) : infinite ? remaining : zero;
        return AtLeast(Add(at, normalized), new EvidenceInteger(start)) && timestamp <= end;
    }
    public AllocationPreflightResult Build(IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> windows,
        BigInteger start, BigInteger end, IReadOnlyList<EvidenceObject>? hits = null,
        IReadOnlyList<EvidenceObject>? unresolvedHits = null, IReadOnlyList<EvidenceObject>? unresolvedBuffActions = null,
        EffectRecordCache? recordCache = null)
        => BuildCore(records, windows, start, end, hits, unresolvedHits, unresolvedBuffActions, recordCache, ownsEvidence: false);

    internal AllocationPreflightResult BuildOwned(IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> windows,
        BigInteger start, BigInteger end, IReadOnlyList<EvidenceObject> hits,
        IReadOnlyList<EvidenceObject> unresolvedHits, IReadOnlyList<EvidenceObject> unresolvedBuffActions,
        EffectRecordCache? recordCache, IEnumerable<EvidenceObject>? hitBlockers = null, bool readOnlyRecords = false)
        => BuildCore(records, windows, start, end, hits, unresolvedHits, unresolvedBuffActions, recordCache, ownsEvidence: true, hitBlockers, readOnlyRecords);

    // The private live summary consumes counts and a verdict, never blocker rows. Full reports
    // keep using Build/BuildOwned; omitted nonempty evidence is explicitly unknown, not empty.
    internal AllocationPreflightResult BuildSummaryOwned(IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> windows,
        BigInteger start, BigInteger end, IReadOnlyList<EvidenceObject> unresolvedHits,
        IReadOnlyList<EvidenceObject> unresolvedBuffActions, EffectRecordCache? recordCache, int hitBlockerCount)
        => BuildCore(records, windows, start, end, null, unresolvedHits, unresolvedBuffActions, recordCache,
            ownsEvidence: true, readOnlyRecords: true, summarizedHitBlockerCount: hitBlockerCount);

    // This verdict depends only on the exact record and this resource owner. Time/window selection stays outside.
    private EffectRecordAnalysis Assess(EvidenceObject record, bool ownsEvidence)
    {
        if (structure.Classify(record) is EvidenceObject proof && proof.Get("proof_kind") is EvidenceText { Value: "typed_root_structural" })
        {
            ((Dictionary<string, EvidenceValue>)record.Fields).Remove("rdps_unresolved_semantic_condition");
            return new(record, [], [], []) { Readiness = new(NonDamage: 1) };
        }
        var statics = ownsEvidence ? specifications.CollectStaticOwned(record) : specifications.CollectStatic(record);
        var dynamic = ownsEvidence ? dynamics.CollectOwned(statics.Record) : dynamics.Collect(statics.Record);
        record = dynamic.Record;
        EffectRecordAnalysis result = new(record, [], statics.Effects, dynamic.Effects);
        EvidenceObject Blocker(string reason, params string[] fields)
        {
            var values = fields.ToDictionary(field => field, record.Get, StringComparer.Ordinal);
            values["reason"] = new EvidenceText(reason);
            return new(values);
        }
        if (record.Get("end_ts_ms") is EvidenceNull && record.Get("raw_duration_ms") is EvidenceNull
            && record.Get("lifetime_mode") is not EvidenceText { Value: "Infinity" } && approval.Match(record) is not null)
            return result with { Readiness = new(Blocker: Blocker("unresolved_buff_lifecycle", "uid", "event_key")) };
        if (Truth(record.Get("rdps_unresolved_semantic_condition")))
        {
            var blocker = Blocker("unresolved_semantic_condition", "uid", "event_key");
            ((Dictionary<string, EvidenceValue>)blocker.Fields)["condition_errors"] = BuffEvidence.Clone(record.Get("rdps_unresolved_semantic_condition"));
            return result with { Readiness = new(Blocker: blocker) };
        }
        if (!CouldAffectExternal(record)) return result with { Readiness = new() };
        var hasEffect = result.StaticEffects.Count > 0 || result.DynamicEffects.Count > 0;
        var classification = PacketBuffClassification.Classify(record);
        var entry = approval.Match(record);
        EvidenceObject? validation = null;
        if (entry is not null)
        {
            var validated = EffectRegistryRules.Validate(entry, record);
            result = result with { Record = record = validated.Record };
            validation = validated.Error;
            if (validation is null) return result with { Readiness = new(CheckedExternal: 1, Accepted: 1) };
        }
        else if (structure.Classify(record) is not null)
            return result with { Readiness = new(CheckedExternal: 1, NonDamage: 1) };
        Dictionary<string, EvidenceValue> blocked = new(StringComparer.Ordinal);
        foreach (var field in new[] { "uid", "event_key", "raw_event_key", "source_character_key", "source_skill_key", "source_skill_family_key", "target_character_key", "target_enemy_key" })
            blocked[field] = field == "uid" ? new EvidenceText(Text(record.Get("uid"))) : record.Get(field);
        blocked["class"] = classification.Get("class");
        blocked["reason"] = validation?.Get("reason") ?? classification.Get("reason");
        blocked["bb_keys"] = Array(CatalogValues.Iterable(CatalogValues.Or(record.Get("bb_keys"), new EvidenceArray([])))
            .Select(CatalogValues.Text).Distinct(StringComparer.Ordinal).Order(PythonDisplay.CodePointComparer).Select(value => new EvidenceText(value)));
        if (validation is not null) foreach (var field in new[] { "unknown_bb_keys", "required_bb_keys" }) blocked[field] = validation.Get(field);
        blocked["has_effect"] = new EvidenceBoolean(hasEffect);
        blocked["included_effect_window"] = new EvidenceBoolean(false);
        blocked["packet_mapping_rejected"] = new EvidenceBoolean(Truth(record.Get("packet_mapping_rejected")));
        var includedReason = validation is null && (hasEffect || classification.Get("class") is EvidenceText { Value: "effect" })
            ? new EvidenceText("included external rDPS effect is not in rdps_semantics_registry.verified_effects") : null;
        return result with { Readiness = new(CheckedExternal: 1, Blocker: new(blocked), TracksWindowInclusion: true, IncludedReason: includedReason) };
    }

    private AllocationPreflightResult BuildCore(IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> windows,
        BigInteger start, BigInteger end, IReadOnlyList<EvidenceObject>? hits,
        IReadOnlyList<EvidenceObject>? unresolvedHits, IReadOnlyList<EvidenceObject>? unresolvedBuffActions,
        EffectRecordCache? recordCache, bool ownsEvidence, IEnumerable<EvidenceObject>? hitBlockers = null, bool readOnlyRecords = false,
        int? summarizedHitBlockerCount = null)
    {
        var frozenRecords = ownsEvidence && readOnlyRecords && recordCache is not null;
        // Only record roots are changed below. The live calculation owns the input descendants.
        var current = records.Select(record => frozenRecords ? (EvidenceObject)FrozenEvidence.Capture(record) : ownsEvidence
            ? new EvidenceObject(new Dictionary<string, EvidenceValue>(record.Fields, StringComparer.Ordinal)) { SourcePairs = record.SourcePairs }
            : (EvidenceObject)BuffEvidence.Clone(record)).ToArray();
        var compact = summarizedHitBlockerCount is not null;
        HashSet<string>? included = compact ? null : new(windows.SelectMany(EffectIdentity.WindowUids), StringComparer.Ordinal);
        List<EvidenceObject>? blockers = compact ? null : [];
        var blockerCount = summarizedHitBlockerCount ?? 0;
        void AddRow(EvidenceObject source)
        {
            blockerCount++;
            if (blockers is not null) blockers.Add((EvidenceObject)BuffEvidence.Clone(source));
        }
        void Add(EvidenceObject source, string reason, params string[] fields)
        {
            blockerCount++;
            if (blockers is null) return;
            var row = fields.ToDictionary(field => field, source.Get, StringComparer.Ordinal);
            row["reason"] = new EvidenceText(reason);
            blockers.Add(new(row));
        }
        foreach (var row in unresolvedBuffActions ?? [])
            if (!Truth(row.Get("uid_observation_only")) && Overlaps(row, start, end)) AddRow(row);
        foreach (var window in windows)
        {
            if (Truth(window.Get("rdps_invalid_dynamic_evaluation"))) Add(window, "invalid_dynamic_evaluation", "uid");
            if (Truth(window.Get("rdps_unresolved_stack_evidence"))) Add(window, "unresolved_stack_evidence", "uid", "event_key");
            if (Truth(window.Get("rdps_unresolved_enable_evidence"))) Add(window, "unobserved_initial_buff_enable_state", "uid", "event_key");
            if (Truth(window.Get("rdps_snapshot_order_unresolved"))) Add(window, "unresolved_buff_snapshot_order", "uid");
        }
        foreach (var row in unresolvedHits ?? []) if (Integer(row.Get("ts_ms")) >= start && Integer(row.Get("ts_ms")) <= end) AddRow(row);
        if (blockers is not null)
        {
            blockers.AddRange(hitBlockers ?? (hits ?? []).SelectMany(HitBlockers));
            blockerCount = blockers.Count;
        }
        var checkedExternal = 0;
        var accepted = 0;
        var nonDamage = 0;
        for (var index = 0; index < current.Length; index++)
        {
            var record = current[index];
            if (Truth(record.Get("uid_observation_only")) || !Overlaps(record, start, end)) continue;
            EffectRecordAnalysis Analyze(EvidenceObject value) => Assess(value, ownsEvidence);
            var analyzed = recordCache is null ? Analyze(record)
                : frozenRecords ? recordCache.AnalyzeFrozen(this, record, Analyze)
                : ownsEvidence ? recordCache.AnalyzeOwned(this, record, Analyze) : recordCache.Analyze(this, record, Analyze);
            current[index] = record = analyzed.Record;
            var readiness = analyzed.Readiness ?? throw new InvalidOperationException("Expected a record semantic verdict");
            checkedExternal += readiness.CheckedExternal;
            accepted += readiness.Accepted;
            nonDamage += readiness.NonDamage;
            if (readiness.Blocker is null) continue;
            blockerCount++;
            if (blockers is null) continue;
            var blocker = ownsEvidence ? FrozenEvidence.OwnedMutableRoot(readiness.Blocker) : (EvidenceObject)BuffEvidence.Clone(readiness.Blocker);
            if (readiness.TracksWindowInclusion)
            {
                var isIncluded = Text(record.Get("uid")) is { Length: > 0 } uid && included!.Contains(uid);
                var fields = (Dictionary<string, EvidenceValue>)blocker.Fields;
                fields["included_effect_window"] = new EvidenceBoolean(isIncluded);
                if (isIncluded && readiness.IncludedReason is not null) fields["reason"] = readiness.IncludedReason;
            }
            blockers.Add(blocker);
        }
        var counts = blockers?.GroupBy(row => Text(CatalogValues.Or(row.Get("reason"), new EvidenceText("unknown"))))
            .ToDictionary(group => group.Key, group => (EvidenceValue)new EvidenceInteger(group.Count()), StringComparer.Ordinal);
        var summary = BuffEvidence.Object(("mode", new EvidenceText("pre_allocation_semantic_gate")), ("ok", new EvidenceBoolean(blockerCount == 0)),
            ("checked_external_buff_count", new EvidenceInteger(checkedExternal)), ("accepted_effect_buff_count", new EvidenceInteger(accepted)),
            ("accepted_non_rdps_buff_count", new EvidenceInteger(nonDamage)), ("blocker_count", new EvidenceInteger(blockerCount)),
            ("blocker_reason_counts", counts is null ? EvidenceNull.Value : new EvidenceObject(counts)),
            ("blockers", blockers is not null ? Array(blockers) : blockerCount == 0 ? new EvidenceArray([]) : EvidenceNull.Value));
        return new(ownsEvidence ? summary : (EvidenceObject)BuffEvidence.Clone(summary), current);
    }

    // This verdict uses only the final hit evidence, never resource, scope or window state.
    internal static IReadOnlyList<EvidenceObject> HitBlockers(EvidenceObject hit)
    {
        List<EvidenceObject> blockers = [];
        CollectHitBlockers(hit, blockers);
        return blockers;
    }

    internal static int HitBlockerCount(EvidenceObject hit) => CollectHitBlockers(hit, null);

    private static int CollectHitBlockers(EvidenceObject hit, List<EvidenceObject>? blockers)
    {
        var count = 0;
        void Add(string reason, string field, string? second = null)
        {
            count++;
            if (blockers is null) return;
            Dictionary<string, EvidenceValue> row = new(StringComparer.Ordinal) { [field] = hit.Get(field) };
            if (second is not null) row[second] = hit.Get(second);
            row["reason"] = new EvidenceText(reason); blockers.Add(new(row));
        }
        static bool InvalidBucket(EvidenceValue side)
        {
            foreach (var value in CatalogValues.Iterable(CatalogValues.Or(side, new EvidenceArray([]))))
                if (value is EvidenceNull) return true;
            return false;
        }
        if (hit.Get("dpd_raw") is EvidenceObject dpd && (InvalidBucket(dpd.Get("atk_zones")) || InvalidBucket(dpd.Get("def_zones"))))
            Add("invalid_dpd_bucket_evidence", "seq");
        List<string>? missing = blockers is null ? null : [];
        var missingCount = 0;
        void Missing(string field) { missingCount++; missing?.Add(field); }
        if (!Truth(hit.Get("damage_element")) || hit.Get("damage_element_source") is not EvidenceText { Value: "official_action_unit" }) Missing("damage_action_unit");
        if (!Truth(hit.Get("damage_school"))) Missing("damage_school");
        if (!Truth(hit.Get("target_enemy_key")) || hit.Get("target_enemy_key") is EvidenceText { Value: "eny_0000_unknown" }) Missing("target_identity");
        if (hit.Get("packet_hit_value") is EvidenceNull) Missing("packet_hp_loss");
        if (missingCount > 0)
        {
            Add("unresolved_hit_evidence", "seq", "line_no");
            if (blockers is not null)
                ((Dictionary<string, EvidenceValue>)blockers[^1].Fields)["missing"] = Array(missing!.Select(value => new EvidenceText(value)));
        }
        void Flag(string flag, string reason, bool withLine = false)
        {
            if (Truth(hit.Get(flag))) Add(reason, "seq", withLine ? "line_no" : null);
        }
        Flag("rdps_unresolved_effect_conditions", "unresolved_effect_condition", true);
        Flag("rdps_unresolved_whitelist_effect", "external_effect_not_whitelisted");
        if (Truth(hit.Get("rdps_unresolved_static_multiplier_sources")))
        {
            count++;
            if (blockers is not null)
            {
                var row = BuffEvidence.Object(("seq", hit.Get("seq")), ("reason", new EvidenceText("unresolved_static_multiplier_source")),
                    ("sources", BuffEvidence.Clone(hit.Get("rdps_unresolved_static_multiplier_sources"))));
                blockers.Add(row);
            }
        }
        Flag("rdps_unresolved_target_binding", "unresolved_effect_target_instance");
        Flag("rdps_unresolved_attacker_binding", "unresolved_attacker_stats_binding");
        Flag("rdps_unresolved_dpd_residual", "DPD residual has no authoritative attribution", true);
        return count;
    }
}
