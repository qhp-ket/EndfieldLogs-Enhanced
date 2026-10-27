"""Verified effect registry matching, runtime rates and validation."""
from __future__ import annotations

from math import isfinite
from parser_core.catalog import buff_templates as _buff_catalog
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.approval import _rdps_registry_bb_keys_allowed
from parser_core.effects.approval import _rdps_registry_effect_bb_keys
from parser_core.effects.approval import _rdps_registry_matching_effect_entry
from parser_core.effects.approval import _record_bb_key_set
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.ingestion.fields import _coerce_optional_float
from parser_core.ingestion.fields import _positive_int
import copy
from typing import Any


_RDPS_ALLOCATABLE_ZONES = {"atk", "dmg_inc", "amp", "fragile", "vuln_taken", "res", "combo", "arts_strength",
                           "prod_dmg_inc", "prod_vuln_taken"}


_RDPS_REGISTRY_CONTROL_BB_KEYS = {
    "",
    "=",
    "duration",
    "duration2",
    "duration_spellvulnerable",
    "life_time",
    "lifetime",
    "max_stack",
    "max_stack_count",
    "maxstack",
    "stack_limit",
    "stacklimit",
    "cntmax",
    "count",
    "max_count",
}


def _rdps_registry_known_non_rdps_entry(record: dict[str, Any]) -> dict[str, Any] | None:
    from parser_core.realtime.incremental import ACTIVE_ALLOCATION_CACHE
    cache = ACTIVE_ALLOCATION_CACHE.get()
    if cache is None:
        return _classify_non_rdps_entry(record)
    roots = _load_current_buff_roots()
    key = (id(roots), *(record.get(field) for field in (
        'event_key', 'raw_event_key', 'target_character_key', 'target_enemy_key')))
    if key not in cache.static_classifications:
        cache.static_classifications[key] = _classify_non_rdps_entry(record)
    return copy.deepcopy(cache.static_classifications[key])


