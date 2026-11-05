using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class CriticalEvidenceSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static bool Reason(EvidenceObject context, string expected) => context.Get("reasons") is EvidenceArray reasons
        && reasons.Items.OfType<EvidenceText>().Any(reason => reason.Value == expected);
    public static void Run(Action<bool, string> check)
    {
        var hit = Obj("""{"character_key":"a","source_actor_id":"actor","line_no":100,"ts_ms":1000,"critical_flag_observed":true,"crit_flag":1,"hit_value":100,"raw_hit_value":110,"overkill_damage":0,"enemy_hp_after_observed":true,"enemy_hp_before":300,"damage_element":"physical","damage_calculation":{"damageProcessors":[]}}""");
        var observation = Obj("""{"template":"a","values":{"9":0.25,"10":0.5},"lines":{"9":50,"10":50},"times":{"9":500,"10":500}}""");
        var result = CriticalEvidence.Build(hit, observation, new Dictionary<string, CriticalBuffProfile>(), []);
        check(result.Get("status") is EvidenceText { Value: "verified" } && result.Get("critRate") is EvidenceReal { Value: .25 }
            && result.Get("critDamageBonus") is EvidenceReal { Value: .5 } && result.Get("isCritical") is EvidenceBoolean { Value: true },
            "The recorded critical outcome is explained by bound 25% rate and 50% bonus attributes");
        check(result.Get("damageCap") is EvidenceInteger { Value: var hp } && hp == 300
            && result.Get("uncappedDamage") is EvidenceInteger { Value: var raw } && raw == 110,
            "Critical evidence keeps observed pre-hit HP separate from uncapped damage");
        var profile = CriticalEvidence.Profile(Obj("""{"children":[{"attributeType":"CriticalRate"},{"$type":"Beyond.Gameplay.Core.DamageAction.DamageUnit","attributeType":"CriticalDamageIncrease"}]}"""));
        check(profile.Attributes.SequenceEqual([9]) && !profile.Processors && !profile.Missing,
            "Nested damage-unit processors cannot masquerade as persistent critical BUFF attributes");
        var persistent = new Dictionary<string, CriticalBuffProfile> { ["buff"] = profile };
        var changed = CriticalEvidence.Build(hit, observation, persistent,
            [Obj("""{"event_key":"buff","target_actor_id":"actor","line_no":51}""")]);
        check(Reason(changed, "critical_attribute_changed_after_snapshot"), "A persistent critical state change invalidates an older attribute observation");
        var boundary = CriticalEvidence.Build(hit, observation, persistent,
            [Obj("""{"event_key":"buff","target_actor_id":"actor","snapshot_update":true,"end_is_observation_boundary":true,"end_line_no":51,"end_ts_ms":600}""")]);
        check(boundary.Get("status") is EvidenceText { Value: "verified" }, "An observation boundary is not inferred to be an actual BUFF expiry");
        var drain = Obj("""{"damage_element":"lifedrain","critical_flag_observed":true,"crit_flag":0,"damage_calculation":{},"hit_value":90,"raw_hit_value":100,"overkill_damage":10}""");
        var drainContext = CriticalEvidence.Build(drain, null, persistent, []);
        check(drainContext.Get("source") is EvidenceText { Value: "exact_lifedrain_no_critical_branch" }
            && drainContext.Get("damageCap") is EvidenceInteger { Value: var cap } && cap == 90,
            "The proven LifeDrain no-critical branch needs no fabricated entity snapshot and retains overkill cap");
        var active = Obj("""{"hit_value":1,"critical_flag_observed":false,"_active_attacker_buff_ids":["missing"],"part_inst_id":1}""");
        var unavailable = CriticalEvidence.Build(active, null, persistent, []);
        check(Reason(unavailable, "missing_critical_flag") && Reason(unavailable, "missing_critical_attributes")
            && Reason(unavailable, "unresolved_active_buff") && Reason(unavailable, "part_damage_roll_relation_unavailable"),
            "Missing observations retain all independent reasons rather than guessing critical parameters");
        var root = Obj("""{"attributeType":"CriticalRate"}""");
        ReportCriticalEvidence report = new(new Dictionary<string, EvidenceObject> { ["buff"] = root }, new Dictionary<string, string> { ["42"] = "buff" });
        var record = Obj("""{"uid":"source","event_key":"42","target_actor_id":"actor","enable_observations":[{"line_no":60,"status":"duplicate"},{"line_no":55,"status":"observed"}]}""");
        var window = Obj("""{"uid":"window","uid_aliases":["source"],"event_key":"42","target_actor_id":"actor","snapshot_update":true}""");
        var withObservation = new EvidenceObject(new Dictionary<string, EvidenceValue>(hit.Fields, StringComparer.Ordinal) { ["critical_observation"] = observation });
        var attached = report.Attach([new(withObservation, new Dictionary<System.Numerics.BigInteger, EvidenceValue>(),
            new Dictionary<System.Numerics.BigInteger, EvidenceValue>(), new Dictionary<System.Numerics.BigInteger, EvidenceValue>())], [record], [window]);
        check(attached.Windows[0].Get("critical_state_change_lines") is EvidenceArray { Items.Count: 1 } lines
            && lines.Items[0] is EvidenceInteger { Value: var line } && line == 55,
            "Numeric resource mapping and UID aliases carry non-duplicate state changes into the report window");
        check(attached.Hits[0].Evidence.Get("critical_context") is EvidenceObject context && Reason(context, "critical_attribute_changed_after_snapshot"),
            "The report entry applies the same state-change invalidation used by standalone critical diagnostics");
        check(window.Get("critical_state_change_lines") is EvidenceNull && withObservation.Get("critical_context") is EvidenceNull,
            "Critical report projection leaves allocation windows and captured hits untouched");
        var owned = report.AttachOwned([attached.Hits[0] with { Evidence = (EvidenceObject)EvidenceJson.Clone(withObservation) }],
            [record], [(EvidenceObject)EvidenceJson.Clone(window)]);
        check(EvidenceJsonSignature.Sorted(owned.Hits[0].Evidence) == EvidenceJsonSignature.Sorted(attached.Hits[0].Evidence)
            && EvidenceJsonSignature.Sorted(owned.Windows[0]) == EvidenceJsonSignature.Sorted(attached.Windows[0]),
            "Private critical projection preserves complete per-hit reasons and UID-alias window change evidence");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)observation.Get("values")).Fields)["9"] = new EvidenceReal(.75);
        check(((EvidenceObject)((EvidenceObject)attached.Hits[0].Evidence.Get("critical_observation")).Get("values")).Get("9")
            is EvidenceReal { Value: .25 }, "The public critical entry retains nested observation isolation after private-path optimization");
    }
}
