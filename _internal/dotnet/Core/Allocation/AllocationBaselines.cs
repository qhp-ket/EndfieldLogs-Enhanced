using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Observed attributes, fixed attack terms and residual evidence for one owned hit.</summary>
public sealed class AllocationBaselines(AllocationDebug debug)
{
    private static readonly string[] DpdZones = ["dmg_inc", "amp", "combo", "vuln_taken", "fragile"];
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static EvidenceObject Object(EvidenceValue value) => CatalogValues.Or(value, BuffEvidence.Object()) as EvidenceObject
        ?? throw new InvalidDataException("Allocation field must be an object");
    private static void Unresolved(HitAllocation state) => ((Dictionary<string, EvidenceValue>)state.Hit.Fields)["rdps_unresolved_effect_conditions"] = new EvidenceBoolean(true);
    private static void Add(HitAllocation state, string zone, double value) => state.SelfByZone[zone] = state.SelfByZone.GetValueOrDefault(zone) + value;
    private static void Explain(HitAllocation state, string zone, EvidenceObject row)
    {
        if (!state.ContributorsByZone.TryGetValue(zone, out var rows)) state.ContributorsByZone[zone] = rows = [];
        rows.Add(row);
    }

    private static IEnumerable<(EvidenceValue Attribute, EvidenceValue Value)> BaselineItems(HitAllocation state)
    {
        if (!state.Input.Hit.BaselineProjectionIsNumeric)
            foreach (var (key, value) in Object(state.Hit.Get("baseline")).Fields) yield return (new EvidenceText(key), value);
        foreach (var (key, value) in state.NumericBaseline) yield return (new EvidenceInteger(key), value);
    }

    public void AttachObserved(HitAllocation state)
    {
        HashSet<BigInteger> observed = [];
        foreach (var (rawAttribute, finalValue) in BaselineItems(state))
        {
            BigInteger attribute;
            try { attribute = EffectIdentity.Integer(rawAttribute); }
            catch (Exception error) when (error is InvalidCastException or FormatException) { continue; }
            if (attribute == 2 || !StaticLoadoutEvidence.AttributeEffects.TryGetValue(attribute, out var mapping)) continue;
            var final = BuffEvidence.OptionalFloat(finalValue);
            if (final is null or < 0) { Unresolved(state); continue; }
            var (zone, element) = mapping;
            if (zone == "crit") continue;
            observed.Add(attribute);
            if (final == 0) continue;
            var applies = DamageAttributeApplicability.Evaluate(new EvidenceInteger(attribute), state.Hit.Get("damage_decorate_mask"),
                state.Hit.Get("static_damage_decorate_mask"), state.Hit.Get("static_damage_decorate_mask_source"));
            if (applies is null && element == state.Element) applies = true;
            if (applies is null) Unresolved(state);
            if (applies is not true || !EffectConditions.AppliesToElement(element, state.Element, state.School)) continue;
            var captured = state.CapturedByAttribute.GetValueOrDefault(attribute);
            var rate = final.Value - captured;
            if (rate < 0) { Unresolved(state); continue; }
            if (rate == 0) continue;
            Add(state, zone, rate);
            if (state.IncludeDebug) Explain(state, zone, debug.Baseline(state.Hit, attribute, zone, element, rate, final.Value, captured));
        }
        foreach (var value in Items(state.Hit.Get("static_multiplier_entries")))
        {
            if (value is not EvidenceObject entry) continue;
            var applicability = StaticEntryApplicability.Evaluate(entry, state.Hit, state.NumericBaseline);
            if (applicability.UnresolvedCondition) Unresolved(state);
            if (!applicability.Applies || entry.Get("zone") is EvidenceText { Value: "atk" } && state.Attack.Kind == AttackDependence.Independent) continue;
            if (entry.Get("attr_type") is EvidenceArray or EvidenceObject) throw new InvalidCastException("Unhashable attribute type");
            if (observed.Any(attribute => EvidenceJson.PythonEquals(entry.Get("attr_type"), new EvidenceInteger(attribute)))) continue;
            var zone = Text(entry.Get("zone"));
            if (BuffEvidence.OptionalFloat(entry.Get("rate")) is not double rate) { state.InvalidNumericAllocation = true; continue; }
            Add(state, zone, rate);
            if (state.IncludeDebug) Explain(state, zone, debug.Static(state.Hit, entry));
        }
    }

