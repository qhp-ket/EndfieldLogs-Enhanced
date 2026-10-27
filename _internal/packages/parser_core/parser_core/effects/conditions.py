"""Observed condition guards and exact damage-type constraints."""
from __future__ import annotations

from parser_core.effects.damage_types import _effect_applies_to_damage_element, _normalize_effect_element
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any

from functools import lru_cache
from parser_core.catalog.buff_templates import _load_current_buff_roots


def _effect_damage_type_condition_elements(effect: dict[str, Any]) -> set[str]:
    condition = effect.get("condition")
    return _condition_damage_type_elements(condition if isinstance(condition, dict) else None)


def _condition_damage_type_elements(condition: dict[str, Any] | None) -> set[str]:
    if not isinstance(condition, dict):
        return set()
    if str(condition.get("type") or "") == "all":
        elements: set[str] = set()
        for child in condition.get("conditions") or []:
            if isinstance(child, dict):
                elements.update(_condition_damage_type_elements(child))
        return elements
    if str(condition.get("type") or "") != "damage_type_in":
        return set()
    return {
        str(element)
        for element in condition.get("elements") or []
        if str(element or "")
    }


def _effect_element_applies_to_hit(
    effect: dict[str, Any],
    damage_element: str | None,
    damage_school: str | None = None,
) -> bool:
    effect_element = _normalize_effect_element(effect.get("element"))
    condition_elements = _effect_damage_type_condition_elements(effect)
    if condition_elements and (effect_element == "all" or effect_element in condition_elements):
        return True
    return _effect_applies_to_damage_element(effect_element, damage_element, damage_school)


