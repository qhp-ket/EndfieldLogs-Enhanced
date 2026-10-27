"""Build static and dynamic effect specifications from approved observations."""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.packet_mapping import _packet_mapping_allows_static_rate
from parser_core.effects.packet_mapping import _packet_numeric_buff_hint
from parser_core.effects.registry import _RDPS_ALLOCATABLE_ZONES
from parser_core.effects.registry import _rdps_registry_known_non_rdps_entry
from parser_core.effects.registry import _rdps_registry_suppresses_zone_effects
from parser_core.effects.registry import _rdps_registry_verified_effect_entry
from parser_core.effects.registry import _rdps_registry_zone_effects
from parser_core.effects.semantic_conditions import _collect_semantic_condition_zone_effects
from parser_core.realtime.incremental import memoize_live_record
from parser_core.ingestion.fields import _coerce_optional_float
import copy
from typing import Any


@memoize_live_record
def _collect_zone_effects(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> list[dict[str, Any]]:
    if record.get('rdps_live_identity_conflict'):
        record['rdps_unresolved_semantic_condition'] = ['conflicting_live_buff_identity']
        return []
    buff_id = _normalize_buff_id(record.get("event_key"))
    verified_entry = _rdps_registry_verified_effect_entry(record, root_lookup_cache=root_lookup_cache)
    if verified_entry is None and _rdps_registry_known_non_rdps_entry(record) is not None:
        return []
    if verified_entry is None and _rdps_registry_suppresses_zone_effects(record):
        record.pop('rdps_unresolved_semantic_condition', None)
        return []
    if verified_entry is None:
        # Current typed effects can describe the attacker's own baseline;
        # they do not authorize external rDPS outside the approved whitelist.
        effects = _collect_semantic_condition_zone_effects(record, root_lookup_cache=root_lookup_cache)
        for effect in effects:
            effect['external_rdps_allowed'] = False
            effect['rdps_whitelist_keys'] = []
        if not effects and not record.get('rdps_unresolved_semantic_condition'):
            record['rdps_unresolved_semantic_condition'] = ['missing_verified_semantics']
        return effects
    effects = _rdps_registry_zone_effects(record, verified_entry)
    semantic_effects = _collect_semantic_condition_zone_effects(record, root_lookup_cache=root_lookup_cache)
    if record.get("rdps_unresolved_semantic_condition"):
        return []
    if effects and not semantic_effects:
        # A legacy registry effect without a corresponding current typed
        # modifier is not evidence that the effect exists in this build.
        record['rdps_unresolved_semantic_condition'] = ['missing_current_semantic_effect']
        return []
    verified_effects = []
    registry_specs_by_current_index: dict[int, list[dict[str, Any]]] = {}
    for effect in effects:
        matched = [(index, semantic) for index, semantic in enumerate(semantic_effects)
                   if effect.get('zone') == semantic.get('zone')
                   and str(semantic.get('bb_key') or '') in (effect.get('_registry_bb_keys')
                        or [str(effect.get('_registry_bb_key') or '')])]
        if matched:
            if any(semantic.get('rate') != effect.get('rate') for _, semantic in matched):
                record['rdps_unresolved_semantic_condition'] = ['conflicting_declared_rates']
                return []
            # The registry authorizes the effect; the current complete root
            # defines the actual branches/conditions, not a legacy name rule.
            for index, semantic in matched:
                registry_specs_by_current_index.setdefault(index, []).append(effect)
        else:
            record['rdps_unresolved_semantic_condition'] = ['registry_effect_not_in_current_typed_root']
            return []
    for index, declared_specs in registry_specs_by_current_index.items():
        approved = dict(semantic_effects[index])
        approved['external_rdps_allowed'] = True
        approved['rdps_whitelist_keys'] = list(verified_entry.get('_rdps_whitelist_keys') or [])
        if verified_entry.get('_keyword_origin'):
            approved['keyword_origin'] = copy.deepcopy(verified_entry['_keyword_origin'])
        alternatives = []
        for spec in declared_specs:
            terms = [copy.deepcopy(spec['condition'])] if 'condition' in spec else []
            element = spec.get('element', 'all')
            if element != 'all':
                terms.append({'type': 'damage_type_in', 'source': 'rdps_whitelist',
                              'elements': ['fire', 'pulse', 'cryst', 'natural'] if element == 'spell' else [element]})
            alternatives.append({'type': 'all', 'conditions': terms} if terms else {'type': 'always'})
        # A typed branch may match several approved element rows. Preserve
        # their union without crediting the branch more than once.
        if not any(branch.get('type') == 'always' for branch in alternatives):
            restriction = {'type': 'any', 'source': 'rdps_whitelist', 'conditions': alternatives}
            approved['condition'] = ({'type': 'all', 'source': 'typed_and_whitelist',
                                      'conditions': [approved['condition'], restriction]}
                                     if 'condition' in approved else restriction)
        verified_effects.append(approved)
    effects = verified_effects
    for effect in effects:
        effect.pop("_registry_bb_key", None)
    if verified_entry.get("dynamic"):
        return []
    return effects


@memoize_live_record
def _extract_dynamic_effect_specs(record: dict[str, Any], *, root_lookup_cache: dict | None = None) -> list[dict[str, Any]]:
    record.pop("rdps_unresolved_dynamic_effect", None)
    if record.get('rdps_live_identity_conflict'):
        record['rdps_unresolved_dynamic_effect'] = True
        return []
    entry = _rdps_registry_verified_effect_entry(record, root_lookup_cache=root_lookup_cache)
    if entry is None or not entry.get("dynamic") or record.get("packet_mapping_rejected"):
        return []
    if 'buff_chr_0023_antal_normal_fragile' in (entry.get('_rdps_whitelist_keys') or []):
        snapshots = record.get('keyword_rate_snapshots') or []
        if snapshots and entry.get('_keyword_origin'):
            base_record = dict(record)
            base_record.pop('keyword_rate_snapshots', None)
            effects = _collect_zone_effects(base_record, root_lookup_cache=root_lookup_cache)
            sessions = {row.get('session_id') for row in snapshots}
            if len(sessions) == 1 and None not in sessions and effects:
                return [{**effect, 'base_rate': effect['rate'],
                         'keyword_rate_snapshots': copy.deepcopy(snapshots),
                         'keyword_session_id': next(iter(sessions))}
                        for effect in effects]
        # A legacy parent label is not the live keyword effect. Current main
        # Buffs are authorized by their exact creation origin and observed rate.
        record['rdps_unresolved_dynamic_effect'] = True
        return []
    if record.get('event_key') in {'buff_common_natural_natural_corrupt_do', 'buff_common_natural_cryst_triggered', 'buff_common_natural_fire_triggered'}:
        snapshots = record.get('attribute_refresh_snapshots') or record.get('resistance_parameter_snapshots') or []
        if snapshots:
            root = _load_current_buff_roots().get(record['event_key']) or {}
            attributes = root.get('attributeModifier') or {}
            resistance_types = {'PhysicalResistance': 'physical', 'NaturalResistance': 'natural',
                                'CrystResistance': 'cryst', 'PulseResistance': 'pulse',
                                'FireResistance': 'fire', 'EtherResistance': 'ether'}
            keys_by_element: dict[str, list[str]] = defaultdict(list)
            approved_keys = {item.get('bb_key') for item in entry.get('effects') or [] if item.get('zone') == 'res'}
            for modifier in attributes.get('attributeModifiers') or []:
                element = resistance_types.get(modifier.get('attributeType'))
                if element is None:
                    continue
                param = modifier.get('param') or {}
                key = param.get('blackboardKey')
                if (modifier.get('formulaItem') != 'BaseAddition' or modifier.get('modifyAttributeType') != 'Specific'
                        or param.get('useBlackboardKey') is not True or key not in approved_keys):
                    record['rdps_unresolved_dynamic_effect'] = True
                    return []
                keys_by_element[element].append(key)
            if keys_by_element:
                return [{'zone': 'res', 'element': element, 'base_rate': 0.0,
                         'parameter_keys': keys, 'parameter_snapshots': copy.deepcopy(snapshots),
                         'external_rdps_allowed': True,
                         'rdps_whitelist_keys': list(entry.get('_rdps_whitelist_keys') or [])}
                        for element, keys in keys_by_element.items()]
    hint = record.get("packet_mapping")
    if not isinstance(hint, dict):
        hint = _packet_numeric_buff_hint(record.get("raw_event_key") or record.get("event_key"))
    specs = hint.get("dynamic_effects")
    if not isinstance(specs, list) or not specs:
        specs = entry.get("dynamic_effects")
    if not isinstance(specs, list) or not specs:
        record["rdps_unresolved_dynamic_effect"] = True
        return []
    bb_values = record.get("bb_values") or {}
    allow_constant = _packet_mapping_allows_static_rate(hint)
    effects = []
    for spec in specs:
        if not isinstance(spec, dict) or spec.get("zone") not in _RDPS_ALLOCATABLE_ZONES:
            record["rdps_unresolved_dynamic_effect"] = True
            return []
        element = spec.get("element")
        if element not in {"all", "physical", "spell", "fire", "pulse", "cryst", "natural"}:
            record["rdps_unresolved_dynamic_effect"] = True
            return []
        declared = [item for item in (entry.get('dynamic_effects') or entry.get('effects') or [])
                    if item.get('zone') == spec['zone'] and item.get('element', 'all') == element]
        if not declared:
            record['rdps_unresolved_dynamic_effect'] = True
            record['rdps_whitelist_rejection'] = 'dynamic_effect_not_declared'
            return []
        effect = {"zone": spec["zone"], "element": element}
        parameters = (("base_rate", "base_bb_key", "base_bb_keys", "bb_key"),
                      ("tick_rate", "tick_bb_key", "tick_bb_keys", "tick_bb_key"),
                      ("delayed_add_rate", "add_bb_key", "", "add_bb_key"),
                      ("delay_sec", "delay_bb_key", "", "delay_bb_key"),
                      ("max_rate", "max_bb_key", "", "max_bb_key"))
        for parameter, key_field, aliases_field, provenance in parameters:
            aliases = spec.get(aliases_field) if aliases_field else []
            if aliases is not None and not isinstance(aliases, list):
                record["rdps_unresolved_dynamic_effect"] = True
                return []
            keys = list(dict.fromkeys([str(key) for key in aliases or [] if key]))
            primary = spec.get(key_field) or (spec.get("bb_key") if parameter == "base_rate" else None)
            if primary and str(primary) not in keys:
                keys.insert(0, str(primary))
            values = [(key, _coerce_optional_float(bb_values[key])) for key in keys if key in bb_values]
            if str(spec.get("zone") or "") == "res":
                values = [(key, -value if value is not None and value < 0 else value)
                          for key, value in values]
            if values:
                if any(value is None or value < 0 for _, value in values) or len({value for _, value in values}) != 1:
                    record["rdps_unresolved_dynamic_effect"] = True
                    return []
                effect[parameter] = values[0][1]
                effect[provenance] = values[0][0]
            elif parameter in spec and allow_constant:
                value = _coerce_optional_float(spec[parameter])
                if value is None or value < 0:
                    record["rdps_unresolved_dynamic_effect"] = True
                    return []
                effect[parameter] = value
            elif keys or parameter in spec:
                record["rdps_unresolved_dynamic_effect"] = True
                return []
            else:
                # The declared formula has no such term: its additive identity is zero.
                effect[parameter] = 0.0
        multiplier = _coerce_optional_float(spec.get("tick_multiplier", 1))
        if multiplier is None or multiplier < 0 or not isfinite(effect["tick_rate"] * multiplier):
            record["rdps_unresolved_dynamic_effect"] = True
            return []
        effect["tick_rate"] *= multiplier
        declared_keys = {str(item[field]) for item in declared
                         for field in ('bb_key', 'base_bb_key', 'tick_bb_key', 'add_bb_key', 'delay_bb_key', 'max_bb_key')
                         if item.get(field)}
        declared_keys.update(str(key) for item in declared
                             for field in ('bb_keys', 'base_bb_keys', 'tick_bb_keys', 'required_bb_keys')
                             for key in item.get(field) or [])
        used_keys = {str(effect[field]) for field in ('bb_key', 'tick_bb_key', 'add_bb_key', 'delay_bb_key', 'max_bb_key')
                     if effect.get(field)}
        if not used_keys <= declared_keys:
            record['rdps_unresolved_dynamic_effect'] = True
            record['rdps_whitelist_rejection'] = 'dynamic_operand_not_declared'
            return []
        for parameter, _, _, provenance in parameters:
            if parameter in spec and not effect.get(provenance):
                if not any(_coerce_optional_float(item.get(parameter)) == effect[parameter]
                           for item in declared if parameter in item):
                    record['rdps_unresolved_dynamic_effect'] = True
                    record['rdps_whitelist_rejection'] = 'dynamic_literal_not_declared'
                    return []
        # Native ModifyDynamicBlackboard reports the destination key's value
        # after assignment. That result alone does not prove the attribute
        # modifier was refreshed; bind the typed key and explicit refresh
        # before using it. Never integrate the configured tick over time.
        if effect["tick_rate"] != 0.0 or effect["delayed_add_rate"] != 0.0:
            record["rdps_unresolved_dynamic_effect"] = True
            return []
        if spec.get("dynamic_key"):
            effect["dynamic_key"] = spec["dynamic_key"]
        if "condition" in spec:
            effect["condition"] = copy.deepcopy(spec["condition"])
        if all('condition' in item for item in declared):
            restriction = {'type': 'any', 'source': 'rdps_whitelist',
                           'conditions': [copy.deepcopy(item['condition']) for item in declared]}
            effect['condition'] = ({'type': 'all', 'conditions': [effect['condition'], restriction]}
                                   if 'condition' in effect else restriction)
        effect['external_rdps_allowed'] = True
        effect['rdps_whitelist_keys'] = list(entry.get('_rdps_whitelist_keys') or [])
        effects.append(effect)
    return effects
