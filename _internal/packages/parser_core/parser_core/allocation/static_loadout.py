"""Derive static loadout effects and observed attack baselines from verified resources."""
from __future__ import annotations

from collections import Counter
from collections import defaultdict
from parser_core.catalog.names import _CURRENT_TYPED_RESOURCE_BINDING
from parser_core.catalog.names import _canonical_num_table_skill_number
from parser_core.catalog.names import _load_num_id_str_skill_map
from parser_core.catalog.resources import _NATIVE_DAMAGE_SEMANTICS_BINDING
from parser_core.catalog.resources import _load_character_base_stat_catalog
from parser_core.catalog.resources import _load_equip_item_catalog
from parser_core.catalog.resources import _load_weapon_catalog
from parser_core.catalog.resources import _repo_root
from parser_core.ingestion.fields import _coerce_optional_float
import json
import re
from typing import Any

from parser_core.effects.conditions import _effect_condition_failure
from parser_core.effects.damage_types import _attr_type_applies_to_skill
from parser_core.effects.damage_types import _effect_applies_to_damage_element
from parser_core.effects.registry import _RDPS_ALLOCATABLE_ZONES
from parser_core.ingestion.fields import _safe_positive_rate


_RDPS_DEBUG_ZONE_LABELS = {
    "atk": "攻击",
    "dmg_inc": "增伤",
    "fragile": "脆弱",
    "vuln_taken": "易伤",
    "amp": "增幅",
    "res": "减抗",
    "combo": "连击",
    "crit": "暴击",
    "arts_strength": "源石技艺强度",
    "prod_dmg_inc": "独立增伤",
    "prod_vuln_taken": "独立承伤易伤",
}


_ATTR_TYPE_TO_EFFECT = {
    2: ("atk", "all"),
    9: ("crit", "all"),
    10: ("crit", "all"),
    17: ("dmg_inc", "all"),
    28: ("dmg_inc", "all"),
    32: ("dmg_inc", "all"),
    33: ("dmg_inc", "all"),
    50: ("dmg_inc", "physical"),
    51: ("dmg_inc", "fire"),
    # 52/54 依据 AttributeMetaTable 官方语义补齐（icon_pulse/natural_damage_increase），
    # 此前缺失导致电磁/自然系角色的属性快照增伤丢失。
    52: ("dmg_inc", "pulse"),
    53: ("dmg_inc", "cryst"),
    54: ("dmg_inc", "natural"),
    55: ("dmg_inc", "ether"),
    65: ("amp", "fire"),
    66: ("amp", "pulse"),
    67: ("amp", "cryst"),
    68: ("amp", "natural"),
    70: ("fragile", "physical"),
    71: ("fragile", "fire"),
    72: ("fragile", "pulse"),
    73: ("fragile", "cryst"),
    74: ("fragile", "natural"),
    75: ("fragile", "ether"),
}


def _character_base_stats(character_key: str | None, level: int | None) -> dict[str, Any] | None:
    key = str(character_key or "")
    if not key:
        return None
    rows = _load_character_base_stat_catalog().get(key)
    if not rows:
        return None
    if type(level) is not int or level <= 0:
        return None
    exact = rows.get(int(level))
    if exact is not None:
        return {
            **exact,
            "level_source": "loadout",
        }
    return None


