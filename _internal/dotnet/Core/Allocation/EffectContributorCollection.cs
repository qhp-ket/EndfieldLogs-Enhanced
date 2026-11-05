using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Match recipients and retain only observed, applicable and approved sources in the per-hit model.</summary>
public sealed class EffectContributorCollection(AllocationDebug debug)
{
    private sealed record Candidate(EvidenceObject Window, IReadOnlyList<EvidenceValue> Effects, bool Attacker, bool Enemy,
        IReadOnlySet<string> Uids, bool PacketMatch, string Source);
    private sealed record Matched(string Zone, double Rate, EvidenceValue Attribute);
    private static readonly HashSet<string> Zones = new(["atk", "dmg_inc", "amp", "fragile", "vuln_taken", "res", "combo", "arts_strength", "prod_dmg_inc", "prod_vuln_taken"], StringComparer.Ordinal);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static long Coordinate(EvidenceValue value) => checked((long)EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0))));
    private static void Flag(HitAllocation state, string key = "rdps_unresolved_effect_conditions") => ((Dictionary<string, EvidenceValue>)state.Hit.Fields)[key] = new EvidenceBoolean(true);
    private static void Ignore(HitAllocation state, EvidenceObject row, params (string Key, EvidenceValue Value)[] details)
    {
        if (!state.IncludeDebug) return;
        var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal);
        foreach (var (key, value) in details) fields[key] = BuffEvidence.Clone(value);
        state.IgnoredEffects.Add(new(fields));
    }
    private static EvidenceObject Identity(EvidenceObject window) => BuffEvidence.Object(("uid", window.Get("uid")), ("event_key", window.Get("event_key")));
    private static EvidenceText Str(string value) => new(value);
    private static EvidenceArray Sorted(IEnumerable<string> values) => new(values.Order(PythonDisplay.CodePointComparer).Select(value => (EvidenceValue)Str(value)).ToArray());

    public void Collect(HitAllocation state)
    {
        foreach (var index in state.WindowIndices)
        {
            var candidate = MatchWindow(state, index);
            if (candidate is null) continue;
            foreach (var effect in candidate.Effects.Cast<EvidenceObject>())
            {
                var matched = MatchRecipient(state, candidate, effect);
                if (matched is null || !Allocatable(state, candidate, effect, matched)) continue;
                Record(state, candidate, effect, matched);
            }
        }
    }

    private Candidate? MatchWindow(HitAllocation state, int index)
    {
        var window = state.Windows[index];
        var effects = state.EffectsAtHit[index];
        if (effects.Count == 0)
        {
            if (CatalogValues.Truth(window.Get("_enable_state_unobserved_at_hit")))
            {
                Flag(state);
                Ignore(state, Identity(window), ("reason", Str("unobserved_initial_buff_enable_state")), ("reason_group", Str("condition_unobservable")));
            }
            if (state.LineNumber == 0 && (CatalogValues.Truth(window.Get("snapshot_update")) && EvidenceJson.PythonEquals(window.Get("start_ts_ms"), new EvidenceInteger(state.TimestampMs))
                || EvidenceJson.PythonEquals(window.Get("snapshot_end_ts_ms"), new EvidenceInteger(state.TimestampMs))))
            {
                Flag(state);
                Ignore(state, Identity(window), ("reason", Str("unresolved_buff_snapshot_order")), ("reason_group", Str("condition_unobservable")));
            }
            return null;
        }
        var start = Coordinate(window.Get("start_ts_ms"));
        if (start > state.TimestampMs || state.TimestampMs > Coordinate(window.Get("end_ts_ms"))) return null;
        var line = Coordinate(CatalogValues.Or(window.Get("start_line_no"), window.Get("line_no")));
        if (start == state.TimestampMs && state.LineNumber != 0 && line != 0 && line > state.LineNumber) return null;
        if (start == state.TimestampMs && Text(window.Get("event_key")) == Text(state.Hit.Get("skill_key"))) return null;
        if (CatalogValues.Truth(window.Get("skill_family_key")) && !EvidenceJson.PythonEquals(window.Get("skill_family_key"), state.Hit.Get("skill_family_key"))) return null;
        // Both skill-filter tables in the fixed source are empty; no identifier heuristic is added here.
        var attacker = EvidenceJson.PythonEquals(window.Fields["target_character_key"], new EvidenceText(state.Attacker));
        var enemy = state.Target.Length > 0 && EvidenceJson.PythonEquals(window.Fields["target_character_key"], new EvidenceText(state.Target));
        if (!attacker && !enemy) return null;
        var uids = EffectIdentity.WindowUids(window);
        var packetMatch = uids.Overlaps(state.DefenderModifierUids);
        var actor = Text(window.Get("target_actor_id"));
        if (attacker && Text(state.Hit.Get("source_actor_id")) is { Length: > 0 } sourceActor && actor.Length > 0 && sourceActor != actor)
        {
            if (uids.Overlaps(state.AttackerModifierUids)) Flag(state, "rdps_unresolved_target_binding");
            Ignore(state, Identity(window), ("reason", Str("buff_owner_instance_mismatch")));
            return null;
        }
        if (enemy)
        {
            var targetActor = Text(state.Hit.Get("target_actor_id"));
            if (targetActor.Length > 0 && actor.Length > 0 && targetActor != actor)
            {
                if (packetMatch) Flag(state, "rdps_unresolved_target_binding");
                return null;
            }
            if ((targetActor.Length == 0 || actor.Length == 0) && !packetMatch) { Flag(state, "rdps_unresolved_target_binding"); return null; }
        }
        var source = window.Fields["source_character_key"];
        return CatalogValues.Truth(source) ? new(window, effects, attacker, enemy, uids, packetMatch, CatalogValues.Text(source)) : null;
    }

    private Matched? MatchRecipient(HitAllocation state, Candidate candidate, EvidenceObject effect)
    {
        var window = candidate.Window;
        var zone = CatalogValues.Text(effect.Fields["zone"]);
        if (zone == "atk" && state.Attack.Kind is AttackDependence.Independent or AttackDependence.Unknown)
        {
            if (state.Attack.Kind == AttackDependence.Unknown) Flag(state);
            Ignore(state, Identity(window), ("zone", Str("atk")), ("reason", Str(state.Attack.Kind == AttackDependence.Independent ? "damage_not_scaled_by_attack" : "attack_damage_calculation_unresolved")));
            return null;
        }
        if (state.UnresolvedStackZones.Contains(zone))
        {
            Ignore(state, Identity(window), ("zone", Str(zone)), ("reason", Str("unresolved_stack_zone_baseline")), ("reason_group", Str("condition_unobservable")));
            return null;
        }
        var rate = BuffEvidence.OptionalFloat(effect.Get("rate"));
        if (rate is null)
        {
            state.InvalidNumericAllocation = true;
            Ignore(state, Identity(window), ("reason", Str("invalid_effect_rate")));
            return null;
        }
        string? side = zone switch { "vuln_taken" or "fragile" or "res" or "prod_vuln_taken" => "defender",
            "atk" or "dmg_inc" or "amp" or "combo" or "arts_strength" or "crit" or "prod_dmg_inc" => "attacker", _ => null };
        if (effect.Fields.ContainsKey("recipient_side"))
        {
            if (effect.Get("recipient_side") is EvidenceArray or EvidenceObject) throw new InvalidCastException("Unhashable recipient side");
            if (effect.Get("recipient_side") is not EvidenceText { Value: "attacker" or "defender" } recipient) { Flag(state); return null; }
            side = recipient.Value;
        }
        if (side == "defender" && !candidate.Enemy || side == "attacker" && !candidate.Attacker)
        {
            if (state.IncludeDebug) Ignore(state, debug.Applicable(window, effect, "ignored"), ("reason", Str("effect_recipient_side_mismatch")), ("required_side", Str(side!)));
            return null;
        }
        if (CatalogValues.Truth(state.Hit.Get("packet_modifier_seen")) && candidate.Enemy && candidate.Uids.Count > 0 && zone == "vuln_taken"
            && state.MatchedDefenderSignatures.Contains(EffectIdentity.PacketGuard(effect)) && !candidate.PacketMatch)
        {
            if (state.IncludeDebug) Ignore(state, debug.Applicable(window, effect, "ignored"), ("reason", Str("packet_defender_uid_suppressed")),
                ("reason_group", Str("packet_modifier_uid_mismatch")), ("packet_modifier_guard", Str("defender_uid_selection")),
                ("packet_modifier_seen", new EvidenceBoolean(true)), ("packet_modifier_uids", BuffEvidence.Object(("attacker", Sorted(state.AttackerModifierUids)),
                    ("defender", Sorted(state.DefenderModifierUids)))), ("candidate_uids", Sorted(candidate.Uids)));
            return null;
        }
        var attribute = effect.Get("attr_type");
        if (attribute is EvidenceInteger or EvidenceBoolean)
        {
            var applies = DamageAttributeApplicability.Evaluate(attribute, state.Hit.Get("damage_decorate_mask"), state.Hit.Get("static_damage_decorate_mask"), state.Hit.Get("static_damage_decorate_mask_source"));
            if (applies is null) Flag(state);
            if (applies is not true)
            {
                if (state.IncludeDebug) Ignore(state, debug.Applicable(window, effect, "ignored"),
                    ("reason", Str(applies is null ? "attribute_damage_mask_missing" : "attribute_damage_mask_filtered")),
                    ("reason_group", Str(applies is null ? "condition_unobservable" : "condition_unsatisfied")));
                return null;
            }
        }
        return new(zone, rate.Value, attribute);
    }

    private bool Allocatable(HitAllocation state, Candidate candidate, EvidenceObject effect, Matched matched)
    {
        var zone = matched.Zone;
        bool Reject(string reason, params (string Key, EvidenceValue Value)[] fields)
        {
            if (state.IncludeDebug) Ignore(state, debug.Applicable(candidate.Window, effect, "ignored"), [("reason", Str(reason)), ..fields]);
            return false;
        }
        if (zone == "crit") return Reject("crit_not_allocated");
        if (!Zones.Contains(zone)) return Reject(zone == "res" ? "resistance_counterfactual_unresolved" : "utility_not_allocated");
        if (zone == "arts_strength" && !state.ArtsStrength.Observed) return Reject("arts_strength_only_affects_anomaly_damage");
        if (matched.Rate <= 0) return false;
        if (!EffectConditions.AppliesToHit(effect, state.Element, state.School))
        {
            if (state.IncludeDebug) Ignore(state, debug.Applicable(candidate.Window, effect, "ignored"),
                EffectConditions.ElementFilter(effect.Get("element") is EvidenceNull ? null : CatalogValues.Text(effect.Fields["element"]), state.Element, state.School).Fields.Select(pair => (pair.Key, pair.Value)).ToArray());
            return false;
        }
        if (EffectConditions.Failure(effect, state.Hit) is { Fields.Count: > 0 } failure)
        {
            if (failure.Get("reason_group") is EvidenceText { Value: "condition_unobservable" }) Flag(state);
            if (state.IncludeDebug) Ignore(state, debug.Applicable(candidate.Window, effect, "ignored"), failure.Fields.Select(pair => (pair.Key, pair.Value)).ToArray());
            return false;
        }
        if (candidate.Source != state.Attacker && candidate.Enemy && state.DefenderAllowedEffects.Count > 0 && state.DefenderModifierUids.Count == 0
            && !state.DefenderAllowedEffects.Contains((zone, Text(CatalogValues.Or(effect.Fields["element"], Str("all")))))) return Reject("packet_attr_mismatch");
        if (zone == "res")
        {
            if (state.Element is "real" or "lifedrain") return false;
            if (state.ResistanceNumerator is not double numerator || !double.IsFinite(numerator) || numerator <= 0)
            {
                Flag(state);
                return Reject("resistance_counterfactual_unresolved", ("detail", Str("missing_or_conflicting_hit_resistance")));
            }
        }
        return true;
    }

    private void Record(HitAllocation state, Candidate candidate, EvidenceObject effect, Matched matched)
    {
        IReadOnlyList<ArtsEffectSource> sources;
        if (candidate.Enemy)
        {
            var attributed = ArtsEffectAttribution.Attribute(candidate.Window, effect, state.Windows);
            // Provenance can evaluate historical windows outside this hit's time candidates.
            state.RequiresFullWindowReset |= !ReferenceEquals(state.Windows, attributed.Windows);
            state.Windows = attributed.Windows;
            sources = attributed.Sources;
        }
        else sources = [new(candidate.Source, matched.Rate, null)];
        foreach (var source in sources)
        {
            if (!double.IsFinite(source.Rate)) { state.InvalidNumericAllocation = true; continue; }
            if (source.Rate <= 0) continue;
            if (source.Provider != state.Attacker && effect.Get("external_rdps_allowed") is EvidenceBoolean { Value: false })
            {
                Flag(state, "rdps_unresolved_whitelist_effect");
                if (state.IncludeDebug) Ignore(state, debug.Applicable(candidate.Window, effect, "ignored"), ("reason", Str("external_effect_not_whitelisted")));
                continue;
            }
            if (candidate.Attacker && matched.Attribute is EvidenceInteger or EvidenceBoolean)
            {
                var attribute = EffectIdentity.Integer(matched.Attribute);
                state.CapturedByAttribute[attribute] = state.CapturedByAttribute.GetValueOrDefault(attribute) + source.Rate;
            }
            var self = source.Provider == state.Attacker;
            var record = state.IncludeDebug ? debug.ArtsProvenance(candidate.Window, effect, source.Provider, source.Rate, source.Provenance, self ? "self" : "external") : null;
            if (self)
            {
                if (matched.Zone.StartsWith("prod_", StringComparison.Ordinal))
                    state.SelfFactorByZone[matched.Zone] = state.SelfFactorByZone.GetValueOrDefault(matched.Zone, 1) * (1 + source.Rate);
                else state.SelfByZone[matched.Zone] = state.SelfByZone.GetValueOrDefault(matched.Zone) + source.Rate;
            }
            else
            {
                if (!state.ExternalByZone.TryGetValue(matched.Zone, out var rows)) state.ExternalByZone[matched.Zone] = rows = [];
                rows.Add(new(source.Provider, source.Rate, record));
            }
            if (record is not null)
            {
                if (!state.ContributorsByZone.TryGetValue(matched.Zone, out var rows)) state.ContributorsByZone[matched.Zone] = rows = [];
                rows.Add(record);
            }
        }
    }
}
