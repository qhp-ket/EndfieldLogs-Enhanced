using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Validate the current typed forwarding actions before using packet combo evidence.</summary>
internal static class ComboResourceContract
{
    public const string Trigger = "buff_common_affixes_combo_trigger";
    public const string Imbue = "buff_common_affixes_skillimbue";
    public const string Modifier = "buff_common_affixes_skillimbue_atk";
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? Empty;
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.Select(Obj).ToArray() : [];
    private static bool Is(EvidenceObject value, string key, string expected) => value.Get(key) is EvidenceText text && text.Value == expected;
    private static bool Enabled(EvidenceObject value) => value.Get("isEnable") is EvidenceBoolean { Value: true };
    private static bool Binding(EvidenceValue value, string key) => Obj(value).Get("useBlackboardKey") is EvidenceBoolean { Value: true }
        && Is(Obj(value), "blackboardKey", key);
    private static bool Mask(EvidenceObject value, int mask) => Is(value, "$type", "Beyond.Gameplay.Core.Conditions.CheckDamageDecorateMask.Data")
        && Is(value, "checkType", "HasAny") && EvidenceJson.PythonEquals(value.Get("mask"), new EvidenceInteger(mask));

    public static double? Resolve(IReadOnlyDictionary<string, EvidenceObject> roots)
    {
        if (!roots.ContainsKey(Trigger) || !roots.ContainsKey(Imbue) || !roots.ContainsKey(Modifier)) return null;
        BuffActionIndices indices = new();
        foreach (var (parent, action, child) in new[] { (Trigger, 4, Imbue), (Imbue, 0, Modifier) })
        {
            var creations = indices.For(roots[parent]).Creations.Where(row => row.Definition.Get("serverActionIndex") is EvidenceInteger index && index.Value == action).ToArray();
            if (creations is not [{ Enabled: true }]) return null;
            var definition = creations[0].Definition;
            var created = Rows(definition.Get("buffs"));
            if (created is not [var buff] || buff.Get("readIdFromBlackboard") is not EvidenceBoolean { Value: false }
                || !Is(buff, "buffId", child) || buff.Get("assignBlackboard") is not EvidenceBoolean { Value: true }
                || !Is(definition, "buffSource", "ActionSource") || !Is(Obj(definition.Get("targetSettings")), "targetSource", "Owner")) return null;
            var assignments = Rows(buff.Get("assignItems")).Where(row => Is(row, "targetKey", "imbue_scale")).ToArray();
            if (assignments is not [var assigned] || assigned.Get("useDirectValue") is not EvidenceBoolean { Value: false }
                || !Is(assigned, "inputValueKey", "imbue_scale")) return null;
        }
        var groups = Rows(roots[Modifier].Get("damageModifier"));
        if (groups is not [var group] || !Is(group, "enableSide", "Attacker")) return null;
        var processors = Rows(group.Get("damageProcessors"));
        if (processors is not [var processor] || !Is(processor, "$type", "Beyond.Gameplay.Core.DamageScaleProcessor")
            || !Is(processor, "side", "Attacker") || !Is(processor, "zoneName", "ComboCalcZone")
            || !Binding(processor.Get("addition"), "real_imbue_scale")) return null;
        var conditions = Rows(Obj(group.Get("condition")).Get("actionData"));
        if (conditions is not [var cast, var scope, var branch] || !conditions.All(Enabled)
            || !Is(cast, "$type", "Beyond.Gameplay.Core.Conditions.CheckSkillCastId.Data") || !Mask(scope, 0x300)
            || !Is(branch, "$type", "Beyond.Gameplay.Core.IfElseAction.IfElseActionData")) return null;
        var checks = Rows(Obj(branch.Get("conditionAction")).Get("actionData"));
        var successes = Rows(Obj(branch.Get("succeedActions")).Get("actionData"));
        var failures = Rows(Obj(branch.Get("failActions")).Get("actionData"));
        if (checks is not [var check] || successes is not [var success] || failures is not [var failure]
            || !Enabled(check) || !Enabled(success) || !Enabled(failure) || !Mask(check, 0x100)
            || !Is(success, "$type", "Beyond.Gameplay.Core.SimpleCalcBBAction.Data") || !Is(success, "operation", "Multiply")
            || !Is(success, "key", "real_imbue_scale") || !Binding(success.Get("value1"), "imbue_scale")
            || Obj(success.Get("value2")).Get("useBlackboardKey") is not EvidenceBoolean { Value: false }
            || !Is(failure, "$type", "Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data") || !Is(failure, "operation", "Assign")
            || failure.Get("directValue") is not EvidenceBoolean { Value: true } || !Is(failure, "key", "real_imbue_scale")
            || !Binding(failure.Get("value"), "imbue_scale")) return null;
        var factor = BuffEvidence.OptionalFloat(Obj(success.Get("value2")).Get("value"));
        return factor > 0 ? factor : null;
    }
}
