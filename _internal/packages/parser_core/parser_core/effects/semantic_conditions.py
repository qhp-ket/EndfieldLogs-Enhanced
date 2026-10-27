"""Resolve declared damage conditions against exact resource evidence."""
from __future__ import annotations

from parser_core.allocation.static_loadout import _ATTR_TYPE_TO_EFFECT
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.buff_templates import _load_damage_zone_config
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.conditions import _condition_damage_type_elements
from parser_core.effects.conditions import _decoded_damage_modifier_condition_rows
from parser_core.effects.damage_types import _ATTR_TYPE_DAMAGE_MASK
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.registry import _rdps_registry_candidate_effect_entry
from parser_core.ingestion.fields import _coerce_optional_float
import re
from typing import Any


def _semantic_entry_bb_keys(entry: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in entry.get("blackboard") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if isinstance(key, str) and key:
            keys.add(key)
    return keys


def _semantic_entry_has_rdps(entry: dict[str, Any]) -> bool:
    flags = entry.get("semanticFlags") if isinstance(entry.get("semanticFlags"), dict) else {}
    counts = entry.get("modifierCounts") if isinstance(entry.get("modifierCounts"), dict) else {}
    probe = entry.get("binaryProbe") if isinstance(entry.get("binaryProbe"), dict) else {}
    return bool(
        flags.get("hasTemplateModifiers")
        or flags.get("hasAttributeModifier")
        or flags.get("hasDamageModifier")
        or counts.get("attribute")
        or counts.get("damage")
        or probe.get("rdpsCandidate")
    )


def _semantic_blackboard_defaults(entry: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for row in entry.get("blackboard") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        if not key:
            continue
        if row.get("defaultDouble") is not None:
            defaults[key] = row.get("defaultDouble")
        elif row.get("defaultString") not in (None, ""):
            defaults[key] = row.get("defaultString")
    return defaults


def _semantic_damage_effect_zone(effect: dict[str, Any]) -> tuple[str, str] | None:
    if str(effect.get("processorType") or "") != "DamageScaleProcessor":
        return None
    zone_name = str(effect.get('zoneName') or '')
    config = _load_damage_zone_config().get(zone_name)
    if not isinstance(config, dict):
        return None
    side = str(effect.get("side") or effect.get("enableSide") or "")
    if zone_name == 'ProdCalcZone':
        if side == 'Attacker':
            return 'prod_dmg_inc', 'all'
        if side == 'Defender':
            return 'prod_vuln_taken', 'all'
        return None
    if zone_name != 'NormalCalcZone':
        return None
    if side == "Attacker":
        return "dmg_inc", "all"
    if side == "Defender":
        return "vuln_taken", "all"
    return None


def _semantic_damage_effect_condition(
    buff_id: str,
    effect: dict[str, Any],
    *,
    defaults: dict[str, Any],
    bb_values: dict[str, Any],
) -> dict[str, Any] | None:
    group_index = effect.get("groupIndex")
    if isinstance(group_index, bool) or not re.fullmatch(r"\d+", str(group_index)):
        return {"type": "unresolved", "errors": ["missing_condition_group_index"]}
    decoded = _decoded_damage_modifier_condition_rows(buff_id).get(int(group_index))
    if not decoded:
        return {"type": "unresolved", "errors": ["missing_decoded_condition"]}
    if decoded.get("errors"):
        return {"type": "unresolved", "errors": list(decoded["errors"])}
    if decoded.get("all_disabled"):
        return {"type": "always", "source": "decoded_disabled_conditions"}
    if decoded.get("action_count") == 0:
        return {"type": "always", "source": "decoded_empty_conditions"}
    conditions = []
    for raw in decoded.get("conditions") or []:
        condition = dict(raw)
        if condition.get('type') in {'target_hp_compare', 'target_has_buff'} and effect.get('enableSide') in {'Attacker', 'Defender'}:
            # ApplyModifier sets TargetHandle to the opposite participant
            # of the modifier's enabled/owning side, independently of the
            # processor's destination damage zone.
            condition['subject_side'] = 'defender' if effect['enableSide'] == 'Attacker' else 'attacker'
        if condition.get("type") == "target_hp_compare":
            config = condition.pop("value_config")
            key = str(config.get("blackboardKey") or "")
            value = bb_values.get(key) if config["useBlackboardKey"] else config.get("value")
            threshold = _coerce_optional_float(value)
            if threshold is None or threshold < 0 or (condition["is_ratio"] and threshold > 1):
                return {"type": "unresolved", "errors": ["missing_or_invalid_hp_threshold"], "bb_key": key}
            condition["threshold"] = threshold
            if config["useBlackboardKey"]:
                condition["threshold_key"] = key
        conditions.append(condition)
    if not conditions:
        return {"type": "unresolved", "errors": ["empty_decoded_condition"]}
    if len(conditions) == 1:
        return conditions[0]
    return {"type": "all", "source": "decoded_conditions", "conditions": conditions}


def _collect_semantic_condition_zone_effects(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> list[dict[str, Any]]:
    buff_id = _normalize_buff_id(record.get("event_key"))
    root = _load_current_buff_roots().get(buff_id)
    record.pop('rdps_unresolved_semantic_condition', None)
    record.pop('rdps_unapproved_typed_branches', None)
    if not isinstance(root, dict):
        record['rdps_unresolved_semantic_condition'] = ['missing_current_buff_root']
        return []
    bb_values = {str(key): value for key, value in (record.get("bb_values") or {}).items()}
    effects: list[dict[str, Any]] = []
    modifiers = root.get('damageModifier')
    if not isinstance(modifiers, list):
        record['rdps_unresolved_semantic_condition'] = ['unspecified_damage_modifiers']
        return []
    declared = []
    for group_index, modifier in enumerate(modifiers):
        if not isinstance(modifier, dict) or not isinstance(modifier.get('damageProcessors'), list):
            record['rdps_unresolved_semantic_condition'] = ['unspecified_damage_processors']
            return []
        if modifier.get('enableSide') not in {'Attacker', 'Defender'}:
            record['rdps_unresolved_semantic_condition'] = ['unsupported_modifier_entry_side']
            return []
        for processor in modifier['damageProcessors']:
            if not isinstance(processor, dict):
                record['rdps_unresolved_semantic_condition'] = ['unsupported_damage_processor_or_side']
                return []
            processor_type = processor.get('$type')
            if processor_type == 'Beyond.Gameplay.Core.DamageScaleProcessor':
                if processor.get('side') not in {'Attacker', 'Defender'}:
                    record['rdps_unresolved_semantic_condition'] = ['unsupported_damage_processor_or_side']
                    return []
                declared.append({**processor, 'groupIndex': group_index, 'processorType': 'DamageScaleProcessor',
                                 'enableSide': modifier['enableSide']})
                continue
            # InstantModifyAttribute is the native processor used by
            # resistance-ignore windows. Only accept the fully typed fire
            # resistance form; other attributes remain unknown.
            if processor_type == 'Beyond.Gameplay.Core.InstantModifyAttribute':
                typed_modifier = processor.get('modifier')
                if (not isinstance(typed_modifier, dict)
                        or typed_modifier.get('attributeType') != 'FireResistance'
                        or typed_modifier.get('formulaItem') != 'BaseAddition'
                        or typed_modifier.get('modifyAttributeType') != 'Specific'
                        or processor.get('modifyTargetSide') != 'Defender'):
                    record['rdps_unresolved_semantic_condition'] = ['unsupported_damage_processor_or_side']
                    return []
                declared.append({
                    'groupIndex': group_index,
                    'processorType': 'InstantModifyAttribute',
                    'side': 'Defender',
                    'enableSide': modifier['enableSide'],
                    'addition': typed_modifier.get('param') or {},
                    'attributeType': 'FireResistance',
                })
                continue
            record['rdps_unresolved_semantic_condition'] = ['unsupported_damage_processor_or_side']
            return []
    approval = _rdps_registry_candidate_effect_entry(record, root_lookup_cache=root_lookup_cache)
    approved_specs = (approval.get('effects') or []) if isinstance(approval, dict) else []
    for damage_effect in declared:
        # A newly added typed branch cannot expand an existing element-specific
        # whitelist. An enabled AND condition with disjoint damage types proves
        # it is outside that approval, even when another action in the branch
        # is not supported. Preserve the boundary without guessing that action.
        decoded = _decoded_damage_modifier_condition_rows(buff_id).get(damage_effect['groupIndex']) or {}
        addition = damage_effect.get('addition') if isinstance(damage_effect.get('addition'), dict) else {}
        bb_key = addition.get('blackboardKey') if addition.get('useBlackboardKey') is True else None
        scopes = [spec.get('element', 'all') for spec in approved_specs if isinstance(spec, dict)
                  and bb_key and bb_key in {spec.get('bb_key'), *(spec.get('bb_keys') or [])}]
        if (scopes and all(scope in {'physical', 'spell', 'fire', 'pulse', 'cryst', 'natural',
                                     'real', 'lifedrain', 'ether'} for scope in scopes)
                and 'unresolved_source_guard' not in decoded.get('errors', [])):
            allowed = set().union(*({'fire', 'pulse', 'cryst', 'natural'} if scope == 'spell' else {scope}
                                    for scope in scopes))
            restrictions = [set(condition['elements']) for condition in decoded.get('conditions') or []
                            if condition.get('type') == 'damage_type_in' and condition.get('elements')]
            if any(not allowed.intersection(elements) for elements in restrictions):
                record.setdefault('rdps_unapproved_typed_branches', []).append({
                    'group_index': damage_effect['groupIndex'], 'bb_key': bb_key,
                    'reason': 'typed_damage_types_disjoint_from_whitelist',
                    'whitelist_elements': sorted(allowed),
                    'typed_damage_types': sorted(set.union(*restrictions)),
                    'unsupported_conditions': list(decoded.get('errors') or []),
                })
                continue
        condition = _semantic_damage_effect_condition(
            buff_id,
            damage_effect,
            defaults={},
            bb_values=bb_values,
        )
        if condition is None:
            continue
        if condition.get("type") == "unresolved":
            record["rdps_unresolved_semantic_condition"] = condition.get("errors") or ["unresolved_condition"]
            continue
        if damage_effect.get('processorType') == 'InstantModifyAttribute':
            zone_element = ('res', 'fire')
        else:
            zone_element = _semantic_damage_effect_zone(damage_effect)
        if zone_element is None:
            record['rdps_unresolved_semantic_condition'] = ['unsupported_damage_zone']
            continue
        zone, element = zone_element
        addition = damage_effect.get("addition") if isinstance(damage_effect.get("addition"), dict) else {}
        bb_key = str(addition.get("blackboardKey") or "")
        use_key = addition.get('useBlackboardKey')
        rate = (_coerce_optional_float(bb_values.get(bb_key)) if use_key is True and bb_key else
                _coerce_optional_float(addition.get('value')) if use_key is False else None)
        if damage_effect.get('processorType') == 'InstantModifyAttribute' and rate is not None:
            # FireResistance BaseAddition is encoded as a signed decrease
            # (e.g. -20); the rDPS res lane stores the corresponding positive
            # amount removed from resistance.
            rate = -rate
        if rate is None or rate < 0:
            record["rdps_unresolved_semantic_condition"] = ["missing_or_invalid_effect_rate"]
            continue
        condition_elements = _condition_damage_type_elements(condition)
        if element == "all" and len(condition_elements) == 1:
            element = next(iter(condition_elements))
        effect = {
            "zone": zone,
            "element": _normalize_effect_element(element),
            "rate": rate,
            "condition": condition,
            "semantic_source": "typed_current_damageModifier",
            'recipient_side': damage_effect['enableSide'].lower(),
        }
        if zone.startswith('prod_'):
            effect['multiplicative'] = True
        if bb_key:
            effect["bb_key"] = bb_key
        effects.append(effect)
    attributes = root.get('attributeModifier')
    if isinstance(attributes, dict):
        typed_attribute_types = {
            'Atk': (2, 'BaseMultiplier'),
            'NormalAttackDamageIncrease': (17, 'BaseAddition'),
            'UltimateSkillDamageIncrease': (28, 'BaseAddition'),
            'NormalSkillDamageIncrease': (32, 'BaseAddition'),
            'ComboSkillDamageIncrease': (33, 'BaseAddition'),
            'FireDamageIncrease': (51, 'BaseAddition'),
            'PhysicalDamageIncrease': (50, 'BaseAddition'),
            'PulseDamageIncrease': (52, 'BaseAddition'),
            'CrystDamageIncrease': (53, 'BaseAddition'),
            'NaturalDamageIncrease': (54, 'BaseAddition'),
            'PulseEnhancedDmgIncrease': (66, 'BaseAddition'),
            'FireEnhancedDmgIncrease': (65, 'BaseAddition'),
            'CrystEnhancedDmgIncrease': (67, 'BaseAddition'),
            'NaturalEnhancedDmgIncrease': (68, 'BaseAddition'),
            'PhysicalAndSpellInflictionEnhance': (87, 'BaseAddition'),
        }
        typed_vulnerability_types = {
            'PhysicalVulnerableDmgIncrease': ('fragile', 'physical'),
            'FireVulnerableDmgIncrease': ('fragile', 'fire'),
            'PulseVulnerableDmgIncrease': ('fragile', 'pulse'),
            'CrystVulnerableDmgIncrease': ('fragile', 'cryst'),
            'NaturalVulnerableDmgIncrease': ('fragile', 'natural'),
        }
        for modifier in attributes.get('attributeModifiers') or []:
            attr_spec = typed_attribute_types.get(modifier.get('attributeType')) if isinstance(modifier, dict) else None
            vulnerability_zone = (typed_vulnerability_types.get(modifier.get('attributeType'))
                                  if isinstance(modifier, dict) else None)
            if attr_spec is None:
                if vulnerability_zone is None:
                    continue
                attr_type, required_formula = None, 'BaseAddition'
            else:
                attr_type, required_formula = attr_spec
            if (type(attributes.get('isConvertedAttribute')) is not bool
                    or modifier.get('formulaItem') != required_formula
                    or modifier.get('modifyAttributeType') != 'Specific'):
                record['rdps_unresolved_semantic_condition'] = ['unsupported_conditional_attribute_formula']
                return []
            param = modifier.get('param') or {}
            bb_key = str(param.get('blackboardKey') or '')
            use_key = param.get('useBlackboardKey')
            rate = (_coerce_optional_float(bb_values.get(bb_key)) if use_key is True and bb_key else
                    _coerce_optional_float(param.get('value')) if use_key is False else None)
            if rate is None or rate < 0:
                record['rdps_unresolved_semantic_condition'] = ['missing_or_invalid_attribute_rate']
                return []
            zone, element = vulnerability_zone or (('arts_strength', 'all') if attr_type == 87 else _ATTR_TYPE_TO_EFFECT[attr_type])
            condition = ({'type': 'damage_decorate_mask', 'check': 'HasAny',
                          'mask': _ATTR_TYPE_DAMAGE_MASK[attr_type],
                          'source': 'DamagePackData.GetAttackerDamageScaleIncreaseFromSkillType'}
                         if attr_type in _ATTR_TYPE_DAMAGE_MASK else None)
            effects.append({'zone': zone, 'element': element, 'rate': rate, 'attr_type': attr_type,
                            'bb_key': bb_key if use_key is True else '',
                            **({'condition': condition} if condition is not None else {}),
                            'semantic_source': 'typed_current_attributeModifier'})
            if attributes['isConvertedAttribute']:
                # Full Attributes.GetValue uses FilerTypeMask.All (-1),
                # which includes Converted. Read the observed BB operand;
                # do not reconstruct the conversion that generated it.
                effects[-1]['converted_attribute'] = True
    return effects
