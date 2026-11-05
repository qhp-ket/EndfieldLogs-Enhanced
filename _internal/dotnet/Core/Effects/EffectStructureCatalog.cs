using System.Collections.Concurrent;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

/// <summary>Typed-root proof of effects that cannot participate in outgoing damage allocation.</summary>
public sealed class EffectStructureCatalog(IReadOnlyDictionary<string, EvidenceObject> roots)
{
    private readonly ConcurrentDictionary<string, IReadOnlySet<string>> actionTypes = new(StringComparer.Ordinal);
    private static readonly HashSet<string> SafeAttributes = new(["MoveSpeedScalar", "InAirMoveSpeedScalar", "TurnRateScalar", "NormalAttackRange", "PoiseRecTime", "PoiseRecTimeScalar", "ComboSkillCooldownScalar", "ComboSkillCooldownFinalAddition", "ComboSkillCooldownRecoveryScalar", "NormalSkillCooldownAddition", "SkillCooldownScalar", "AtbCostAddition", "MaxUltimateSp", "UltimateSpGainScalar", "MaxHp", "HealTakenIncrease", "HealOutputIncrease", "HpRecoveryPerSecByMaxHpRatio", "SlowActionSpeedScalar", "KeywordSpeedUpScalar", "KnockDownTimeAddition"], StringComparer.Ordinal);
    private static readonly HashSet<string> DefensiveAttributes = new(["PhysicalDamageTakenScalar", "FireDamageTakenScalar", "PulseDamageTakenScalar", "CrystDamageTakenScalar", "EtherDamageTakenScalar", "NaturalDamageTakenScalar", "HealTakenIncrease"], StringComparer.Ordinal);
    private static readonly HashSet<string> NonAllocatingTypes = new([
        "Beyond.Blackboard.AssignPair", "Beyond.Blackboard.BlackboardDouble", "Beyond.Blackboard.BlackboardInt", "Beyond.Blackboard.DataPair",
        "Beyond.Gameplay.AttributeModifierData", "Beyond.Gameplay.Core.AbilityActionMap", "Beyond.Gameplay.Core.AttackClickListenerAction.Data",
        "Beyond.Gameplay.Core.BuffActionMap", "Beyond.Gameplay.Core.BuffData", "Beyond.Gameplay.Core.BuffIconConfig", "Beyond.Gameplay.Core.BuffIconDurationSourceSetting",
        "Beyond.Gameplay.Core.BuffStackingSettings", "Beyond.Gameplay.Core.CompareFloat.Data", "Beyond.Gameplay.Core.Conditions.CheckEntityNum.Data",
        "Beyond.Gameplay.Core.Conditions.CheckSkillType.Data", "Beyond.Gameplay.Core.CreateBuffAction.Data", "Beyond.Gameplay.Core.CreateBuffActionInput",
        "Beyond.Gameplay.Core.DirectionSettings", "Beyond.Gameplay.Core.FindTargetAction.FindTargetActionData", "Beyond.Gameplay.Core.GameplayTagQuery",
        "Beyond.Gameplay.Core.IfElseAction.IfElseActionData", "Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data", "Beyond.Gameplay.Core.NotifyCharPassiveUIAction.Data",
        "Beyond.Gameplay.Core.PlaySoundAction.PlaySoundActionData", "Beyond.Gameplay.Core.ReadSkillSettingData.Data", "Beyond.Gameplay.Core.ReadSkillSettingData.ReadData",
        "Beyond.Gameplay.Core.Selector.DistanceValidator.Data", "Beyond.Gameplay.Core.Selector.OwnerSpawnedEntityFinder.Data", "Beyond.Gameplay.Core.Selector.SelectorData",
        "Beyond.Gameplay.Core.Selector.TagValidator.Data", "Beyond.Gameplay.Core.SequenceActionData", "Beyond.Gameplay.Core.SimpleCalcBBAction.Data",
        "Beyond.Gameplay.Core.TargetSettings", "Beyond.Gameplay.Core.TriggerLiinoUIEvent.Data"], StringComparer.Ordinal);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static bool Is(EvidenceValue value, string text) => value is EvidenceText found && found.Value == text;
    private static bool Any(EvidenceObject root, params string[] keys) => keys.Any(key => CatalogValues.Truth(root.Get(key)));
    private static bool Contains(IReadOnlySet<string> types, params string[] tokens) => types.Any(type => tokens.Any(token => type.Contains(token, StringComparison.Ordinal)));
    private static EvidenceObject Proof(string kind, string reason) => new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
    {
        ["kind"] = new EvidenceText(kind), ["reason"] = new EvidenceText(reason), ["proof_kind"] = new EvidenceText("typed_root_structural"),
        ["suppress_zone_effects"] = new EvidenceBoolean(true),
    });

    private static IReadOnlySet<string> Types(EvidenceObject root)
    {
        HashSet<string> types = new(StringComparer.Ordinal);
        Stack<EvidenceValue> pending = new([root]);
        while (pending.TryPop(out var node))
        {
            if (node is EvidenceObject obj)
            {
                var type = Text(obj.Get("$type"));
                if (type.Length > 0) types.Add(type.Replace('+', '.'));
                foreach (var value in obj.Fields.Values) pending.Push(value);
            }
            else if (node is EvidenceArray array) foreach (var value in array.Items) pending.Push(value);
        }
        return types;
    }

    public EvidenceObject? Classify(EvidenceObject record)
    {
        foreach (var field in new[] { "event_key", "raw_event_key" })
        {
            var key = Text(CatalogValues.Or(record.Get(field), new EvidenceText("unknown_buff")));
            if (!roots.TryGetValue(key, out var root)) continue;
            var types = actionTypes.GetOrAdd(key, _ => Types(root));
            var attributes = (root.Get("attributeModifier") as EvidenceObject)?.Get("attributeModifiers") as EvidenceArray;
            var damage = root.Get("damageModifier") as EvidenceArray;
            var emptyDamage = damage is not null && damage.Items.All(value => value is EvidenceObject obj && !CatalogValues.Truth(obj.Get("damageProcessors")));
            var defensiveAttributes = attributes is { Items.Count: > 0 } && attributes.Items.All(value => value is EvidenceObject obj
                && DefensiveAttributes.Contains(Text(obj.Get("attributeType"))) && Is(obj.Get("modifyAttributeType"), "Specific"));
            var defensiveDamage = damage is { Items.Count: > 0 } && damage.Items.All(value => value is EvidenceObject obj
                && Is(obj.Get("enableSide"), "Defender") && CatalogValues.Iterable(CatalogValues.Or(obj.Get("damageProcessors"), new EvidenceArray([])))
                    .All(value => value is EvidenceObject proc && Text(proc.Get("$type")).EndsWith("DamageScaleProcessor", StringComparison.Ordinal)
                        && Is(proc.Get("side"), "Defender") && Is(proc.Get("zoneName"), "ProdCalcZone")));
            if (Text(record.Get("target_character_key")).StartsWith("chr_", StringComparison.Ordinal) && !CatalogValues.Truth(record.Get("target_enemy_key"))
                && !Contains(types, "InstantModifyAttribute", "ModifyDynamicBlackboard", "DamageActionData") && !Any(root, "globalModifier", "healModifier")
                && defensiveAttributes && (emptyDamage || defensiveDamage))
                return Proof("typed_defensive_only_effect", "current typed root only modifies incoming damage/healing on an identified player");
            if (Is(root.Get("$type"), "Beyond.Gameplay.Core.BuffData") && attributes is { Items.Count: 0 } && damage is { Items.Count: 0 }
                && !Any(root, "globalModifier", "healModifier", "poiseModifier", "shieldConfigs") && types.Count > 0 && types.IsSubsetOf(NonAllocatingTypes))
                return Proof("typed_root_no_allocatable_effect", "current typed root has no attribute, damage, global, heal, poise, or shield effect");
            if (attributes is not null && !Contains(types, "DamageScaleProcessor", "InstantModifyAttribute", "ModifyDynamicBlackboard", "DamageActionData")
                && attributes.Items.All(value => value is EvidenceObject obj && SafeAttributes.Contains(Text(obj.Get("attributeType"))))
                && emptyDamage && !Any(root, "globalModifier", "healModifier"))
                return Proof("typed_root_no_direct_damage_execution", "version-bound BuffData root has no direct damage processor or modifier");
        }
        return null;
    }
}
