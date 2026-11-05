using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

public sealed record EffectRateResult(EvidenceObject Record, double? Rate, string? BlackboardKey);
public sealed record RegistryEffectsResult(EvidenceObject Record, IReadOnlyList<EvidenceObject> Effects);
public sealed record EffectValidationResult(EvidenceObject Record, EvidenceObject? Error);

/// <summary>Resolve only declared runtime rates and retain unresolved or conflicting evidence.</summary>
public static class EffectRegistryRules
{
    private static readonly HashSet<string> Zones = new(["atk", "dmg_inc", "amp", "fragile", "vuln_taken", "res", "combo", "arts_strength", "prod_dmg_inc", "prod_vuln_taken", "crit"], StringComparer.Ordinal);
    private static readonly string[] ControlKeys = ["", "=", "duration", "duration2", "duration_spellvulnerable", "life_time", "lifetime", "max_stack", "max_stack_count", "maxstack", "stack_limit", "stacklimit", "cntmax", "count", "max_count"];
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static EvidenceArray Strings(IEnumerable<string> values) => new(values.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
    private static EvidenceObject Flag(EvidenceObject record, string key) => new(new Dictionary<string, EvidenceValue>(record.Fields, StringComparer.Ordinal) { [key] = new EvidenceBoolean(true) });

    public static IReadOnlySet<string> IgnoredBlackboardKeys(EvidenceObject entry)
    {
        HashSet<string> keys = new(ControlKeys, StringComparer.Ordinal);
        keys.UnionWith(EffectApproval.EffectBlackboardKeys(entry));
        foreach (var field in new[] { "ignored_bb_keys", "self_bb_keys", "allowed_bb_keys" })
            keys.UnionWith(Items(entry.Get(field)).Select(CatalogValues.Text).Where(key => field == "allowed_bb_keys" ? key != "*" : key.Length > 0));
        return keys;
    }

    public static IReadOnlyList<string> UnknownBlackboardKeys(EvidenceObject entry, EvidenceObject record)
    {
        var keys = EffectApproval.BlackboardKeys(record);
        keys.UnionWith(Items(record.Get("attr_mods")).Select(value => Text(((EvidenceObject)value).Get("bb_key"))).Where(key => key.Length > 0));
        keys.ExceptWith(IgnoredBlackboardKeys(entry));
        return keys.Order(PythonDisplay.CodePointComparer).ToArray();
    }

    public static EffectRateResult RuntimeRate(EvidenceObject spec, EvidenceObject record)
    {
        var blackboard = record.Get("bb_values") as EvidenceObject;
        var keys = Items(spec.Get("bb_keys")).Select(CatalogValues.Text).Where(key => key.Length > 0).Distinct(StringComparer.Ordinal).ToList();
        var primary = Text(spec.Get("bb_key"));
        if (primary.Length > 0 && !keys.Contains(primary, StringComparer.Ordinal)) keys.Insert(0, primary);
        var present = keys.Where(key => blackboard?.Fields.ContainsKey(key) == true)
            .Select(key => (Key: key, Value: BuffEvidence.OptionalFloat(blackboard!.Get(key)))).ToArray();
        if (present.Length > 0)
        {
            if (present.Any(pair => pair.Value is null or < 0)) return new(Flag(record, "rdps_invalid_runtime_rate"), null, null);
            if (present.Select(pair => pair.Value).Distinct().Count() != 1) return new(Flag(record, "rdps_conflicting_runtime_rate"), null, null);
            return new(record, present[0].Value, present[0].Key);
        }
        if (Text(spec.Get("formula")) == "atk_add_plus_mult_consume_half_for_other_targets")
        {
            var addKey = Text(CatalogValues.Or(spec.Get("add_bb_key"), new EvidenceText("atk_up_add")));
            var multKey = Text(CatalogValues.Or(spec.Get("mult_bb_key"), new EvidenceText("atk_up_mult")));
            var consumeKey = Text(CatalogValues.Or(spec.Get("consume_bb_key"), new EvidenceText("consume_layer")));
            var add = BuffEvidence.OptionalFloat(blackboard?.Get(addKey) ?? EvidenceNull.Value);
            var mult = BuffEvidence.OptionalFloat(blackboard?.Get(multKey) ?? EvidenceNull.Value);
            var consume = BuffEvidence.OptionalFloat(blackboard?.Get(consumeKey) ?? EvidenceNull.Value);
            if (add is null || mult is null || consume is null) return new(record, null, null);
            // Keep separate operations, matching the reference's binary64 arithmetic.
            var product = mult.Value * consume.Value;
            var rate = add.Value + product;
            var source = Text(record.Get("source_character_key"));
            var target = Text(record.Get("target_character_key"));
            if (source.Length > 0 && target.Length > 0 && source != target)
            {
                var factor = BuffEvidence.OptionalFloat(spec.Fields.TryGetValue("other_target_multiplier", out var declared) ? declared : new EvidenceReal(0.5));
                if (factor is null) return new(record, null, null);
                rate *= factor.Value;
            }
            return double.IsFinite(rate) && rate >= 0 ? new(record, rate, primary.Length > 0 ? primary : addKey) : new(record, null, null);
        }
        if (Text(spec.Get("value_source")).ToLowerInvariant() is "constant" or "static_literal")
        {
            var rate = BuffEvidence.OptionalFloat(spec.Get("rate"));
            return rate is >= 0 ? new(record, rate, primary.Length > 0 ? primary : null) : new(record, null, null);
        }
        return new(record, null, null);
    }

    public static RegistryEffectsResult ZoneEffects(EvidenceObject record, EvidenceObject entry)
    {
        List<EvidenceObject> effects = [];
        if (CatalogValues.Truth(entry.Get("dynamic"))) return new(record, effects);
        foreach (var spec in Items(entry.Get("effects")).OfType<EvidenceObject>())
        {
            var zone = Text(spec.Get("zone"));
            if (!Zones.Contains(zone)) continue;
            var resolved = RuntimeRate(spec, record);
            record = resolved.Record;
            if (resolved.Rate is null) continue;
            Dictionary<string, EvidenceValue> effect = new(StringComparer.Ordinal)
            {
                ["zone"] = new EvidenceText(zone), ["element"] = new EvidenceText(Text(CatalogValues.Or(spec.Get("element"), new EvidenceText("all")))),
                ["rate"] = new EvidenceReal(resolved.Rate.Value),
            };
            if (resolved.BlackboardKey is { Length: > 0 } key)
            {
                effect["_registry_bb_key"] = new EvidenceText(key);
                effect["_registry_bb_keys"] = Strings(Items(spec.Get("bb_keys")).Select(CatalogValues.Text).Append(key).Append(Text(spec.Get("bb_key")))
                    .Where(value => value.Length > 0).Distinct(StringComparer.Ordinal).Order(PythonDisplay.CodePointComparer));
                if (CatalogValues.Truth(spec.Get("expose_bb_key"))) effect["bb_key"] = new EvidenceText(key);
            }
            if (spec.Fields.TryGetValue("condition", out var condition)) effect["condition"] = BuffEvidence.Clone(condition);
            effects.Add(new(effect));
        }
        return new(record, effects);
    }

    public static EffectValidationResult Validate(EvidenceObject entry, EvidenceObject source)
    {
        var clean = new Dictionary<string, EvidenceValue>(source.Fields, StringComparer.Ordinal);
        clean.Remove("rdps_invalid_runtime_rate");
        clean.Remove("rdps_conflicting_runtime_rate");
        EvidenceObject record = new(clean);
        EffectValidationResult Error(string reason, params (string Key, EvidenceValue Value)[] details) => new(record,
            new(new[] { new KeyValuePair<string, EvidenceValue>("reason", new EvidenceText(reason)) }
                .Concat(details.Select(pair => new KeyValuePair<string, EvidenceValue>(pair.Key, pair.Value))).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal)));
        if (CatalogValues.Truth(record.Get("rdps_unresolved_semantic_condition")))
            return Error("unresolved_semantic_condition", ("condition_errors", record.Get("rdps_unresolved_semantic_condition")));
        if (CatalogValues.Truth(record.Get("rdps_unresolved_dynamic_effect"))) return Error("unresolved_dynamic_effect_parameters");
        if (!EffectApproval.BlackboardAllowed(entry, record)) return Error("registry allowed_bb_keys check failed");
        var unknown = UnknownBlackboardKeys(entry, record);
        if (unknown.Count > 0) return Error("verified rDPS buff carried BB keys not declared by rdps_semantics_registry", ("unknown_bb_keys", Strings(unknown)));
        if (CatalogValues.Truth(entry.Get("dynamic"))) return new(record, null);
        var resolved = ZoneEffects(record, entry);
        record = resolved.Record;
        if (CatalogValues.Truth(record.Get("rdps_conflicting_runtime_rate"))) return Error("conflicting_runtime_rate");
        if (CatalogValues.Truth(record.Get("rdps_invalid_runtime_rate"))) return Error("invalid_runtime_rate");
        if (CatalogValues.Truth(entry.Get("effects")) && resolved.Effects.Count != Items(entry.Get("effects")).Count())
            return Error("verified rDPS buff did not expose required runtime BB value declared by rdps_semantics_registry",
                ("required_bb_keys", Strings(EffectApproval.EffectBlackboardKeys(entry).Order(PythonDisplay.CodePointComparer))));
        return new(record, null);
    }
}