def _element_filter_debug_fields(
    effect_element: str,
    damage_element: str | None,
    damage_school: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_effect_element(effect_element)
    reason = "damage_school_filtered" if normalized in {"physical", "spell"} else "damage_element_filtered"
    return {
        "reason": reason,
        "reason_group": "element_mismatch",
        "filter_kind": reason,
        "effect_element": normalized,
        "hit_damage_element": damage_element,
        "hit_damage_school": damage_school,
    }


_PHYSICAL_DAMAGE_ELEMENT_BB_KEYS = {
    "physical_res_down",
    "physical_vulnerable_dmg_increase",
    "phy_resist_down",
}


def _bb_key_damage_type_condition(bb_key: str | None) -> dict[str, Any] | None:
    if str(bb_key or "").lower() not in _PHYSICAL_DAMAGE_ELEMENT_BB_KEYS:
        return None
    return {
        "type": "damage_type_in",
        "source": "blackboard_key",
        "elements": ["physical"],
    }


def _attach_bb_key_damage_type_condition(effect: dict[str, Any], bb_key: str | None) -> None:
    if effect.get("condition"):
        return
    condition = _bb_key_damage_type_condition(bb_key)
    if condition is not None:
        effect["condition"] = condition


def _effect_condition_failure(effect: dict[str, Any], hit: dict[str, Any]) -> dict[str, Any] | None:
    if "condition" not in effect:
        return None
    condition = effect.get("condition")
    missing = {"reason": "condition_state_missing", "reason_group": "condition_unobservable"}
    if not isinstance(condition, dict):
        return {**missing, "detail": "malformed_condition"}
    condition_type = str(condition.get("type") or "")
    missing.update({"condition_type": condition_type, "condition_source": condition.get("source")})
    if condition_type == "always":
        return None
    if condition_type == 'damage_decorate_mask':
        required, check = condition.get('mask'), condition.get('check')
        actual = hit.get('damage_decorate_mask')
        if type(required) is not int or not 0 <= required < 2**64 or check not in {'HasAll', 'HasAny'}:
            return {**missing, 'detail': 'missing_or_invalid_damage_decorate_mask'}
        if actual is None:
            static = hit.get('static_damage_decorate_mask')
            if (hit.get('static_damage_decorate_mask_source') == 'current_typed_skill_or_buff_exact_unit_generation_only'
                    and type(static) is int and 0 <= static < 2**64):
                # The same exact unit proves positive skill categories and
                # physical/spell anomaly bits used by arts-strength eligibility.
                # It does not prove absent bits, crit or other runtime state.
                positive = static & (0x22784 | 0x4001C000 | 0x0FD00038)
                overlap = positive & required
                if (check == 'HasAny' and overlap) or (check == 'HasAll' and overlap == required):
                    return None
            return {**missing, 'detail': 'missing_or_invalid_damage_decorate_mask'}
        if type(actual) is not int or not 0 <= actual < 2**64:
            return {**missing, 'detail': 'missing_or_invalid_damage_decorate_mask'}
        overlap = actual & required
        passed = overlap == required if check == 'HasAll' else overlap != 0
        return None if passed else {'reason': 'damage_decorate_mask_filtered', 'reason_group': 'condition_unsatisfied'}
    if condition_type in {"all", "any"}:
        children = condition.get("conditions")
        if not isinstance(children, list) or not children or any(not isinstance(child, dict) for child in children):
            return {**missing, "detail": "malformed_compound_condition"}
        failures = [_effect_condition_failure({"condition": child}, hit) for child in children]
        if condition_type == 'any' and any(failure is None for failure in failures):
            return None
        failures = [failure for failure in failures if failure is not None]
        if not failures:
            return None
        return next((failure for failure in failures if failure.get("reason_group") == "condition_unobservable"), failures[0])
    if condition_type in {"target_hp_compare", "target_hp_ratio_lte"}:
        compare = condition.get("compare") if condition_type == "target_hp_compare" else "LE"
        is_ratio = condition.get("is_ratio") if condition_type == "target_hp_compare" else True
        threshold = _coerce_optional_float(condition.get("threshold"))
        subject = condition.get('subject_side', 'defender')
        if subject not in {'attacker', 'defender'}:
            return {**missing, 'detail': 'invalid_condition_subject'}
        hp_before = _coerce_optional_float(hit.get('attacker_hp_before' if subject == 'attacker' else 'enemy_hp_before'))
        maximum = _coerce_optional_float(hit.get('attacker_max_hp' if subject == 'attacker' else 'target_enemy_max_hp'))
        if (compare not in {"LT", "LE", "GT", "GE", "EQ", "NE"} or not isinstance(is_ratio, bool)
                or threshold is None or threshold < 0 or hp_before is None or hp_before < 0):
            return {**missing, "detail": "invalid_hp_comparison"}
        if is_ratio and (maximum is None or maximum <= 0 or hp_before > maximum or threshold > 1):
            return {**missing, "detail": "missing_explicit_maximum_hp"}
        value = hp_before / maximum if is_ratio else hp_before
        passed = {"LT": value < threshold, "LE": value <= threshold, "GT": value > threshold,
                  "GE": value >= threshold, "EQ": value == threshold, "NE": value != threshold}[compare]
        if passed:
            return None
        return {"reason": "target_hp_condition_unsatisfied", "reason_group": "condition_unsatisfied",
                "condition_type": condition_type, "condition_compare": compare, "condition_threshold": threshold,
                "target_hp_before": hp_before, "target_max_hp": maximum, "compared_value": value}
    if condition_type == "target_has_buff":
        ids = condition.get("buff_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(key, str) or not key for key in ids):
            return {**missing, "detail": "invalid_required_buff_ids"}
        subject = condition.get('subject_side', 'defender')
        if subject not in {'attacker', 'defender'}:
            return {**missing, 'detail': 'invalid_condition_subject'}
        active = hit.get('_active_attacker_buff_ids' if subject == 'attacker' else '_active_target_buff_ids')
        if not isinstance(active, (list, set, tuple)):
            return {**missing, "detail": "missing_target_buff_state"}
        if set(ids).intersection(active):
            return None
        if hit.get('attacker_buff_state_complete' if subject == 'attacker' else 'target_buff_state_complete') is not True:
            return {**missing, "detail": "incomplete_target_buff_state", "condition_buff_ids": ids}
        return {"reason": "target_buff_missing", "reason_group": "condition_unsatisfied", "condition_buff_ids": ids}
    if condition_type == "damage_type_in":
        elements = condition.get("elements")
        valid = {"physical", "fire", "pulse", "cryst", "natural"}
        actual = hit.get("damage_element")
        if not isinstance(elements, list) or not elements or any(value not in valid for value in elements) or actual not in valid:
            return {**missing, "detail": "unresolved_damage_type"}
        if actual in elements:
            return None
        return {"reason": "damage_type_filtered", "reason_group": "condition_unsatisfied",
                "condition_type": condition_type, "condition_elements": elements, "damage_element": actual}
    return {**missing, "reason": "condition_type_unsupported", "detail": "unsupported_condition"}



def _normalize_condition_damage_type(value: Any) -> str | None:
    lowered = str(value or "").strip().lower()
    if lowered in {"physical", "physic"}:
        return "physical"
    if lowered in {"fire", "pulse", "cryst", "crystal", "natural"}:
        return "cryst" if lowered == "crystal" else lowered
    return None


@lru_cache(maxsize=4096)
def _decoded_damage_modifier_condition_rows(buff_id: str) -> dict[int, dict[str, Any]]:
    payload = _load_current_buff_roots().get(buff_id)
    if not isinstance(payload, dict):
        return {}
    modifiers = payload.get("damageModifier")
    if not isinstance(modifiers, list):
        return {}
    rows = {}
    for index, modifier in enumerate(modifiers):
        conditions = []
        errors = []
        container = modifier.get("condition") if isinstance(modifier, dict) else None
        actions = container.get("actionData") if isinstance(container, dict) else None
        if not isinstance(actions, list):
            rows[index] = {"conditions": [], "errors": ["missing_condition_actions"]}
            continue
        if any(container.get(key) is not False for key in ("onlyExecuteWhenSourceIsMainChar", "onlyExecuteWhenSourceIsGuard")):
            errors.append("unresolved_source_guard")
        disabled = 0
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("isEnable"), bool):
                errors.append("missing_condition_enabled_state")
                continue
            if action["isEnable"] is False:
                disabled += 1
                continue
            # C# nested-type notation differs between JSON.NET's old display
            # JSON (+Data) and the fully qualified current metadata (.Data).
            symbol = str(action.get('$type') or '').split(',', 1)[0].replace('+', '.')
            action_type = {
                'Beyond.Gameplay.Core.Conditions.CheckHp.Data': 'CheckHp',
                'Beyond.Gameplay.Core.Conditions.CheckDamageType.Data': 'CheckDamageType',
                'Beyond.Gameplay.Core.Conditions.CheckDamageTypeMask.Data': 'CheckDamageTypeMask',
                'Beyond.Gameplay.Core.Conditions.CheckDamageDecorateMask.Data': 'CheckDamageDecorateMask',
                'Beyond.Gameplay.Core.CheckBuffStackNumAdvanced.Data': 'CheckBuffStackNumAdvanced',
            }.get(symbol, symbol)
            if action_type not in {"CheckHp", "CheckDamageType", "CheckDamageTypeMask", "CheckDamageDecorateMask", "CheckBuffStackNumAdvanced"}:
                errors.append("unsupported_action:" + action_type)
                continue
            if action_type in {"CheckHp", "CheckBuffStackNumAdvanced"}:
                selector = action.get("hpOwner" if action_type == "CheckHp" else "checkTarget")
                if not isinstance(selector, dict) or selector.get("targetSource") != "Target":
                    errors.append("unsupported_condition_target")
                    continue
                selection = selector.get("selectorData") or {}
                if (not isinstance(selection, dict) or selection.get("validatorData") or selection.get("postProcessorData")
                        or any(selector.get(key) for key in ("targetGroupKey", "ownerContextKey", "targetContextKey"))):
                    errors.append("unsupported_condition_selector")
                    continue
            if action_type == "CheckHp":
                value = action.get("value")
                compare = action.get("compare")
                if (compare not in {"LT", "LE", "GT", "GE", "EQ", "NE"}
                        or not isinstance(action.get("isRatio"), bool) or not isinstance(value, dict)
                        or not isinstance(value.get("useBlackboardKey"), bool)
                        or (value["useBlackboardKey"] and not value.get("blackboardKey"))):
                    errors.append("unsupported_hp_comparison")
                    continue
                conditions.append({"type": "target_hp_compare", "source": action_type,
                                   "compare": compare, "is_ratio": action["isRatio"], "value_config": dict(value)})
            elif action_type == "CheckDamageType":
                element = _normalize_condition_damage_type(action.get("damageType"))
                if element is None:
                    errors.append("unresolved_damage_type")
                    continue
                conditions.append({"type": "damage_type_in", "source": action_type, "elements": [element]})
            elif action_type == 'CheckDamageTypeMask':
                mask = action.get('damageTypeMask')
                # A defined enum value is serialized as its exact name;
                # combinations are integers. These names are version-bound
                # DamageTypeMask declarations, not inferred from a Buff ID.
                if type(mask) is str:
                    mask = {'Physical': 1, 'Real': 2, 'Fire': 4, 'Pulse': 8,
                            'Cryst': 16, 'LifeDrain': 32, 'Natural': 64, 'Ether': 128}.get(mask)
                # Exact DamageTypeMask enum bits. Representing a condition
                # does not grant an external effect whitelist approval.
                bits = {1: 'physical', 2: 'real', 4: 'fire', 8: 'pulse', 16: 'cryst',
                        32: 'lifedrain', 64: 'natural', 128: 'ether'}
                if type(mask) is not int or mask <= 0 or mask & ~sum(bits):
                    errors.append('unsupported_damage_type_mask')
                    continue
                conditions.append({'type': 'damage_type_in', 'source': action_type,
                                   'elements': [element for bit, element in bits.items() if mask & bit]})
            elif action_type == 'CheckDamageDecorateMask':
                mask, check = action.get('mask'), action.get('checkType')
                if type(mask) is not int or mask < 0 or check not in {'HasAll', 'HasAny'}:
                    errors.append('unsupported_damage_decorate_check')
                    continue
                conditions.append({'type': 'damage_decorate_mask', 'source': action_type,
                                   'mask': mask, 'check': check})
            else:
                settings = action.get("buffSettings") or {}
                value = action.get("value") or {}
                ids = settings.get("buffIdList") if isinstance(settings, dict) else None
                if (not isinstance(ids, list) or not ids or any(not isinstance(key, str) or not key for key in ids)
                        or settings.get("checkType") != "Id" or action.get("buffStackNumType") != "BuffCount"
                        or action.get("compareType") != "GE" or action.get("limitSkillCastId") is not False
                        or not isinstance(value, dict) or value.get("useBlackboardKey") is not False
                        or _coerce_optional_float(value.get("value")) != 1.0):
                    errors.append("unsupported_buff_count_comparison")
                    continue
                conditions.append({"type": "target_has_buff", "source": action_type, "buff_ids": sorted(set(ids))})
        rows[index] = {"conditions": conditions, "errors": errors, "action_count": len(actions),
                       "all_disabled": bool(actions) and disabled == len(actions)}
    return rows