def _classify_non_rdps_entry(record):
    candidates = [
        _normalize_buff_id(record.get("event_key")),
        _normalize_buff_id(record.get("raw_event_key")),
    ]
    # A registry label is not a structural proof. Check the current typed root.
    roots = _load_current_buff_roots()
    type_index = _buff_catalog._BUFF_ACTION_TYPES_INDEX
    for key in candidates:
        root = roots.get(key)
        if not isinstance(root, dict):
            continue
        attribute_block = root.get("attributeModifier")
        attribute_rows = (attribute_block.get("attributeModifiers")
                          if isinstance(attribute_block, dict) else None)
        action_types = type_index[1].get(key) if type_index is not None and type_index[0] is roots else None
        if action_types is None:
            action_types = set()
            pending = [root]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    type_name = str(value.get("$type") or "")
                    if type_name:
                        action_types.add(type_name.replace("+", "."))
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
        unsafe_action_tokens = (
            "DamageScaleProcessor", "InstantModifyAttribute",
            "ModifyDynamicBlackboard", "DamageActionData",
        )
        safe_attribute_types = {
            "MoveSpeedScalar", "InAirMoveSpeedScalar", "TurnRateScalar",
            "NormalAttackRange", "PoiseRecTime", "PoiseRecTimeScalar",
            "ComboSkillCooldownScalar", "ComboSkillCooldownFinalAddition",
            "ComboSkillCooldownRecoveryScalar", "NormalSkillCooldownAddition",
            "SkillCooldownScalar", "AtbCostAddition", "MaxUltimateSp",
            "UltimateSpGainScalar", "MaxHp", "HealTakenIncrease",
            "HealOutputIncrease", "HpRecoveryPerSecByMaxHpRatio",
            "SlowActionSpeedScalar", "KeywordSpeedUpScalar",
            "KnockDownTimeAddition",
        }
        attribute_types_safe = (
            isinstance(attribute_rows, list)
            and all(isinstance(item, dict) and item.get("attributeType") in safe_attribute_types
                    for item in attribute_rows)
        )
        damage_modifiers_empty = (
            isinstance(root.get("damageModifier"), list)
            and all(isinstance(item, dict) and not item.get("damageProcessors")
                    for item in root.get("damageModifier") or [])
        )
        defensive_attribute_names = {
            "PhysicalDamageTakenScalar", "FireDamageTakenScalar",
            "PulseDamageTakenScalar", "CrystDamageTakenScalar",
            "EtherDamageTakenScalar", "NaturalDamageTakenScalar",
            "HealTakenIncrease",
        }
        defensive_attributes_only = (
            isinstance(attribute_rows, list)
            and bool(attribute_rows)
            and all(
                isinstance(item, dict)
                and item.get("attributeType") in defensive_attribute_names
                and item.get("modifyAttributeType") == "Specific"
                for item in attribute_rows
            )
        )
        defensive_damage_only = (
            isinstance(root.get("damageModifier"), list)
            and bool(root.get("damageModifier"))
            and all(
                isinstance(item, dict)
                and item.get("enableSide") == "Defender"
                and all(
                    isinstance(proc, dict)
                    and str(proc.get("$type") or "").endswith("DamageScaleProcessor")
                    and proc.get("side") == "Defender"
                    and proc.get("zoneName") == "ProdCalcZone"
                    for proc in item.get("damageProcessors") or []
                )
                for item in root.get("damageModifier") or []
            )
        )
        if (str(record.get("target_character_key") or "").startswith("chr_")
                and not record.get("target_enemy_key")
                and not any(any(token in item for token in (
                    "InstantModifyAttribute", "ModifyDynamicBlackboard", "DamageActionData"))
                    for item in action_types)
                and not root.get("globalModifier") and not root.get("healModifier")
                and ((defensive_attributes_only and damage_modifiers_empty)
                     or (defensive_attributes_only and defensive_damage_only))):
            return {
                "kind": "typed_defensive_only_effect",
                "proof_kind": "typed_root_structural",
                "reason": "current typed root only modifies incoming damage/healing on an identified player",
                "suppress_zone_effects": True,
            }
        non_allocating_types = {
            "Beyond.Blackboard.AssignPair", "Beyond.Blackboard.BlackboardDouble",
            "Beyond.Blackboard.BlackboardInt", "Beyond.Blackboard.DataPair",
            "Beyond.Gameplay.AttributeModifierData", "Beyond.Gameplay.Core.AbilityActionMap",
            "Beyond.Gameplay.Core.AttackClickListenerAction.Data",
            "Beyond.Gameplay.Core.BuffActionMap", "Beyond.Gameplay.Core.BuffData",
            "Beyond.Gameplay.Core.BuffIconConfig", "Beyond.Gameplay.Core.BuffIconDurationSourceSetting",
            "Beyond.Gameplay.Core.BuffStackingSettings", "Beyond.Gameplay.Core.CompareFloat.Data",
            "Beyond.Gameplay.Core.Conditions.CheckEntityNum.Data",
            "Beyond.Gameplay.Core.Conditions.CheckSkillType.Data",
            "Beyond.Gameplay.Core.CreateBuffAction.Data", "Beyond.Gameplay.Core.CreateBuffActionInput",
            "Beyond.Gameplay.Core.DirectionSettings", "Beyond.Gameplay.Core.FindTargetAction.FindTargetActionData",
            "Beyond.Gameplay.Core.GameplayTagQuery", "Beyond.Gameplay.Core.IfElseAction.IfElseActionData",
            "Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data",
            "Beyond.Gameplay.Core.NotifyCharPassiveUIAction.Data",
            "Beyond.Gameplay.Core.PlaySoundAction.PlaySoundActionData",
            "Beyond.Gameplay.Core.ReadSkillSettingData.Data", "Beyond.Gameplay.Core.ReadSkillSettingData.ReadData",
            "Beyond.Gameplay.Core.Selector.DistanceValidator.Data",
            "Beyond.Gameplay.Core.Selector.OwnerSpawnedEntityFinder.Data",
            "Beyond.Gameplay.Core.Selector.SelectorData", "Beyond.Gameplay.Core.Selector.TagValidator.Data",
            "Beyond.Gameplay.Core.SequenceActionData", "Beyond.Gameplay.Core.SimpleCalcBBAction.Data",
            "Beyond.Gameplay.Core.TargetSettings", "Beyond.Gameplay.Core.TriggerLiinoUIEvent.Data",
        }
        no_allocatable_payload = (
            root.get("$type") == "Beyond.Gameplay.Core.BuffData"
            and isinstance(attribute_rows, list) and not attribute_rows
            and isinstance(root.get("damageModifier"), list) and not root.get("damageModifier")
            and not root.get("globalModifier") and not root.get("healModifier")
            and not root.get("poiseModifier") and not root.get("shieldConfigs")
            and action_types and action_types <= non_allocating_types
        )
        if no_allocatable_payload:
            return {
                "kind": "typed_root_no_allocatable_effect",
                "proof_kind": "typed_root_structural",
                "reason": "current typed root has no attribute, damage, global, heal, poise, or shield effect",
                "suppress_zone_effects": True,
            }
        if (isinstance(attribute_rows, list)
                and not any(any(token in item for token in unsafe_action_tokens) for item in action_types)
                and (not attribute_rows or attribute_types_safe)
                and damage_modifiers_empty
                and not root.get("globalModifier")
                and not root.get("healModifier")):
            return {
                "kind": "typed_root_no_direct_damage_execution",
                "proof_kind": "typed_root_structural",
                "reason": "version-bound BuffData root has no direct damage processor or modifier",
                "suppress_zone_effects": True,
            }
    return None


