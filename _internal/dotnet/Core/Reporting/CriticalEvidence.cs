using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record CriticalBuffProfile(bool Missing, IReadOnlyList<int> Attributes, bool Processors);

/// <summary>Critical evidence explains the recorded outcome independently of the rDMG allocation.</summary>
public static class CriticalEvidence
{
    private const string Prefix = "Beyond.Gameplay.Core.";
    private static readonly EvidenceArray Empty = new([]);
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Int(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => (CatalogValues.Or(value, Empty) as EvidenceArray)?.Items ?? [];
    private static int? Attribute(EvidenceValue value) => value is EvidenceText { Value: "CriticalRate" } ? 9
        : value is EvidenceText { Value: "CriticalDamageIncrease" } ? 10 : null;
    private static bool Numeric(EvidenceValue value) => value is EvidenceInteger or EvidenceReal;
    private static double Real(EvidenceValue value) => value switch
        { EvidenceInteger integer => (double)integer.Value, EvidenceReal number => number.Value, _ => throw new InvalidDataException("Expected numeric critical evidence") };
    private static bool Finite(EvidenceValue value) => Numeric(value) && double.IsFinite(Real(value));

    public static CriticalBuffProfile Profile(EvidenceValue root)
    {
        if (root is not EvidenceObject) return new(true, [], false);
        HashSet<int> attributes = [];
        var processors = false;
        Stack<EvidenceValue> pending = new([root]);
        while (pending.TryPop(out var node))
        {
            if (node is EvidenceObject obj)
            {
                var kind = Text(obj.Get("$type"));
                if (kind == Prefix + "DamageAction.DamageUnit") continue;
                if (kind is Prefix + "AttackCriticalRateProcessor" or Prefix + "AttackerCriticalDamageProcessor") processors = true;
                if (Attribute(obj.Get("attributeType")) is { } attribute)
                {
                    attributes.Add(attribute);
                    if (kind == Prefix + "InstantModifyAttribute") processors = true;
                }
                if (kind == Prefix + "InstantModifyAttribute" && obj.Get("modifier") is EvidenceObject modifier
                    && Attribute(modifier.Get("attributeType")) is not null) processors = true;
                foreach (var value in obj.Fields.Values) pending.Push(value);
            }
            else if (node is EvidenceArray array) foreach (var value in array.Items) pending.Push(value);
        }
        return new(false, attributes.Order().ToArray(), processors);
    }

    public static EvidenceObject Build(EvidenceObject hit, EvidenceObject? observation,
        IReadOnlyDictionary<string, CriticalBuffProfile> profiles, IReadOnlyList<EvidenceObject> windows)
    {
        HashSet<string> reasons = new(StringComparer.Ordinal);
        EvidenceObject Unavailable() => BuffEvidence.Object(("version", new EvidenceInteger(1)), ("status", new EvidenceText("unavailable")),
            ("reasons", new EvidenceArray(reasons.Order(PythonDisplay.CodePointComparer).Select(reason => (EvidenceValue)new EvidenceText(reason)).ToArray())));
        EvidenceObject Verified(bool critical, double rate, double bonus, EvidenceValue uncapped, EvidenceValue cap, string source) =>
            BuffEvidence.Object(("version", new EvidenceInteger(1)), ("status", new EvidenceText("verified")), ("isCritical", new EvidenceBoolean(critical)),
                ("critRate", new EvidenceReal(rate)), ("critDamageBonus", new EvidenceReal(bonus)), ("uncappedDamage", BuffEvidence.Clone(uncapped)),
                ("damageCap", BuffEvidence.Clone(cap)), ("source", new EvidenceText(source)));
        var hitValue = hit.Get("hit_value");
        var rawValue = hit.Fields.GetValueOrDefault("raw_hit_value") ?? hitValue;
        var overkill = Int(hit.Get("overkill_damage")) > 0;
        if (hit.Get("damage_element") is EvidenceText { Value: "lifedrain" } && Truth(hit.Get("critical_flag_observed"))
            && EvidenceJson.PythonEquals(hit.Get("crit_flag"), new EvidenceInteger(0)) && hit.Get("damage_calculation") is EvidenceObject)
            return Verified(false, 0, 0, rawValue, overkill ? hitValue : EvidenceNull.Value, "exact_lifedrain_no_critical_branch");
        if (!Truth(hit.Get("critical_flag_observed"))) reasons.Add("missing_critical_flag");
        var valuesEvidence = observation?.Get("values") as EvidenceObject;
        if (observation is null || !EvidenceJson.PythonEquals(observation.Get("template"), hit.Get("character_key"))
            || valuesEvidence is null || !valuesEvidence.Fields.ContainsKey("9") || !valuesEvidence.Fields.ContainsKey("10"))
            reasons.Add("missing_critical_attributes");
        var calculation = hit.Get("damage_calculation") as EvidenceObject;
        if (calculation?.Get("damageProcessors") is not EvidenceArray) reasons.Add("missing_exact_damage_unit");
        if (Int(hit.Get("part_inst_id")) != 0) reasons.Add("part_damage_roll_relation_unavailable");
        foreach (var id in Items(hit.Get("_active_attacker_buff_ids")).Concat(Items(hit.Get("_active_target_buff_ids"))).Select(Text).Distinct(StringComparer.Ordinal))
        {
            if (!profiles.TryGetValue(id, out var profile) || profile.Missing) reasons.Add("unresolved_active_buff");
            else if (profile.Processors) reasons.Add("conditional_critical_modifier");
        }
        foreach (var window in windows)
        {
            if (!profiles.TryGetValue(Text(window.Get("event_key")), out var profile) || profile.Attributes.Count == 0 || profile.Processors || observation is null) continue;
            var target = Text(CatalogValues.Or(window.Get("target_actor_id"), window.Get("owner_raw")));
            if (target != Text(hit.Get("source_actor_id")) && !EvidenceJson.PythonEquals(window.Get("target_character_key"), hit.Get("character_key"))) continue;
            List<EvidenceValue> changes = Truth(window.Get("end_is_observation_boundary")) ? [] : [window.Get("end_line_no")];
            changes.AddRange(Items(window.Get("critical_state_change_lines")));
            if (!Truth(window.Get("snapshot_update"))) changes.Add(window.Fields.GetValueOrDefault("line_no") ?? window.Get("start_line_no"));
            foreach (var attr in profile.Attributes)
            {
                var key = attr.ToString(System.Globalization.CultureInfo.InvariantCulture);
                var observedLine = observation.Get("lines") is EvidenceObject lines ? Int(lines.Get(key)) : BigInteger.Zero;
                if (changes.Any(value => value is EvidenceInteger integer && observedLine < integer.Value && integer.Value <= Int(hit.Get("line_no"))))
                    reasons.Add("critical_attribute_changed_after_snapshot");
                var observedTime = observation.Get("times") is EvidenceObject times ? times.Get(key) : EvidenceNull.Value;
                if (window.Get("end_line_no") is EvidenceNull && !Truth(window.Get("end_is_observation_boundary"))
                    && observedTime is EvidenceInteger time && window.Get("end_ts_ms") is EvidenceInteger end
                    && time.Value <= end.Value && end.Value <= Int(hit.Fields.GetValueOrDefault("ts_ms") ?? new EvidenceInteger(-1)))
                    reasons.Add("critical_attribute_changed_after_snapshot");
            }
        }
        if (reasons.Count > 0) return Unavailable();
        var values = new Dictionary<int, double> { [9] = Real(valuesEvidence!.Get("9")), [10] = Real(valuesEvidence.Get("10")) };
        var processorCount = 0;
        foreach (var processor in ((EvidenceArray)calculation!.Get("damageProcessors")).Items)
        {
            if (processor is not EvidenceObject obj) { reasons.Add("invalid_damage_processor"); continue; }
            var kind = Text(obj.Get("$type"));
            int attr;
            EvidenceValue parameter;
            string operation;
            if (kind == Prefix + "DamageScaleProcessor") continue;
            if (kind == Prefix + "AttackCriticalRateProcessor")
            {
                attr = 9; operation = "Addition"; parameter = obj.Get("addition");
            }
            else if (kind == Prefix + "InstantModifyAttribute")
            {
                if (obj.Get("modifyTargetSide") is EvidenceText { Value: "Defender" }) continue;
                if (obj.Get("modifyTargetSide") is not EvidenceText { Value: "Attacker" }) { reasons.Add("unresolved_modifier_target"); continue; }
                var modifier = obj.Get("modifier") as EvidenceObject;
                if (modifier?.Get("modifyAttributeType") is not EvidenceText { Value: "Specific" }) { reasons.Add("unresolved_modifier_attribute"); continue; }
                if (Attribute(modifier.Get("attributeType")) is not { } attribute) continue;
                attr = attribute; operation = Text(modifier.Get("formulaItem")); parameter = modifier.Get("param");
            }
            else { reasons.Add("unsupported_damage_processor"); continue; }
            processorCount++;
            EvidenceValue value = EvidenceNull.Value;
            if (parameter is EvidenceObject param)
            {
                if (param.Get("useBlackboardKey") is EvidenceBoolean { Value: false }) value = param.Get("value");
                else if (param.Get("useBlackboardKey") is EvidenceBoolean { Value: true }) reasons.Add("unresolved_critical_blackboard_binding");
            }
            if (!Finite(value)) reasons.Add("missing_critical_modifier_value");
            else if (operation == "Addition") values[attr] += Real(value);
            else if (operation == "FinalMultiplier") values[attr] *= Real(value);
            else reasons.Add("unsupported_critical_modifier_operation");
        }
        if (processorCount > 1) reasons.Add("combined_critical_processors_unresolved");
        var probability = values[9] > 0 ? values[9] : 0;
        if (probability > 1) probability = 1;
        var bonus = values[10];
        var criticalFlag = EvidenceJson.PythonEquals(hit.Get("crit_flag"), new EvidenceInteger(1));
        if (hit.Get("damage_element") is EvidenceText { Value: "lifedrain" }) { probability = 0; bonus = 0; }
        if (!double.IsFinite(values[9]) || !double.IsFinite(bonus) || bonus < 0) reasons.Add("invalid_critical_attributes");
        if (probability == 0 && criticalFlag || probability == 1 && !criticalFlag) reasons.Add("critical_outcome_conflicts_with_parameters");
        EvidenceValue damageCap = EvidenceNull.Value;
        var uncappedDamage = rawValue;
        if (probability is 0 or 1 || bonus == 0) uncappedDamage = hitValue;
        else if (overkill) damageCap = hitValue;
        else if (Truth(hit.Get("enemy_hp_after_observed")))
        {
            damageCap = hit.Get("enemy_hp_before");
            if (!Finite(damageCap) || EffectIdentity.CompareKeys(damageCap, hitValue) < 0) reasons.Add("inconsistent_pre_hit_hp");
        }
        else reasons.Add("missing_pre_hit_hp");
        return reasons.Count > 0 ? Unavailable() : Verified(criticalFlag, probability, bonus, uncappedDamage, damageCap,
            "bound_entity_attributes_and_exact_damage_unit");
    }
}
