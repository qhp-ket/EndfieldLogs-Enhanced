using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Decode typed condition declarations without granting effect approval.</summary>
public sealed class ModifierConditionCatalog(IReadOnlyDictionary<string, EvidenceObject> roots)
{
    private const int Capacity = 4096;
    private readonly Dictionary<string, (IReadOnlyDictionary<int, EvidenceObject> Rows, LinkedListNode<string> Node)> cache = new(StringComparer.Ordinal);
    private readonly LinkedList<string> order = new();
    private readonly object gate = new();
    public int CachedCount { get { lock (gate) return cache.Count; } }

    public IReadOnlyDictionary<int, EvidenceObject> For(string buffId)
    {
        lock (gate)
        {
            if (cache.TryGetValue(buffId, out var existing))
            {
                order.Remove(existing.Node);
                order.AddLast(existing.Node);
                return existing.Rows;
            }
            var rows = Decode(roots.GetValueOrDefault(buffId));
            var node = order.AddLast(buffId);
            cache.Add(buffId, (rows, node));
            if (cache.Count > Capacity)
            {
                cache.Remove(order.First!.Value);
                order.RemoveFirst();
            }
            return rows;
        }
    }

    public static string? NormalizeDamageType(EvidenceValue value)
    {
        var text = PythonDisplay.Strip(CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")))).ToLowerInvariant();
        return text switch
        {
            "physical" or "physic" => "physical", "cryst" or "crystal" => "cryst",
            "fire" or "pulse" or "natural" => text, _ => null,
        };
    }

    public static IReadOnlyDictionary<int, EvidenceObject> Decode(EvidenceObject? root)
    {
        Dictionary<int, EvidenceObject> rows = [];
        if (root?.Get("damageModifier") is not EvidenceArray modifiers) return rows;
        for (var index = 0; index < modifiers.Items.Count; index++)
        {
            List<EvidenceValue> conditions = [], errors = [];
            var container = (modifiers.Items[index] as EvidenceObject)?.Get("condition") as EvidenceObject;
            if (container?.Get("actionData") is not EvidenceArray actions)
            {
                rows[index] = Object(("conditions", new EvidenceArray([])), ("errors", new EvidenceArray([Text("missing_condition_actions")])));
                continue;
            }
            if (new[] { "onlyExecuteWhenSourceIsMainChar", "onlyExecuteWhenSourceIsGuard" }.Any(key => container.Get(key) is not EvidenceBoolean { Value: false }))
                errors.Add(Text("unresolved_source_guard"));
            var disabled = 0;
            foreach (var item in actions.Items)
            {
                if (item is not EvidenceObject action || action.Get("isEnable") is not EvidenceBoolean enabled)
                {
                    errors.Add(Text("missing_condition_enabled_state"));
                    continue;
                }
                if (!enabled.Value) { disabled++; continue; }
                var symbol = CatalogValues.Text(CatalogValues.Or(action.Get("$type"), Text(""))).Split(',', 2)[0].Replace('+', '.');
                var kind = symbol switch
                {
                    "Beyond.Gameplay.Core.Conditions.CheckHp.Data" => "CheckHp",
                    "Beyond.Gameplay.Core.Conditions.CheckDamageType.Data" => "CheckDamageType",
                    "Beyond.Gameplay.Core.Conditions.CheckDamageTypeMask.Data" => "CheckDamageTypeMask",
                    "Beyond.Gameplay.Core.Conditions.CheckDamageDecorateMask.Data" => "CheckDamageDecorateMask",
                    "Beyond.Gameplay.Core.CompareFloat.Data" => "CompareFloat",
                    "Beyond.Gameplay.Core.CheckBuffStackNumAdvanced.Data" => "CheckBuffStackNumAdvanced",
                    _ => symbol,
                };
                if (kind is not ("CheckHp" or "CheckDamageType" or "CheckDamageTypeMask" or "CheckDamageDecorateMask" or "CheckBuffStackNumAdvanced" or "CompareFloat"))
                {
                    errors.Add(Text("unsupported_action:" + kind));
                    continue;
                }
                if (kind is "CheckHp" or "CheckBuffStackNumAdvanced")
                {
                    if (action.Get(kind == "CheckHp" ? "hpOwner" : "checkTarget") is not EvidenceObject selector || !Is(selector.Get("targetSource"), "Target"))
                    {
                        errors.Add(Text("unsupported_condition_target"));
                        continue;
                    }
                    var selection = CatalogValues.Or(selector.Get("selectorData"), Object());
                    if (selection is not EvidenceObject selected || CatalogValues.Truth(selected.Get("validatorData")) || CatalogValues.Truth(selected.Get("postProcessorData"))
                        || new[] { "targetGroupKey", "ownerContextKey", "targetContextKey" }.Any(key => CatalogValues.Truth(selector.Get(key))))
                    {
                        errors.Add(Text("unsupported_condition_selector"));
                        continue;
                    }
                }
                var condition = DecodeAction(kind, action, out var error);
                if (condition is not null) conditions.Add(condition);
                if (error is not null) errors.Add(Text(error));
            }
            rows[index] = Object(("conditions", new EvidenceArray(conditions)), ("errors", new EvidenceArray(errors)),
                ("action_count", new EvidenceInteger(actions.Items.Count)), ("all_disabled", new EvidenceBoolean(actions.Items.Count > 0 && disabled == actions.Items.Count)));
        }
        return rows;
    }

    private static EvidenceObject? DecodeAction(string kind, EvidenceObject action, out string? error)
    {
        error = null;
        if (kind == "CompareFloat")
        {
            bool Valid(EvidenceValue raw) => raw is EvidenceObject value && value.Get("useBlackboardKey") is EvidenceBoolean enabled
                && (!enabled.Value || value.Get("blackboardKey") is EvidenceText { Value.Length: > 0 });
            if (!Is(action.Get("compare"), "Equals") || !Valid(action.Get("valueA")) || !Valid(action.Get("valueB"))) error = "unsupported_float_comparison";
            else return Object(("type", Text("value_compare")), ("source", Text(kind)), ("compare", Text("Equals")),
                ("left_config", action.Get("valueA")), ("right_config", action.Get("valueB")));
        }
        else if (kind == "CheckHp")
        {
            var compare = action.Get("compare");
            if (!Is(compare, "LT", "LE", "GT", "GE", "EQ", "NE") || action.Get("isRatio") is not EvidenceBoolean
                || action.Get("value") is not EvidenceObject value || value.Get("useBlackboardKey") is not EvidenceBoolean blackboard
                || blackboard.Value && !CatalogValues.Truth(value.Get("blackboardKey"))) error = "unsupported_hp_comparison";
            else return Object(("type", Text("target_hp_compare")), ("source", Text(kind)), ("compare", compare),
                ("is_ratio", action.Get("isRatio")), ("value_config", new EvidenceObject(value.Fields.ToDictionary(pair => pair.Key, pair => pair.Value))));
        }
        else if (kind == "CheckDamageType")
        {
            if (NormalizeDamageType(action.Get("damageType")) is not { } element) error = "unresolved_damage_type";
            else return Object(("type", Text("damage_type_in")), ("source", Text(kind)), ("elements", new EvidenceArray([Text(element)])));
        }
        else if (kind == "CheckDamageTypeMask")
        {
            var mask = action.Get("damageTypeMask");
            if (mask is EvidenceText text)
            {
                var named = text.Value switch { "Physical" => 1, "Real" => 2, "Fire" => 4, "Pulse" => 8,
                    "Cryst" => 16, "LifeDrain" => 32, "Natural" => 64, "Ether" => 128, _ => 0 };
                mask = new EvidenceInteger(named);
            }
            if (mask is not EvidenceInteger number || number.Value <= 0 || number.Value > 255) error = "unsupported_damage_type_mask";
            else
            {
                string[] elements = ["physical", "real", "fire", "pulse", "cryst", "lifedrain", "natural", "ether"];
                return Object(("type", Text("damage_type_in")), ("source", Text(kind)),
                    ("elements", new EvidenceArray(elements.Select((name, bit) => (name, bit)).Where(row => (number.Value & (1 << row.bit)) != 0)
                        .Select(row => (EvidenceValue)Text(row.name)).ToArray())));
            }
        }
        else if (kind == "CheckDamageDecorateMask")
        {
            if (action.Get("mask") is not EvidenceInteger { Value.Sign: >= 0 } || !Is(action.Get("checkType"), "HasAll", "HasAny"))
                error = "unsupported_damage_decorate_check";
            else return Object(("type", Text("damage_decorate_mask")), ("source", Text(kind)), ("mask", action.Get("mask")), ("check", action.Get("checkType")));
        }
        else
        {
            var settings = action.Get("buffSettings") as EvidenceObject;
            var value = action.Get("value") as EvidenceObject;
            if (settings?.Get("buffIdList") is not EvidenceArray { Items.Count: > 0 } ids || ids.Items.Any(id => id is not EvidenceText { Value.Length: > 0 })
                || !Is(settings.Get("checkType"), "Id") || !Is(action.Get("buffStackNumType"), "BuffCount") || !Is(action.Get("compareType"), "GE")
                || action.Get("limitSkillCastId") is not EvidenceBoolean { Value: false } || value?.Get("useBlackboardKey") is not EvidenceBoolean { Value: false }
                || BuffEvidence.OptionalFloat(value.Get("value")) != 1.0) error = "unsupported_buff_count_comparison";
            else return Object(("type", Text("target_has_buff")), ("source", Text(kind)),
                ("buff_ids", new EvidenceArray(ids.Items.Cast<EvidenceText>().Select(id => id.Value).Distinct(StringComparer.Ordinal)
                    .Order(PythonDisplay.CodePointComparer).Select(id => (EvidenceValue)Text(id)).ToArray())));
        }
        return null;
    }

    private static EvidenceText Text(string value) => new(value);
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => BuffEvidence.Object(fields);
    private static bool Is(EvidenceValue value, params string[] choices) => value is EvidenceText text && choices.Contains(text.Value, StringComparer.Ordinal);
}
