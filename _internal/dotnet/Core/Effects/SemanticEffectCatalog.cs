using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Current typed branches define rates and conditions; approvals only restrict their allocation scope.</summary>
public sealed class SemanticEffectCatalog(IReadOnlyDictionary<string, EvidenceObject> roots,
    IReadOnlyDictionary<string, EvidenceObject> zones, EffectApproval approval, ModifierConditionCatalog? conditions = null)
{
    private readonly ModifierConditionCatalog conditions = conditions ?? new(roots);
    private static readonly Dictionary<string, (int Type, string Formula, string Zone, string Element)> Attributes = new(StringComparer.Ordinal)
    {
        ["Atk"] = (2, "BaseMultiplier", "atk", "all"),
        ["NormalAttackDamageIncrease"] = (17, "BaseAddition", "dmg_inc", "all"),
        ["UltimateSkillDamageIncrease"] = (28, "BaseAddition", "dmg_inc", "all"),
        ["NormalSkillDamageIncrease"] = (32, "BaseAddition", "dmg_inc", "all"),
        ["ComboSkillDamageIncrease"] = (33, "BaseAddition", "dmg_inc", "all"),
        ["PhysicalDamageIncrease"] = (50, "BaseAddition", "dmg_inc", "physical"),
        ["FireDamageIncrease"] = (51, "BaseAddition", "dmg_inc", "fire"),
        ["PulseDamageIncrease"] = (52, "BaseAddition", "dmg_inc", "pulse"),
        ["CrystDamageIncrease"] = (53, "BaseAddition", "dmg_inc", "cryst"),
        ["NaturalDamageIncrease"] = (54, "BaseAddition", "dmg_inc", "natural"),
        ["FireEnhancedDmgIncrease"] = (65, "BaseAddition", "amp", "fire"),
        ["PulseEnhancedDmgIncrease"] = (66, "BaseAddition", "amp", "pulse"),
        ["CrystEnhancedDmgIncrease"] = (67, "BaseAddition", "amp", "cryst"),
        ["NaturalEnhancedDmgIncrease"] = (68, "BaseAddition", "amp", "natural"),
        ["PhysicalAndSpellInflictionEnhance"] = (87, "BaseAddition", "arts_strength", "all"),
    };
    private static readonly Dictionary<string, string> Vulnerabilities = new(StringComparer.Ordinal)
    {
        ["PhysicalVulnerableDmgIncrease"] = "physical", ["FireVulnerableDmgIncrease"] = "fire", ["PulseVulnerableDmgIncrease"] = "pulse",
        ["CrystVulnerableDmgIncrease"] = "cryst", ["NaturalVulnerableDmgIncrease"] = "natural",
    };
    private static readonly Dictionary<int, int> AttributeMasks = new() { [17] = 0x20484, [28] = 0x200, [32] = 0x100, [33] = 0x2000 };
    private static EvidenceText T(string value) => new(value);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, T("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static bool Is(EvidenceValue value, params string[] choices) => value is EvidenceText text && choices.Contains(text.Value, StringComparer.Ordinal);
    private static EvidenceObject Obj(params (string Key, EvidenceValue Value)[] fields) => BuffEvidence.Object(fields);
    private static EvidenceArray Strings(IEnumerable<string> values) => new(values.Select(value => (EvidenceValue)T(value)).ToArray());
    private static Dictionary<string, EvidenceValue> Copy(EvidenceObject value) => new(value.Fields, StringComparer.Ordinal);
    private static EvidenceObject Unresolved(string error, string? key = null) => key is null
        ? Obj(("type", T("unresolved")), ("errors", Strings([error])))
        : Obj(("type", T("unresolved")), ("errors", Strings([error])), ("bb_key", T(key)));

    public (string Zone, string Element)? DamageZone(EvidenceObject effect)
    {
        if (Text(effect.Get("processorType")) != "DamageScaleProcessor") return null;
        var zone = Text(effect.Get("zoneName"));
        if (!zones.ContainsKey(zone)) return null;
        var side = Text(CatalogValues.Or(effect.Get("side"), effect.Get("enableSide"), T("")));
        return (zone, side) switch
        {
            ("ProdCalcZone", "Attacker") => ("prod_dmg_inc", "all"), ("ProdCalcZone", "Defender") => ("prod_vuln_taken", "all"),
            ("NormalCalcZone", "Attacker") => ("dmg_inc", "all"), ("NormalCalcZone", "Defender") => ("vuln_taken", "all"), _ => null,
        };
    }

    public EvidenceObject DamageCondition(string buffId, EvidenceObject effect, EvidenceObject blackboard)
    {
        var group = effect.Get("groupIndex");
        var text = CatalogValues.Text(group);
        if (group is EvidenceBoolean || !SkillIdentityCatalog.IsDigitText(text)) return Unresolved("missing_condition_group_index");
        var index = TraceFields.OptionalInteger(text);
        if (index is null || index > int.MaxValue || !conditions.For(buffId).TryGetValue((int)index.Value, out var decoded)) return Unresolved("missing_decoded_condition");
        if (CatalogValues.Truth(decoded.Get("errors"))) return Obj(("type", T("unresolved")), ("errors", new EvidenceArray(Items(decoded.Get("errors")).ToArray())));
        if (CatalogValues.Truth(decoded.Get("all_disabled"))) return Obj(("type", T("always")), ("source", T("decoded_disabled_conditions")));
        if (EvidenceJson.PythonEquals(decoded.Get("action_count"), new EvidenceInteger(0))) return Obj(("type", T("always")), ("source", T("decoded_empty_conditions")));
        List<EvidenceValue> result = [];
        foreach (var raw in Items(decoded.Get("conditions")).Cast<EvidenceObject>())
        {
            var condition = Copy((EvidenceObject)BuffEvidence.Clone(raw));
            if (Is(raw.Get("type"), "target_hp_compare", "target_has_buff") && Is(effect.Get("enableSide"), "Attacker", "Defender"))
                condition["subject_side"] = T(Is(effect.Get("enableSide"), "Attacker") ? "defender" : "attacker");
            if (Is(raw.Get("type"), "target_hp_compare"))
            {
                var config = (EvidenceObject)condition["value_config"];
                condition.Remove("value_config");
                var key = Text(config.Get("blackboardKey"));
                var threshold = BuffEvidence.OptionalFloat(CatalogValues.Truth(config.Get("useBlackboardKey")) ? blackboard.Get(key) : config.Get("value"));
                if (threshold is null or < 0 || CatalogValues.Truth(raw.Get("is_ratio")) && threshold > 1) return Unresolved("missing_or_invalid_hp_threshold", key);
                condition["threshold"] = new EvidenceReal(threshold.Value);
                if (CatalogValues.Truth(config.Get("useBlackboardKey"))) condition["threshold_key"] = T(key);
            }
            result.Add(new EvidenceObject(condition));
        }
        return result.Count switch
        {
            0 => Unresolved("empty_decoded_condition"), 1 => (EvidenceObject)result[0],
            _ => Obj(("type", T("all")), ("source", T("decoded_conditions")), ("conditions", new EvidenceArray(result))),
        };
    }

    public RegistryEffectsResult Collect(EvidenceObject source)
    {
        var record = Copy(source);
        record.Remove("rdps_unresolved_semantic_condition");
        record.Remove("rdps_unapproved_typed_branches");
        List<EvidenceObject> effects = [];
        RegistryEffectsResult Error(string error, bool clear = false)
        {
            record["rdps_unresolved_semantic_condition"] = Strings([error]);
            return new(new(record), clear ? [] : effects);
        }
        var buffId = Text(CatalogValues.Or(source.Get("event_key"), T("unknown_buff")));
        if (!roots.TryGetValue(buffId, out var root)) return Error("missing_current_buff_root");
        var blackboard = source.Get("bb_values") as EvidenceObject ?? Obj();
        if (root.Get("damageModifier") is not EvidenceArray modifiers) return Error("unspecified_damage_modifiers");
        List<EvidenceObject> declared = [];
        for (var index = 0; index < modifiers.Items.Count; index++)
        {
            if (modifiers.Items[index] is not EvidenceObject modifier || modifier.Get("damageProcessors") is not EvidenceArray processors)
                return Error("unspecified_damage_processors");
            if (!Is(modifier.Get("enableSide"), "Attacker", "Defender")) return Error("unsupported_modifier_entry_side");
            foreach (var value in processors.Items)
            {
                if (value is not EvidenceObject processor) return Error("unsupported_damage_processor_or_side");
                if (Is(processor.Get("$type"), "Beyond.Gameplay.Core.DamageScaleProcessor"))
                {
                    if (!Is(processor.Get("side"), "Attacker", "Defender")) return Error("unsupported_damage_processor_or_side");
                    var fields = Copy(processor);
                    fields["groupIndex"] = new EvidenceInteger(index);
                    fields["processorType"] = T("DamageScaleProcessor");
                    fields["enableSide"] = modifier.Get("enableSide");
                    declared.Add(new(fields));
                }
                else if (Is(processor.Get("$type"), "Beyond.Gameplay.Core.InstantModifyAttribute")
                    && processor.Get("modifier") is EvidenceObject typed && Is(typed.Get("attributeType"), "FireResistance")
                    && Is(typed.Get("formulaItem"), "BaseAddition") && Is(typed.Get("modifyAttributeType"), "Specific") && Is(processor.Get("modifyTargetSide"), "Defender"))
                    declared.Add(Obj(("groupIndex", new EvidenceInteger(index)), ("processorType", T("InstantModifyAttribute")), ("side", T("Defender")),
                        ("enableSide", modifier.Get("enableSide")), ("addition", CatalogValues.Or(typed.Get("param"), Obj())), ("attributeType", T("FireResistance"))));
                else return Error("unsupported_damage_processor_or_side");
            }
        }
        var candidate = approval.Match(new EvidenceObject(record), requireGuard: false);
        var approved = candidate is null ? [] : Items(candidate.Get("effects")).OfType<EvidenceObject>().ToArray();
        foreach (var effect in declared)
        {
            var decoded = conditions.For(buffId).GetValueOrDefault((int)((EvidenceInteger)effect.Get("groupIndex")).Value) ?? Obj();
            var addition = effect.Get("addition") as EvidenceObject ?? Obj();
            var keyValue = addition.Get("useBlackboardKey") is EvidenceBoolean { Value: true } ? addition.Get("blackboardKey") : EvidenceNull.Value;
            var scopes = approved.Where(spec => CatalogValues.Truth(keyValue) && Items(spec.Get("bb_keys")).Append(spec.Get("bb_key")).Any(key => EvidenceJson.PythonEquals(key, keyValue)))
                .Select(spec => spec.Fields.TryGetValue("element", out var element) ? element : T("all")).ToArray();
            if (scopes.Length > 0 && scopes.All(scope => Is(scope, "physical", "spell", "fire", "pulse", "cryst", "natural", "real", "lifedrain", "ether"))
                && !Items(decoded.Get("errors")).Any(error => Is(error, "unresolved_source_guard")))
            {
                var allowed = scopes.SelectMany(scope => Is(scope, "spell") ? new[] { "fire", "pulse", "cryst", "natural" } : new[] { Text(scope) }).ToHashSet(StringComparer.Ordinal);
                var restrictions = Items(decoded.Get("conditions")).OfType<EvidenceObject>()
                    .Where(condition => Is(condition.Get("type"), "damage_type_in") && CatalogValues.Truth(condition.Get("elements")))
                    .Select(condition => Items(condition.Get("elements")).Select(CatalogValues.Text).ToHashSet(StringComparer.Ordinal)).ToArray();
                if (restrictions.Any(elements => !allowed.Overlaps(elements)))
                {
                    var ignored = Items(record.GetValueOrDefault("rdps_unapproved_typed_branches") ?? EvidenceNull.Value).ToList();
                    ignored.Add(Obj(("group_index", effect.Get("groupIndex")), ("bb_key", keyValue), ("reason", T("typed_damage_types_disjoint_from_whitelist")),
                        ("whitelist_elements", Strings(allowed.Order(PythonDisplay.CodePointComparer))),
                        ("typed_damage_types", Strings(restrictions.SelectMany(row => row).Distinct(StringComparer.Ordinal).Order(PythonDisplay.CodePointComparer))),
                        ("unsupported_conditions", new EvidenceArray(Items(decoded.Get("errors")).ToArray()))));
                    record["rdps_unapproved_typed_branches"] = new EvidenceArray(ignored);
                    continue;
                }
            }
            var condition = DamageCondition(buffId, effect, blackboard);
            if (Is(condition.Get("type"), "unresolved"))
            {
                record["rdps_unresolved_semantic_condition"] = CatalogValues.Or(condition.Get("errors"), Strings(["unresolved_condition"]));
                continue;
            }
            var instant = Is(effect.Get("processorType"), "InstantModifyAttribute");
            var zoneElement = instant ? ("res", "fire") : DamageZone(effect);
            if (zoneElement is null) { Error("unsupported_damage_zone"); continue; }
            var (zone, element) = zoneElement.Value;
            var key = Text(addition.Get("blackboardKey"));
            var rate = ReadRate(addition, blackboard, key);
            if (instant && rate is not null) rate = -rate;
            if (rate is null or < 0) { Error("missing_or_invalid_effect_rate"); continue; }
            var elements = EffectConditions.DamageTypeElements(condition);
            if (element == "all" && elements.Count == 1) element = elements.First();
            var row = Copy(Obj(("zone", T(zone)), ("element", T(element)), ("rate", new EvidenceReal(rate.Value)), ("condition", condition),
                ("semantic_source", T("typed_current_damageModifier")), ("recipient_side", T(Text(effect.Get("enableSide")).ToLowerInvariant()))));
            if (zone.StartsWith("prod_", StringComparison.Ordinal)) row["multiplicative"] = new EvidenceBoolean(true);
            if (key.Length > 0) row["bb_key"] = T(key);
            effects.Add(new(row));
        }
        if (root.Get("attributeModifier") is EvidenceObject attributes)
            foreach (var value in Items(attributes.Get("attributeModifiers")))
            {
                if (value is not EvidenceObject modifier) continue;
                var name = Text(modifier.Get("attributeType"));
                var known = Attributes.TryGetValue(name, out var attribute);
                if (!known && !Vulnerabilities.ContainsKey(name)) continue;
                var formula = known ? attribute.Formula : "BaseAddition";
                if (attributes.Get("isConvertedAttribute") is not EvidenceBoolean converted || !Is(modifier.Get("formulaItem"), formula) || !Is(modifier.Get("modifyAttributeType"), "Specific"))
                    return Error("unsupported_conditional_attribute_formula", clear: true);
                var parameter = CatalogValues.Or(modifier.Get("param"), Obj()) as EvidenceObject ?? throw new InvalidCastException("Invalid attribute parameter");
                var key = Text(parameter.Get("blackboardKey"));
                var rate = ReadRate(parameter, blackboard, key);
                if (rate is null or < 0) return Error("missing_or_invalid_attribute_rate", clear: true);
                var row = Copy(Obj(("zone", T(known ? attribute.Zone : "fragile")), ("element", T(known ? attribute.Element : Vulnerabilities[name])),
                    ("rate", new EvidenceReal(rate.Value)), ("attr_type", known ? new EvidenceInteger(attribute.Type) : EvidenceNull.Value),
                    ("bb_key", parameter.Get("useBlackboardKey") is EvidenceBoolean { Value: true } ? T(key) : T("")),
                    ("semantic_source", T("typed_current_attributeModifier"))));
                if (known && AttributeMasks.TryGetValue(attribute.Type, out var mask)) row["condition"] = Obj(("type", T("damage_decorate_mask")),
                    ("check", T("HasAny")), ("mask", new EvidenceInteger(mask)), ("source", T("DamagePackData.GetAttackerDamageScaleIncreaseFromSkillType")));
                if (converted.Value) row["converted_attribute"] = new EvidenceBoolean(true);
                effects.Add(new(row));
            }
        return new(new(record), effects);
    }

    private static double? ReadRate(EvidenceObject parameter, EvidenceObject blackboard, string key) => parameter.Get("useBlackboardKey") switch
    {
        EvidenceBoolean { Value: true } when key.Length > 0 => BuffEvidence.OptionalFloat(blackboard.Get(key)),
        EvidenceBoolean { Value: false } => BuffEvidence.OptionalFloat(parameter.Get("value")), _ => null,
    };
}
