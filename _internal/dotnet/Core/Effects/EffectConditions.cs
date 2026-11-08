using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Observed state may prove a condition; missing state never proves its absence.</summary>
public static class EffectConditions
{
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => BuffEvidence.Object(fields);
    private static string Kind(EvidenceObject value) => CatalogValues.Text(CatalogValues.Or(value.Get("type"), Text("")));
    private static bool Is(EvidenceValue value, params string[] choices) => value is EvidenceText text && choices.Contains(text.Value, StringComparer.Ordinal);
    private static BigInteger? Mask(EvidenceValue value) => value is EvidenceInteger integer && integer.Value.Sign >= 0
        && integer.Value < BigInteger.One << 64 ? integer.Value : null;

    public static HashSet<string> DamageTypeElements(EvidenceValue condition)
    {
        HashSet<string> result = new(StringComparer.Ordinal);
        if (condition is not EvidenceObject obj) return result;
        if (Kind(obj) == "all")
        {
            foreach (var child in CatalogValues.Iterable(CatalogValues.Or(obj.Get("conditions"), new EvidenceArray([]))))
                if (child is EvidenceObject) result.UnionWith(DamageTypeElements(child));
        }
        else if (Kind(obj) == "damage_type_in")
        {
            foreach (var element in CatalogValues.Iterable(CatalogValues.Or(obj.Get("elements"), new EvidenceArray([]))))
                if (CatalogValues.Truth(element)) result.Add(CatalogValues.Text(element));
        }
        return result;
    }

    public static bool AppliesToElement(string? effectElement, string? damageElement, string? damageSchool = null)
    {
        var element = string.IsNullOrEmpty(effectElement) ? "all" : effectElement;
        if (element == "all") return true;
        if (element is "physical" or "spell")
        {
            if (damageSchool is not null) return element == damageSchool;
            return element == "physical" ? damageElement == "physical"
                : damageElement is "fire" or "pulse" or "cryst" or "natural" or "ether";
        }
        return damageElement is not null && element == damageElement;
    }

    public static bool AppliesToHit(EvidenceObject effect, string? damageElement, string? damageSchool = null)
    {
        var element = CatalogValues.Text(CatalogValues.Or(effect.Get("element"), Text("all")));
        var conditionElements = DamageTypeElements(effect.Get("condition"));
        return conditionElements.Count > 0 && (element == "all" || conditionElements.Contains(element))
            || AppliesToElement(element, damageElement, damageSchool);
    }

    public static EvidenceObject ElementFilter(string? effectElement, string? damageElement, string? damageSchool = null)
    {
        var element = string.IsNullOrEmpty(effectElement) ? "all" : effectElement;
        var reason = element is "physical" or "spell" ? "damage_school_filtered" : "damage_element_filtered";
        return Object(("reason", Text(reason)), ("reason_group", Text("element_mismatch")), ("filter_kind", Text(reason)),
            ("effect_element", Text(element)), ("hit_damage_element", BuffEvidence.Text(damageElement)),
            ("hit_damage_school", BuffEvidence.Text(damageSchool)));
    }

    public static EvidenceObject? BlackboardCondition(string? key) => key?.ToLowerInvariant() is
        "physical_res_down" or "physical_vulnerable_dmg_increase" or "phy_resist_down"
        ? Object(("type", Text("damage_type_in")), ("source", Text("blackboard_key")),
            ("elements", new EvidenceArray([Text("physical")]))) : null;

    public static EvidenceObject AttachBlackboardCondition(EvidenceObject effect, string? key)
    {
        if (CatalogValues.Truth(effect.Get("condition")) || BlackboardCondition(key) is not { } condition) return effect;
        return new(new Dictionary<string, EvidenceValue>(effect.Fields, StringComparer.Ordinal)
        {
            ["condition"] = condition,
        });
    }