def _rdps_registry_suppresses_zone_effects(record: dict[str, Any]) -> bool:
    entry = _rdps_registry_known_non_rdps_entry(record)
    return bool(entry and entry.get("suppress_zone_effects"))


def _rdps_registry_verified_effect_entry(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> dict[str, Any] | None:
    return _rdps_registry_matching_effect_entry(record, require_guard=True, root_lookup_cache=root_lookup_cache)


def _rdps_registry_stack_limit(record: dict[str, Any]) -> int | None:
    entry = _rdps_registry_verified_effect_entry(record)
    if not isinstance(entry, dict):
        return None
    return _positive_int(entry.get("stack_limit"))


def _rdps_registry_candidate_effect_entry(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> dict[str, Any] | None:
    return _rdps_registry_matching_effect_entry(record, require_guard=False, root_lookup_cache=root_lookup_cache)


def _rdps_registry_ignored_bb_keys(entry: dict[str, Any]) -> set[str]:
    ignored = set(_RDPS_REGISTRY_CONTROL_BB_KEYS)
    ignored.update(_rdps_registry_effect_bb_keys(entry))
    ignored.update(str(key) for key in entry.get("ignored_bb_keys") or [] if str(key))
    ignored.update(str(key) for key in entry.get("self_bb_keys") or [] if str(key))
    ignored.update(str(key) for key in entry.get("allowed_bb_keys") or [] if str(key) != "*")
    return ignored


def _rdps_registry_unrecognized_effect_bb_keys(entry: dict[str, Any], record: dict[str, Any]) -> list[str]:
    ignored = _rdps_registry_ignored_bb_keys(entry)
    keys: set[str] = set(_record_bb_key_set(record))
    keys.update(str(key) for key in (record.get("bb_values") or {}).keys() if str(key))
    keys.update(str(mod.get("bb_key") or "") for mod in record.get("attr_mods") or [] if str(mod.get("bb_key") or ""))
    return sorted(
        key
        for key in keys
        if key not in ignored
    )


def _rdps_registry_effect_runtime_rate(
    spec: dict[str, Any],
    record: dict[str, Any],
) -> tuple[float | None, str | None]:
    bb_values = record.get("bb_values") or {}
    keys = list(dict.fromkeys([str(key) for key in spec.get("bb_keys") or [] if str(key)]))
    primary = str(spec.get("bb_key") or "")
    if primary and primary not in keys:
        keys.insert(0, primary)
    present = [(key, _coerce_optional_float(bb_values[key])) for key in keys if key in bb_values]
    if present:
        if any(value is None or value < 0 for _, value in present):
            record["rdps_invalid_runtime_rate"] = True
            return None, None
        if len({value for _, value in present}) != 1:
            record["rdps_conflicting_runtime_rate"] = True
            return None, None
        return present[0][1], present[0][0]
    formula = str(spec.get("formula") or "")
    if formula == "atk_add_plus_mult_consume_half_for_other_targets":
        add = _coerce_optional_float(bb_values.get(str(spec.get("add_bb_key") or "atk_up_add")))
        mult = _coerce_optional_float(bb_values.get(str(spec.get("mult_bb_key") or "atk_up_mult")))
        consumed = _coerce_optional_float(bb_values.get(str(spec.get("consume_bb_key") or "consume_layer")))
        if add is None or mult is None or consumed is None:
            return None, None
        rate = add + mult * consumed
        source = str(record.get("source_character_key") or "")
        target = str(record.get("target_character_key") or "")
        if target and source and target != source:
            factor = _coerce_optional_float(spec.get("other_target_multiplier", 0.5))
            if factor is None:
                return None, None
            rate *= factor
        return (rate, primary or str(spec.get("add_bb_key") or "atk_up_add")) if isfinite(rate) and rate >= 0 else (None, None)
    if str(spec.get("value_source") or "").lower() in {"constant", "static_literal"}:
        rate = _coerce_optional_float(spec.get("rate"))
        return (rate, primary or None) if rate is not None and rate >= 0 else (None, None)
    return None, None


def _rdps_registry_zone_effects(record: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    if entry.get("dynamic"):
        return []
    effects: list[dict[str, Any]] = []
    for spec in entry.get("effects") or []:
        if not isinstance(spec, dict):
            continue
        zone = str(spec.get("zone") or "")
        if zone not in _RDPS_ALLOCATABLE_ZONES and zone != "crit":
            continue
        rate, used_bb_key = _rdps_registry_effect_runtime_rate(spec, record)
        if rate is None:
            continue
        effect = {
            "zone": zone,
            "element": _normalize_effect_element(str(spec.get("element") or "all")),
            "rate": rate,
        }
        if used_bb_key:
            effect["_registry_bb_key"] = used_bb_key
            effect['_registry_bb_keys'] = sorted({used_bb_key, str(spec.get('bb_key') or ''),
                                                  *(str(key) for key in spec.get('bb_keys') or [])} - {''})
            if spec.get("expose_bb_key"):
                effect["bb_key"] = used_bb_key
        if "condition" in spec:
            effect["condition"] = copy.deepcopy(spec["condition"])
        effects.append(effect)
    return effects


def _rdps_registry_validation_error(entry: dict[str, Any], record: dict[str, Any]) -> dict[str, Any] | None:
    record.pop("rdps_invalid_runtime_rate", None)
    record.pop("rdps_conflicting_runtime_rate", None)
    if record.get("rdps_unresolved_semantic_condition"):
        return {"reason": "unresolved_semantic_condition", "condition_errors": record["rdps_unresolved_semantic_condition"]}
    if record.get("rdps_unresolved_dynamic_effect"):
        return {"reason": "unresolved_dynamic_effect_parameters"}
    if not _rdps_registry_bb_keys_allowed(entry, record):
        return {"reason": "registry allowed_bb_keys check failed"}
    unknown_bb_keys = _rdps_registry_unrecognized_effect_bb_keys(entry, record)
    if unknown_bb_keys:
        return {
            "reason": "verified rDPS buff carried BB keys not declared by rdps_semantics_registry",
            "unknown_bb_keys": unknown_bb_keys,
        }
    if entry.get("dynamic"):
        return None
    resolved = _rdps_registry_zone_effects(record, entry)
    if record.get("rdps_conflicting_runtime_rate"):
        return {"reason": "conflicting_runtime_rate"}
    if record.get("rdps_invalid_runtime_rate"):
        return {"reason": "invalid_runtime_rate"}
    if entry.get("effects") and len(resolved) != len(entry["effects"]):
        return {
            "reason": "verified rDPS buff did not expose required runtime BB value declared by rdps_semantics_registry",
            "required_bb_keys": sorted(_rdps_registry_effect_bb_keys(entry)),
        }
    return None