def _derive_static_arts_strength_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    # Baseline points belong to exact equipment slots or exact card properties,
    # never to a matching number or an arbitrary BB field name.
    candidates: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for attribute in row.get('equipment_baseline_attributes') or []:
        if (not isinstance(attribute, dict) or attribute.get('source_type') != 'equip_baseline'
                or attribute.get('attr_type') != 87
                or attribute.get('evidence_kind') != 'official_EquipTable_attribute_zero_or_exact'
                or not isinstance(attribute.get('source_id'), str) or not attribute['source_id']
                or any(type(attribute.get(key)) is not int or attribute[key] < 0
                       for key in ('source_slot', 'attr_index', 'enhance_level'))
                or not re.fullmatch(r'[0-9a-f]{64}', str(attribute.get('source_table_sha256') or ''))):
            continue
        value = _coerce_optional_float(attribute.get('value'))
        if value is None or value < 0:
            continue
        identity = ('equip', attribute['source_slot'], attribute['source_id'], attribute['attr_index'])
        candidates[identity].append({
            'source_type': 'equip', 'source_name': attribute['source_id'], 'source_id': attribute['source_id'],
            'source_slot': attribute['source_slot'], 'attr_index': attribute['attr_index'],
            'enhance_level': attribute['enhance_level'], 'rate': value,
            'source_table_sha256': attribute['source_table_sha256'],
            'evidence_kind': attribute['evidence_kind'],
        })
    try:
        catalog = json.loads((_repo_root() / 'data/local_static/skill/item_arts_strength_catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        catalog = {}
    decoder = catalog.get('decoder') if isinstance(catalog, dict) else None
    if (not isinstance(catalog, dict) or catalog.get('schemaVersion') != 1
            or catalog.get('source') != 'current_official_item_skill_card_attribute'
            or not isinstance(decoder, dict)
            or any(decoder.get(key) != value for key, value in _NATIVE_DAMAGE_SEMANTICS_BINDING.items())):
        catalog = {}
    weapon_id = str(row.get('weapon_template') or '')
    declared_skills = (_load_weapon_catalog().get(weapon_id) or {}).get('weapon_skill_ids') or []
    for category, definitions in (('suit', catalog.get('suitEntries') or []),
                                  ('weapon', catalog.get('weaponEntries') or [])):
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            modifier = definition.get('modifier') or {}
            param = modifier.get('param') or {}
            if (modifier.get('$type') != 'Beyond.Gameplay.AttributeModifierData.AttributeModifier'
                    or modifier.get('attributeType') != 'PhysicalAndSpellInflictionEnhance'
                    or modifier.get('formulaItem') != 'BaseAddition' or modifier.get('modifyAttributeType') != 'Specific'
                    or param.get('useBlackboardKey') is not True
                    or param.get('blackboardKey') != definition.get('bbKey')
                    or not isinstance(definition.get('bbKey'), str) or not definition['bbKey']
                    or type(definition.get('attributeIndex')) is not int or definition['attributeIndex'] < 0
                    or type(definition.get('sourceBytes')) is not int or definition['sourceBytes'] <= 0
                    or definition.get('consumedBytes') != definition['sourceBytes']
                    or not re.fullmatch(r'[0-9a-f]{64}', str(definition.get('sourceSha256') or ''))):
                continue
            source_rows = []
            if category == 'weapon':
                bindings = [binding for binding in definition.get('weaponBindings') or []
                            if isinstance(binding, dict) and binding.get('weaponId') == weapon_id
                            and type(binding.get('skillSlot')) is int and 0 <= binding['skillSlot'] < len(declared_skills)
                            and declared_skills[binding['skillSlot']] == definition.get('skillId')]
                if (len(bindings) != 1 or _load_num_id_str_skill_map().get(str(definition.get('numericSkillId')))
                        != definition.get('skillId')):
                    continue
                for skill in row.get('weapon_source_skills') or row.get('weapon_refine_stats') or []:
                    if not isinstance(skill, dict):
                        continue
                    skill_id = str(skill.get('skill_id') or '')
                    canonical = _load_num_id_str_skill_map().get(skill_id) if skill_id.isdigit() else skill_id
                    if canonical == definition['skillId'] and isinstance(skill.get('bb'), dict):
                        source_rows.append((weapon_id, 'weapon_skill', weapon_id, skill['bb']))
            else:
                for effect in row.get('suit_effects') or []:
                    if (isinstance(effect, dict) and effect.get('suit_id') == definition.get('suitId')
                            and effect.get('active') is True and isinstance(effect.get('value'), dict)):
                        source_rows.append((effect['suit_id'], 'equip_suit',
                                            str(effect.get('suit_name') or effect['suit_id']), effect['value']))
            for item_id, source_type, source_name, bb in source_rows:
                value = _coerce_optional_float(bb.get(definition['bbKey']))
                if value is None or value < 0:
                    continue
                identity = (category, item_id, definition['skillId'], definition['attributeIndex'])
                candidates[identity].append({
                    'source_type': source_type, 'source_name': source_name,
                    'source_id': definition['skillId'], 'item_id': item_id,
                    'attr_index': definition['attributeIndex'], 'bb_key': definition['bbKey'], 'rate': value,
                    'source_resource_sha256': definition['sourceSha256'],
                    'evidence_kind': 'current_official_item_skill_card_attribute',
                })
    entries = []
    for identity, values in candidates.items():
        signatures = {json.dumps({key: field for key, field in value.items() if key != 'source_name'},
                                 sort_keys=True, ensure_ascii=False) for value in values}
        if len(signatures) != 1:
            row.setdefault('rdps_unresolved_static_multiplier_sources', []).append({
                'reason': 'conflicting_static_arts_strength_source', 'identity': list(identity)})
            continue
        entry = dict(values[0])  # One proven source with identical numeric/provenance observations.
        if len({value['source_name'] for value in values}) != 1:
            entry['source_name'] = str(entry.get('item_id') or entry['source_id'])
        if entry['rate'] > 0:
            entries.append({**entry, 'attr_type': 87, 'zone': 'arts_strength',
                            'zone_label': _RDPS_DEBUG_ZONE_LABELS['arts_strength'], 'element': 'all',
                            'condition_text': ''})
    return entries


def _derive_static_self_multiplier_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    row['rdps_unresolved_static_multiplier_sources'] = []
    if row.get('unresolved_equip_inst_ids'):
        row['rdps_unresolved_static_multiplier_sources'].append({
            'reason': 'unresolved_equipment_slot', 'equip_inst_ids': list(row['unresolved_equip_inst_ids'])})
    equip_slots = Counter(equip.get('slot') for equip in row.get('equips') or [] if isinstance(equip, dict))
    baseline_attributes: list[dict[str, Any]] = []
    allocatable_attr_types = {2, 17, 28, 32, 33, 50, 51, 52, 53, 54}
    for equip in row.get("equips") or []:
        if not isinstance(equip, dict):
            continue
        item_id, slot = str(equip.get('item_id') or ''), equip.get('slot')
        meta = _load_equip_item_catalog().get(item_id, {})
        modifiers, proof = meta.get('attribute_modifiers'), meta.get('attribute_source_sha256')
        if (type(slot) is not int or equip_slots[slot] != 1 or not isinstance(modifiers, list)
                or not isinstance(proof, str) or not re.fullmatch(r'[0-9a-f]{64}', proof)):
            row['rdps_unresolved_static_multiplier_sources'].append({'item_id': item_id, 'slot': slot,
                'reason': 'missing_or_conflicting_equipment_attribute_evidence'})
            continue
        levels = defaultdict(set)
        for level in equip.get('enhance_levels') or []:
            if (isinstance(level, dict) and type(level.get('index')) is int
                    and type(level.get('level')) is int):
                levels[level['index']].add(level['level'])
        if row.get('equipment_snapshot_complete') is True:
            for modifier in modifiers:
                if (isinstance(modifier, dict) and type(modifier.get('attrIndex')) is int
                        and not levels.get(modifier['attrIndex'])):
                    # A protobuf map omits only the entries at their default
                    # value; each absent attribute index is therefore level 0.
                    levels[modifier['attrIndex']].add(0)
        for modifier in modifiers:
            if not isinstance(modifier, dict):
                row['rdps_unresolved_static_multiplier_sources'].append({'item_id': item_id, 'reason': 'invalid_attribute_row'})
                continue
            attr_type, formula, target = modifier.get('attrType'), modifier.get('modifierType'), modifier.get('modifyAttributeType')
            if any(type(value) is not int for value in (attr_type, formula, target)):
                row['rdps_unresolved_static_multiplier_sources'].append({'item_id': item_id, 'reason': 'invalid_attribute_enum'})
                continue
            if (row.get('equipment_snapshot_complete') is True
                    and attr_type not in allocatable_attr_types
                    and attr_type not in {39, 40, 41, 42, 87}):
                index = modifier.get('attrIndex')
                raw_values = modifier.get('attrValues')
                values = [_coerce_optional_float(value) for value in raw_values] if isinstance(raw_values, list) else []
                candidates = levels.get(index, set())
                level = next(iter(candidates)) if len(candidates) == 1 else None
                value = (values[level] if level is not None and 0 <= level < len(values)
                         and all(v is not None for v in values) else None)
                if value is not None and value >= 0:
                    baseline_attributes.append({
                        'source_type': 'equip_baseline', 'source_id': item_id,
                        'source_slot': slot, 'attr_type': attr_type,
                        'attr_index': index, 'value': value, 'enhance_level': level,
                        'modifier_type': formula, 'modify_attribute_type': target,
                        'evidence_kind': 'official_EquipTable_attribute_zero_or_exact',
                        'source_table_sha256': proof,
                    })
                    stats = equip.get('stats')
                    if isinstance(stats, list) and type(index) is int and 0 <= index < len(stats):
                        stat = stats[index]
                        if isinstance(stat, dict) and stat.get('value') == 'unknown':
                            stat['value'] = value
                            stat['level'] = level
                            stat['value_source'] = 'official_EquipTable_attribute_zero_or_exact'
                    continue
            # This path handles percentage attack and additive damage bonuses.
            # Main/sub ability, flat stats and other mechanisms are separate.
            if (row.get('equipment_snapshot_complete') is True
                    and target == 0 and attr_type in {39, 40, 41, 42, 87} and formula == 5):
                index = modifier.get('attrIndex')
                raw_values = modifier.get('attrValues')
                values = [_coerce_optional_float(value) for value in raw_values] if isinstance(raw_values, list) else []
                candidates = levels.get(index, set())
                level = next(iter(candidates)) if len(candidates) == 1 else None
                value = values[level] if (level is not None and 0 <= level < len(values)
                                          and all(v is not None for v in values)) else None
                if value is not None and value >= 0:
                    baseline_attributes.append({
                        'source_type': 'equip_baseline', 'source_id': item_id,
                        'source_slot': slot, 'attr_type': attr_type,
                        'attr_index': index, 'value': value, 'enhance_level': level,
                        'evidence_kind': 'official_EquipTable_attribute_zero_or_exact',
                        'source_table_sha256': proof,
                    })
                    stats = equip.get('stats')
                    if isinstance(stats, list) and type(index) is int and 0 <= index < len(stats):
                        stat = stats[index]
                        if isinstance(stat, dict) and stat.get('value') == 'unknown':
                            stat['value'] = value
                            stat['level'] = level
                            stat['value_source'] = 'official_EquipTable_attribute_zero_or_exact'
                    continue
            if target != 0 or attr_type in {39, 40, 41, 42, 61, 87} or (attr_type == 2 and formula not in {6, 7}):
                row['rdps_unresolved_static_multiplier_sources'].append({'item_id': item_id, 'slot': slot,
                    'attr_type': attr_type, 'modifier_type': formula, 'modify_attribute_type': target,
                    'reason': 'unmodeled_static_attribute_mechanism'})
                continue
            if target != 0 or attr_type not in {2, 17, 28, 32, 33, 50, 51, 52, 53, 54}:
                continue
            if (attr_type == 2 and formula not in {6, 7}) or (attr_type != 2 and formula != 5):
                continue
            index = modifier.get('attrIndex')
            raw_values = modifier.get('attrValues')
            values = [_coerce_optional_float(value) for value in raw_values] if isinstance(raw_values, list) else []
            candidates = levels.get(index, set())
            level = next(iter(candidates)) if len(candidates) == 1 else None
            value = None
            if values and all(v is not None for v in values) and type(index) is int:
                if len(candidates) == 1 and 0 <= level < len(values):
                    value = values[level]
                elif not candidates and len(set(values)) == 1:
                    # No level is invented: every legal level has this value.
                    value = values[0]
            if value is None or value < 0:
                row['rdps_unresolved_static_multiplier_sources'].append({'item_id': item_id,
                    'slot': slot, 'attr_index': index, 'attr_type': attr_type,
                    'reason': 'missing_or_conflicting_equipment_enhancement'})
                continue
            stats = equip.get('stats')
            if isinstance(stats, list) and type(index) is int and 0 <= index < len(stats):
                stat = stats[index]
                if isinstance(stat, dict) and stat.get('value') == 'unknown':
                    stat['value'] = value
                    stat['level'] = level
                    stat['value_source'] = 'official_EquipTable_attribute_zero_or_exact'
            if attr_type == 2 and formula == 7:
                baseline_attributes.append({'source_type': 'equip_baseline', 'source_id': item_id,
                    'source_slot': slot, 'attr_type': 2, 'attr_index': index, 'value': value,
                    'modifier_type': 7, 'modify_attribute_type': target, 'enhance_level': level,
                    'evidence_kind': 'official_EquipTable_flat_attack', 'source_table_sha256': proof})
                continue
            zone, element = _ATTR_TYPE_TO_EFFECT[attr_type]
            entries.append({'source_type': 'equip', 'source_name': str(meta.get('item_name') or item_id),
                'source_id': item_id, 'source_slot': slot, 'label': f'attribute_type_{attr_type}',
                'zone': zone, 'zone_label': _RDPS_DEBUG_ZONE_LABELS[zone], 'element': element,
                'rate': value, 'attr_type': attr_type, 'modifier_type': formula, 'attr_index': index,
                'enhance_level': level, 'skill_groups': [], 'condition_text': '',
                'evidence_kind': 'official_EquipTable_attribute', 'source_table_sha256': proof})

    row['equipment_baseline_attributes'] = baseline_attributes
    weapon_skills = row.get('weapon_source_skills') or row.get('weapon_refine_stats') or []
    weapon_meta = _load_weapon_catalog().get(str(row.get('weapon_template') or ''), {})
    declared_weapon_skills = set(weapon_meta.get('weapon_skill_ids') or [])
    basic_attack_skills = {'wpn_sp_attr_atk_high', 'wpn_sp_attr_atk_mid', 'wpn_sp_attr_atk_low'}
    attack_specs = {(key, 'atk'): 'BaseMultiplier' for key in basic_attack_skills & declared_weapon_skills}
    attack_specs.update({(field['skillId'], field['bbKey']): field['formulaItem']
                         for field in weapon_meta.get('static_attack_fields') or []})
    weapon_attack_values: dict[tuple[str, str], set[float | None]] = defaultdict(set)
    for skill in weapon_skills:
        if not isinstance(skill, dict):
            continue
        canonical_skill = _canonical_num_table_skill_number(str(skill.get('skill_id') or ''), None)
        if canonical_skill is None and skill.get('skill_id') in declared_weapon_skills:
            canonical_skill = skill['skill_id']
        for (skill_id, key), formula in attack_specs.items():
            if canonical_skill == skill_id:
                weapon_attack_values[(skill_id, key)].add(_coerce_optional_float((skill.get('bb') or {}).get(key)))
    for (skill_id, key), values in weapon_attack_values.items():
        value = next(iter(values)) if len(values) == 1 else None
        if value is None or value < 0:
            row['rdps_unresolved_static_multiplier_sources'].append({
                'reason': 'missing_or_conflicting_weapon_basic_attack', 'source_id': skill_id})
            continue
        if attack_specs[(skill_id, key)] == 'BaseFinalAddition':
            baseline_attributes.append({'source_type': 'weapon_skill', 'source_id': skill_id,
                'attr_type': 2, 'modifier_type': 7, 'modify_attribute_type': 0, 'value': value,
                'bb_key': key, 'evidence_kind': 'official_WeaponSkill_card_flat_attack'})
            continue
        entries.append({'source_type': 'weapon_skill', 'source_name': str(row.get('weapon_template') or ''),
            'source_id': skill_id, 'zone': 'atk', 'zone_label': _RDPS_DEBUG_ZONE_LABELS['atk'],
            'element': 'all', 'attr_type': 2, 'modifier_type': 6, 'bb_key': key, 'rate': value,
            'evidence_kind': 'official_WeaponSkill_text_basic_atk',
            'source_table_sha256': weapon_meta.get('weapon_definition_sha256'), 'condition_text': ''})
    try:
        damage_catalog = json.loads((_repo_root() / 'data/local_static/skill/item_damage_baseline_catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        damage_catalog = {}
    decoder = damage_catalog.get('decoder') if isinstance(damage_catalog, dict) else None
    if (not isinstance(damage_catalog, dict) or damage_catalog.get('schemaVersion') != 1
            or damage_catalog.get('source') != 'current_official_item_skill_card_attribute'
            or not isinstance(decoder, dict)
            or any(decoder.get(key) != value for key, value in _CURRENT_TYPED_RESOURCE_BINDING.items())):
        damage_catalog = {}
    damage_attributes = {
        'NormalAttackDamageIncrease': 17, 'UltimateSkillDamageIncrease': 28,
        'NormalSkillDamageIncrease': 32, 'ComboSkillDamageIncrease': 33,
        'PhysicalDamageIncrease': 50, 'FireDamageIncrease': 51,
        'PulseDamageIncrease': 52, 'CrystDamageIncrease': 53,
        'NaturalDamageIncrease': 54, 'EtherDamageIncrease': 55,
    }
    damage_static_keys: dict[str, set[str]] = defaultdict(set)
    reviewed_damage_suits: set[str] = set()
    for category, definitions in (('weapon', damage_catalog.get('weaponEntries') or []),
                                  ('suit', damage_catalog.get('suitEntries') or [])):
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            modifier = definition.get('modifier') or {}
            param = modifier.get('param') or {}
            attr_type = definition.get('attributeType')
            if (modifier.get('$type') != 'Beyond.Gameplay.AttributeModifierData.AttributeModifier'
                    or damage_attributes.get(modifier.get('attributeType')) != attr_type
                    or attr_type not in _ATTR_TYPE_TO_EFFECT
                    or modifier.get('modifyAttributeType') != 'Specific'
                    or param.get('useBlackboardKey') is not True
                    or param.get('blackboardKey') != definition.get('bbKey')
                    or not isinstance(definition.get('bbKey'), str) or not definition['bbKey']
                    or type(definition.get('attributeIndex')) is not int or definition['attributeIndex'] < 0
                    or type(definition.get('sourceBytes')) is not int or definition['sourceBytes'] <= 0
                    or definition.get('consumedBytes') != definition['sourceBytes']
                    or not re.fullmatch(r'[0-9a-f]{64}', str(definition.get('sourceSha256') or ''))
                    or _load_num_id_str_skill_map().get(str(definition.get('numericSkillId'))) != definition.get('skillId')):
                continue
            observations = []
            if category == 'weapon':
                declared_list = weapon_meta.get('weapon_skill_ids') or []
                bindings = [binding for binding in definition.get('weaponBindings') or []
                            if isinstance(binding, dict) and binding.get('weaponId') == row.get('weapon_template')
                            and type(binding.get('skillSlot')) is int and 0 <= binding['skillSlot'] < len(declared_list)
                            and declared_list[binding['skillSlot']] == definition['skillId']]
                if len(bindings) != 1:
                    continue
                damage_static_keys[definition['skillId']].add(definition['bbKey'])
                for skill in weapon_skills:
                    if not isinstance(skill, dict):
                        continue
                    skill_id = str(skill.get('skill_id') or '')
                    canonical = _load_num_id_str_skill_map().get(skill_id) if skill_id.isdigit() else skill_id
                    if canonical == definition['skillId'] and isinstance(skill.get('bb'), dict):
                        observations.append((str(row['weapon_template']), 'weapon_skill', skill['bb']))
            else:
                for effect in row.get('suit_effects') or []:
                    if (isinstance(effect, dict) and effect.get('suit_id') == definition.get('suitId')
                            and effect.get('active') is True and isinstance(effect.get('value'), dict)
                            and definition.get('requiredPieces') == 3 and definition.get('skillLevel') == 1):
                        observations.append((effect['suit_id'], 'equip_suit', effect['value']))
                        reviewed_damage_suits.add(effect['suit_id'])
            for item_id, source_type, bb in observations:
                value = _coerce_optional_float(bb.get(definition['bbKey']))
                if value is None or value < 0 or modifier.get('formulaItem') not in {'BaseAddition', 'Addition'}:
                    row['rdps_unresolved_static_multiplier_sources'].append({
                        'reason': ('missing_item_damage_baseline_value' if value is None or value < 0
                                   else 'unmodeled_item_damage_attribute_stage'),
                        'source_id': definition['skillId'], 'bb_key': definition['bbKey'],
                        'formula_item': modifier.get('formulaItem')})
                    continue
                zone, element = _ATTR_TYPE_TO_EFFECT[attr_type]
                entries.append({'source_type': source_type, 'source_name': item_id, 'item_id': item_id,
                    'source_id': definition['skillId'], 'attr_index': definition['attributeIndex'],
                    'zone': zone, 'zone_label': _RDPS_DEBUG_ZONE_LABELS[zone], 'element': element,
                    'attr_type': attr_type, 'modifier_type': {'BaseAddition': 5, 'Addition': 0}[modifier['formulaItem']],
                    'formula_item': modifier['formulaItem'], 'bb_key': definition['bbKey'], 'rate': value,
                    'source_resource_sha256': definition['sourceSha256'],
                    'evidence_kind': 'current_official_item_skill_card_attribute', 'condition_text': ''})

    suit_definitions = {
        'suit_expend_spell01': ({'atk_up'}, {'spell_dmg_up', 'duration', 'max_stack'}),
        'suit_atb01': ({'comboskill_cooldown'}, {'dmg_up', 'duration'}),
        'suit_heal01': ({'heal_up'}, {'dmg_taken_down', 'dmg_taken_down2', 'duration'}),
        'suit_combo_cd01': ({'comboskill_cooldown'}, {'spell_up', 'duration', 'max_stack'}),
        'suit_fire_natr01': ({'phy_spell_up'}, {'fire_dmg_up', 'nature_dmg_up', 'duration', 'duration2'}),
        'suit_usp02': ({'hp_up'}, {'dmg_up', 'duration'}),
    }
    suit_ids = {
        str(effect.get('suit_id') or '') for effect in row.get('suit_effects') or []
        if isinstance(effect, dict) and effect.get('suit_id')
    }
    for effect in row.get('suit_effects') or []:
        if not isinstance(effect, dict):
            continue
        suit_id = str(effect.get('suit_id') or '')
        values = effect.get('value')
        if suit_id not in suit_definitions:
            continue
        base_fields, trigger_fields = suit_definitions[suit_id]
        if not isinstance(values, dict) or not set(values).issubset(base_fields | trigger_fields):
            row['rdps_unresolved_static_multiplier_sources'].append({
                'reason': 'unmodeled_suit_static_semantics', 'suit_ids': [suit_id],
                'unknown_fields': sorted(set(values or {}) - base_fields - trigger_fields)
                if isinstance(values, dict) else [],
            })
            continue
        for field in base_fields:
            value = _coerce_optional_float(values.get(field))
            if value is not None and value >= 0:
                baseline_attributes.append({
                    'source_type': 'equip_suit_baseline', 'source_id': suit_id,
                    'field': field, 'value': value,
                    'evidence_kind': 'official_EquipSuit_text',
                })
    if suit_ids - set(suit_definitions) - reviewed_damage_suits:
        row['rdps_unresolved_static_multiplier_sources'].append({
            'reason': 'unmodeled_suit_static_semantics',
            'suit_ids': sorted(suit_ids - set(suit_definitions) - reviewed_damage_suits),
        })
    # Reviewed fields include card baselines and separately implemented trigger
    # parameters. Knowing a trigger's semantics does not make it a static bonus:
    # its Buff UID/lifetime still decides allocation. Scope every field to the
    # current weapon's declared skill identity, never to a shared BB name.
    basic_fields = {
        'wpn_sword_0006': {
            'wpn_attr_wisd_high': {'wisd'}, 'wpn_sp_attr_atk_high': {'atk'},
            'sk_wpn_sword_0006': {'fire_dmg_up', 'duration', 'normal_atk_up'},
        },
        'wpn_sword_0007': {
            'wpn_attr_wisd_mid': {'wisd'}, 'wpn_sp_attr_usgs_mid': {'usgs'},
            'sk_wpn_sword_0007': {'atk_up', 'phy_spell_up'},
        },
        'wpn_pistol_0012': {
            'wpn_attr_agi_mid': {'agi'}, 'wpn_sp_attr_usgs_mid': {'usgs'},
            'sk_wpn_pistol_0012': {'atk_up', 'duration', 'count', 'nature_dmg_up', 'nature_dmg_up_mult'},
        },
        'wpn_funnel_0008': {
            'wpn_attr_main_high': {'mainattr'},
            'wpn_sp_attr_phy_spell_high': {'physpell'},
            'sk_wpn_funnel_0008': {'second_attr_up', 'duration', 'lv', 'spell_damage_taken_up'},
        },
        'wpn_funnel_0013': {
            'wpn_attr_wisd_high': {'wisd'}, 'wpn_sp_attr_heal_high': {'heal'},
            'sk_wpn_funnel_0013': {'second_attr_up', 'duration', 'lv', 'spell_dmg_taken_up'},
        },
        'wpn_funnel_0017': {
            'wpn_attr_will_high': {'will'}, 'wpn_sp_attr_electrondam_high': {'electrondam'},
            'sk_wpn_funnel_0017': {'atk_up', 'duration', 'max_stack', 'pulse_dmg_up2'},
        },
        'wpn_sword_0012': {
            'wpn_attr_will_high': {'will'}, 'wpn_sp_attr_atk_high': {'atk'},
            'sk_wpn_sword_0012': {'atk_up', 'atk_up2', 'duration', 'max_stack', 'lv'},
        },
        'wpn_lance_0014': {
            'wpn_attr_will_high': {'will'}, 'wpn_sp_attr_heal_high': {'heal'},
            'sk_wpn_lance_0014': {'atk_up', 'duration', 'max_stack', 'primary_attr_up'},
        },
        'wpn_funnel_0004': {
            'wpn_attr_wisd_mid': {'wisd'}, 'wpn_sp_attr_electrondam_mid': {'electrondam'},
            'sk_wpn_funnel_0004': {'phy_spell_up', 'dmg_up', 'duration'},
        },
    }.get(str(row.get('weapon_template') or ''), {})
    weapon_trigger_keys = []
    for skill in weapon_skills:
        if not isinstance(skill, dict):
            continue
        canonical_skill = _canonical_num_table_skill_number(str(skill.get('skill_id') or ''), None)
        reviewed_fields = basic_fields.get(canonical_skill)
        if canonical_skill is None and skill.get('skill_id') in declared_weapon_skills:
            canonical_skill = skill['skill_id']
            reviewed_fields = basic_fields.get(canonical_skill)
        if canonical_skill not in declared_weapon_skills:
            reviewed_fields = None
        if (str(row.get('weapon_template') or '') == 'wpn_funnel_0008'
                and canonical_skill == 'wpn_sp_attr_phy_spell_high'
                and canonical_skill in declared_weapon_skills
                and _coerce_optional_float((skill.get('bb') or {}).get('atk')) == 0.0):
            # Current typed card modifies arts strength only; its exported zero
            # atk placeholder is inert. A nonzero/new field stays unresolved.
            reviewed_fields = set(reviewed_fields or []) | {'atk'}
        if canonical_skill in basic_attack_skills and canonical_skill in declared_weapon_skills:
            reviewed_fields = {'atk'}
        static_attack_keys = {key for skill_id, key in attack_specs if skill_id == canonical_skill}
        if static_attack_keys or damage_static_keys.get(canonical_skill):
            reviewed_fields = set(reviewed_fields or []) | static_attack_keys | damage_static_keys.get(canonical_skill, set())
        if reviewed_fields is None:
            weapon_trigger_keys.append('unreviewed_skill:' + str(skill.get('skill_id') or 'unknown'))
        for key in (skill.get('bb') or {}):
            if reviewed_fields is not None and key in reviewed_fields:
                continue
            weapon_trigger_keys.append(str(key))
    if weapon_trigger_keys:
        row['rdps_unresolved_static_multiplier_sources'].append({
            'reason': 'unmodeled_weapon_static_semantics',
            'weapon_template': row.get('weapon_template'),
            'weapon_source_skill_ids': [
                skill.get('skill_id') for skill in weapon_skills
                if isinstance(skill, dict) and skill.get('skill_id') is not None
            ],
            'trigger_blackboard_keys': sorted(set(weapon_trigger_keys)),
        })

    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    conflicting_sources: set[tuple[Any, ...]] = set()
    for entry in entries:
        if entry.get('evidence_kind') == 'official_EquipTable_attribute':
            deduped.append(entry)
            continue
        # Conditional entries should be represented by live packet buff windows;
        # adding them here would double count transient weapon/suit effects.
        if entry.get("condition_text"):
            continue
        source_id = str(entry.get('source_id') or '')
        source_id = _canonical_num_table_skill_number(source_id, None) or source_id
        key = (
            str(entry.get("source_type") or ""),
            str(entry.get("item_id") or ""),
            source_id,
            str(entry.get("attr_index") or ""),
            str(entry.get('bb_key') or ''),
            str(entry.get('attr_type') or ''),
            str(entry.get('modifier_type') or ''),
            str(entry.get("element") or ""),
            ",".join(entry.get("skill_groups") or []),
        )
        if key in conflicting_sources:
            continue
        if key in seen:
            if seen[key].get('rate') != entry.get('rate'):
                prior = seen.pop(key)
                deduped = [existing for existing in deduped if existing is not prior]
                conflicting_sources.add(key)
                row['rdps_unresolved_static_multiplier_sources'].append({
                    'reason': 'conflicting_static_multiplier_source', 'source_id': source_id,
                    'bb_key': entry.get('bb_key')})
            continue
        seen[key] = entry
        deduped.append(entry)
    return deduped



def _static_entry_applies_to_hit(entry: dict[str, Any], hit: dict[str, Any]) -> bool:
    zone = str(entry.get("zone") or "")
    if zone not in _RDPS_ALLOCATABLE_ZONES:
        return False
    rate = _safe_positive_rate(entry.get("rate"))
    if rate is None:
        return False
    if entry.get('evidence_kind') in {'official_EquipTable_attribute', 'official_WeaponSkill_text_basic',
                                    'current_official_item_skill_card_attribute'}:
        # Captured final attributes already contain equipment additions.
        # Preserve the typed evidence for display; do not add it twice.
        attr_type = entry.get('attr_type')
        baseline = hit.get('baseline') or {}
        if attr_type != 2 and (attr_type in baseline or str(attr_type) in baseline):
            observed = _coerce_optional_float(baseline.get(attr_type, baseline.get(str(attr_type))))
            if observed is not None:
                return False
            hit['rdps_unresolved_effect_conditions'] = True
        applies = _attr_type_applies_to_skill(attr_type, None,
            damage_decorate_mask=hit.get('damage_decorate_mask'),
            static_damage_decorate_mask=hit.get('static_damage_decorate_mask'),
            static_damage_decorate_mask_source=hit.get('static_damage_decorate_mask_source'))
        if applies is None:
            hit['rdps_unresolved_effect_conditions'] = True
        if applies is not True:
            return False
    if not _effect_applies_to_damage_element(
        str(entry.get("element") or "all"),
        hit.get("damage_element"),
        hit.get("damage_school"),
    ):
        return False

    skill_groups = {str(group or "") for group in entry.get("skill_groups") or [] if str(group or "")}
    if not skill_groups:
        return True
    masks = {'normal': 0x20484, 'skill': 0x100, 'combo': 0x2000, 'ultimate': 0x200}
    if not skill_groups.issubset(masks):
        hit['rdps_unresolved_effect_conditions'] = True
        return False
    failure = _effect_condition_failure({'condition': {'type': 'damage_decorate_mask',
        'check': 'HasAny', 'mask': sum(masks[group] for group in skill_groups)}}, hit)
    if failure is not None and failure.get('reason_group') == 'condition_unobservable':
        hit['rdps_unresolved_effect_conditions'] = True
    return failure is None