    private static BigInteger Coordinate(EvidenceValue value, BigInteger fallback) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(fallback)));
    private static (BigInteger, BigInteger) Stamp(EvidenceObject row, string time, string line, BigInteger lineFallback = default) =>
        (Coordinate(row.Get(time), 0), Coordinate(row.Get(line), lineFallback));

    public void ResolveAttack(HitAllocation state)
    {
        double extra = 0;
        state.AttackBaselineError = null;
        var hit = state.Hit;
        var flat = BuffEvidence.OptionalFloat(hit.Fields.GetValueOrDefault("static_flat_attack") ?? new EvidenceReal(0));
        var baseline = BuffEvidence.OptionalFloat(hit.Get("base_attack_for_percent"));
        if (flat is null or < 0) state.AttackBaselineError = "invalid_flat_attack_baseline";
        else if (flat > 0)
        {
            if (baseline is null or <= 0) state.AttackBaselineError = "missing_base_attack_for_flat_addition";
            else extra += flat.Value / baseline.Value;
        }
        if (state.Attack.Kind == AttackDependence.Affine)
        {
            var calculation = Object(state.Attack.Calculation);
            var custom = Object(calculation.Get("atkCalculation"));
            var resource = Object(calculation.Get("sourceProof")).Get("resourceId");
            var owner = Text(hit.Get("event_inst_id"));
            var current = ((BigInteger)state.TimestampMs, (BigInteger)state.LineNumber);
            var candidates = state.Input.ConditionsByUid is null ? state.Input.ConditionRecords
                : state.Input.ConditionsByUid.GetValueOrDefault(owner);
            var records = (candidates ?? []).Where(row => Text(row.Get("uid")) == owner && EvidenceJson.PythonEquals(row.Get("event_key"), resource)
                && Stamp(row, "ts_ms", "line_no").CompareTo(current) <= 0
                && (row.Get("end_ts_ms") is EvidenceNull || current.CompareTo(Stamp(row, "end_ts_ms", "end_line_no", long.MaxValue)) < 0)
                && (row.Get("snapshot_end_ts_ms") is EvidenceNull || current.CompareTo(Stamp(row, "snapshot_end_ts_ms", "snapshot_end_line_no", long.MaxValue)) < 0)).ToArray();
            double? Parameter(string key)
            {
                var parameter = Object(custom.Get(key));
                var raw = parameter.Get("useBlackboardKey") switch
                {
                    EvidenceBoolean { Value: false } => parameter.Get("value"),
                    EvidenceBoolean { Value: true } when records.Length == 1 => Object(records[0].Get("bb_values")).Get(CatalogValues.Text(parameter.Get("blackboardKey"))),
                    _ => EvidenceNull.Value,
                };
                return BuffEvidence.OptionalFloat(raw);
            }
            var coefficient = Parameter("multiplier");
            var addition = Parameter("addition");
            if (addition is null) state.AttackBaselineError = "missing_damage_base_addition";
            else if (addition != 0)
            {
                var ability = BuffEvidence.OptionalFloat(hit.Get("attack_ability_factor"));
                if (baseline is null or <= 0 || ability is null or <= 0 || coefficient is null or <= 0)
                    state.AttackBaselineError = "missing_attack_scale_for_fixed_damage";
                else
                {
                    var scale = baseline.Value * ability.Value * coefficient.Value;
                    if (!double.IsFinite(scale) || scale <= 0) state.AttackBaselineError = "invalid_attack_scale_for_fixed_damage";
                    else extra += addition.Value / scale;
                }
            }
        }
        if (!double.IsFinite(extra)) state.AttackBaselineError = "invalid_attack_addition_ratio";
        if (state.AttackBaselineError is not null)
        {
            if (state.ExternalByZone.GetValueOrDefault("atk") is { Count: > 0 })
            {
                Unresolved(state);
                if (state.IncludeDebug) state.IgnoredEffects.Add(BuffEvidence.Object(("zone", new EvidenceText("atk")), ("reason", new EvidenceText(state.AttackBaselineError))));
            }
        }
        else if (extra != 0)
        {
            Add(state, "atk", extra);
            if (state.IncludeDebug) Explain(state, "atk", debug.Static(hit, BuffEvidence.Object(("zone", new EvidenceText("atk")),
                ("element", new EvidenceText("all")), ("rate", new EvidenceReal(extra)), ("source_type", new EvidenceText("fixed_attack_basis")),
                ("source_name", new EvidenceText("固定攻击与基础伤害项")), ("evidence_kind", new EvidenceText("explicit_fixed_terms_normalization")),
                ("base_attack", baseline is double b ? new EvidenceReal(b) : EvidenceNull.Value), ("flat_attack", flat is double f ? new EvidenceReal(f) : EvidenceNull.Value))));
        }
    }

    public void CheckRemaining(HitAllocation state)
    {
        if (state.ArtsStrength.Observed)
            foreach (var value in Items(state.Hit.Get("static_arts_strength_entries")))
            {
                if (value is not EvidenceObject entry) continue;
                var points = BuffEvidence.OptionalFloat(entry.Get("rate"));
                if (points is null) { state.InvalidNumericAllocation = true; continue; }
                if (points <= 0) continue;
                Add(state, "arts_strength", points.Value);
                if (state.IncludeDebug) Explain(state, "arts_strength", debug.Static(state.Hit, entry));
            }
        foreach (var zone in DpdZones)
        {
            var bucket = PacketAllocationEvidence.Bucket(zone, state.Hit.Get("dpd_raw") as EvidenceObject);
            if (bucket is null) continue;
            var recognized = state.SelfByZone.GetValueOrDefault(zone) + PythonFloatSum.Sum((state.ExternalByZone.GetValueOrDefault(zone) ?? []).Select(row => row.Rate));
            if (Math.Abs((bucket.Value - 1) - recognized) > 0.003)
                ((Dictionary<string, EvidenceValue>)state.Hit.Fields)["rdps_unresolved_dpd_residual"] = new EvidenceBoolean(true);
        }
    }
}