    public static EvidenceObject? Failure(EvidenceObject effect, EvidenceObject hit)
    {
        if (!effect.Fields.ContainsKey("condition")) return null;
        Dictionary<string, EvidenceValue> missing = new(StringComparer.Ordinal)
        {
            ["reason"] = Text("condition_state_missing"), ["reason_group"] = Text("condition_unobservable"),
        };
        EvidenceObject Missing(string detail) => new(new Dictionary<string, EvidenceValue>(missing) { ["detail"] = Text(detail) });
        if (effect.Get("condition") is not EvidenceObject condition) return Missing("malformed_condition");
        var kind = Kind(condition);
        missing["condition_type"] = Text(kind);
        missing["condition_source"] = condition.Get("source");
        if (kind == "always") return null;
        if (kind == "value_compare")
        {
            if (BuffEvidence.OptionalFloat(condition.Get("left")) is not { } left || BuffEvidence.OptionalFloat(condition.Get("right")) is not { } right
                || !Is(condition.Get("compare"), "Equals")) return Missing("missing_or_invalid_comparison_value");
            return left == right ? null : Object(("reason", Text("value_comparison_unsatisfied")), ("reason_group", Text("condition_unsatisfied")));
        }
        if (kind == "damage_decorate_mask")
        {
            if (Mask(condition.Get("mask")) is not BigInteger required || !Is(condition.Get("check"), "HasAll", "HasAny"))
                return Missing("missing_or_invalid_damage_decorate_mask");
            var all = Is(condition.Get("check"), "HasAll");
            var actual = hit.Get("damage_decorate_mask");
            if (actual is EvidenceNull)
            {
                if (Is(hit.Get("static_damage_decorate_mask_source"), "current_typed_skill_or_buff_exact_unit_generation_only")
                    && Mask(hit.Get("static_damage_decorate_mask")) is BigInteger staticMask)
                {
                    var overlap = staticMask & (0x22784 | 0x4001C000 | 0x0FD00038) & required;
                    if (all ? overlap == required : overlap != 0) return null;
                }
                return Missing("missing_or_invalid_damage_decorate_mask");
            }
            if (Mask(actual) is not BigInteger observed) return Missing("missing_or_invalid_damage_decorate_mask");
            return (all ? (observed & required) == required : (observed & required) != 0) ? null
                : Unsatisfied("damage_decorate_mask_filtered");
        }
        if (kind is "all" or "any")
        {
            if (condition.Get("conditions") is not EvidenceArray { Items.Count: > 0 } children || children.Items.Any(child => child is not EvidenceObject))
                return Missing("malformed_compound_condition");
            var failures = children.Items.Select(child => Failure(Object(("condition", child)), hit)).ToArray();
            if (kind == "any" && failures.Any(failure => failure is null)) return null;
            return failures.FirstOrDefault(failure => failure is not null && Is(failure.Get("reason_group"), kind == "all" ? "condition_unsatisfied" : "condition_unobservable"))
                ?? failures.FirstOrDefault(failure => failure is not null);
        }
        if (kind is "target_hp_compare" or "target_hp_ratio_lte")
        {
            var compare = kind == "target_hp_compare" ? condition.Get("compare") : Text("LE");
            var ratio = kind == "target_hp_compare" ? condition.Get("is_ratio") : new EvidenceBoolean(true);
            var threshold = BuffEvidence.OptionalFloat(condition.Get("threshold"));
            var subject = condition.Fields.GetValueOrDefault("subject_side") ?? Text("defender");
            if (!Is(subject, "attacker", "defender")) return Missing("invalid_condition_subject");
            var attacker = Is(subject, "attacker");
            var hp = BuffEvidence.OptionalFloat(hit.Get(attacker ? "attacker_hp_before" : "enemy_hp_before"));
            var maximum = BuffEvidence.OptionalFloat(hit.Get(attacker ? "attacker_max_hp" : "target_enemy_max_hp"));
            if (!Is(compare, "LT", "LE", "GT", "GE", "EQ", "NE") || ratio is not EvidenceBoolean isRatio
                || threshold is null or < 0 || hp is null or < 0) return Missing("invalid_hp_comparison");
            if (isRatio.Value && (maximum is null or <= 0 || hp > maximum || threshold > 1))
                return Missing("missing_explicit_maximum_hp");
            var value = isRatio.Value ? hp.Value / maximum!.Value : hp.Value;
            var passed = ((EvidenceText)compare).Value switch
            {
                "LT" => value < threshold, "LE" => value <= threshold, "GT" => value > threshold,
                "GE" => value >= threshold, "EQ" => value == threshold, _ => value != threshold,
            };
            return passed ? null : Object(("reason", Text("target_hp_condition_unsatisfied")),
                ("reason_group", Text("condition_unsatisfied")), ("condition_type", Text(kind)), ("condition_compare", compare),
                ("condition_threshold", new EvidenceReal(threshold.Value)), ("target_hp_before", new EvidenceReal(hp.Value)),
                ("target_max_hp", maximum is null ? EvidenceNull.Value : new EvidenceReal(maximum.Value)), ("compared_value", new EvidenceReal(value)));
        }
        if (kind == "target_has_buff")
        {
            if (condition.Get("buff_ids") is not EvidenceArray { Items.Count: > 0 } ids
                || ids.Items.Any(id => id is not EvidenceText { Value.Length: > 0 })) return Missing("invalid_required_buff_ids");
            var subject = condition.Fields.GetValueOrDefault("subject_side") ?? Text("defender");
            if (!Is(subject, "attacker", "defender")) return Missing("invalid_condition_subject");
            var attacker = Is(subject, "attacker");
            if (hit.Get(attacker ? "_active_attacker_buff_ids" : "_active_target_buff_ids") is not EvidenceArray active)
                return Missing("missing_target_buff_state");
            if (ids.Items.Any(id => active.Items.Any(observed => EvidenceJson.PythonEquals(id, observed)))) return null;
            if (hit.Get(attacker ? "attacker_buff_state_complete" : "target_buff_state_complete") is not EvidenceBoolean { Value: true })
                return new(new Dictionary<string, EvidenceValue>(Missing("incomplete_target_buff_state").Fields, StringComparer.Ordinal)
                {
                    ["condition_buff_ids"] = ids,
                });
            return Object(("reason", Text("target_buff_missing")), ("reason_group", Text("condition_unsatisfied")), ("condition_buff_ids", ids));
        }
        if (kind == "damage_type_in")
        {
            string[] valid = ["physical", "real", "fire", "pulse", "cryst", "lifedrain", "natural", "ether"];
            var actual = hit.Get("damage_element");
            if (condition.Get("elements") is not EvidenceArray { Items.Count: > 0 } elements
                || elements.Items.Any(element => !Is(element, valid)) || !Is(actual, valid)) return Missing("unresolved_damage_type");
            return elements.Items.Any(element => EvidenceJson.PythonEquals(element, actual)) ? null
                : Object(("reason", Text("damage_type_filtered")), ("reason_group", Text("condition_unsatisfied")),
                    ("condition_type", Text(kind)), ("condition_elements", elements), ("damage_element", actual));
        }
        missing["reason"] = Text("condition_type_unsupported");
        return Missing("unsupported_condition");
    }

    private static EvidenceObject Unsatisfied(string reason) => Object(("reason", Text(reason)), ("reason_group", Text("condition_unsatisfied")));
}
