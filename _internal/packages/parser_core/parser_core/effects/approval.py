"""Exact whitelist identities and observed source/recipient approval guards."""
from __future__ import annotations

from parser_core.effects.action_index import indexed_root_actions

from parser_core.catalog import packet_semantics as _packet_catalog
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.names import _load_num_id_str_skill_map
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map, _load_rdps_semantics_registry
from parser_core.catalog.resources import _NATIVE_DAMAGE_SEMANTICS_BINDING
from parser_core.effects.damage_types import _normalize_effect_element
import copy
import json
import re
from typing import Any


def _record_bb_key_set(record: dict[str, Any]) -> set[str]:
    keys = {str(key) for key in record.get("bb_keys") or [] if str(key)}
    keys.update(str(key) for key in (record.get("bb_values") or {}).keys() if str(key))
    return keys


def _rdps_registry_bb_keys_allowed(entry: dict[str, Any], record: dict[str, Any]) -> bool:
    allowed_values = entry.get("allowed_bb_keys")
    if not isinstance(allowed_values, list):
        return True
    allowed = {str(key).lower() for key in allowed_values}
    if "*" in allowed:
        return True
    observed = {key.lower() for key in _record_bb_key_set(record)}
    return observed.issubset(allowed)


def _rdps_registry_entry_matches_guard(entry: dict[str, Any], record: dict[str, Any]) -> bool:
    guard = entry.get("guard")
    if not isinstance(guard, dict):
        return True

    source_key = str(record.get("source_character_key") or "")
    target_key = str(record.get("target_character_key") or "")
    packet_mapping = record.get("packet_mapping") if isinstance(record.get("packet_mapping"), dict) else {}
    if guard.get('requires_actor_identity') is True:
        if (not source_key or any(type(record.get(key)) is not str
                or not re.fullmatch(r'[1-9]\d*', record[key]) or int(record[key]) >= 2**64
                for key in ('uid', 'source_actor_id', 'target_actor_id'))
                or record.get('uid') == '4294967295'):
            return False
    if guard.get('target_kind') == 'enemy':
        enemy = record.get('target_enemy_key')
        if not enemy or target_key not in ('', enemy) or record.get('target_player_key'):
            return False
    if guard.get('target_kind') == 'character' and (not target_key or record.get('target_enemy_key')):
        return False
    if guard.get('recipient') == 'self':
        if not source_key or target_key != source_key:
            return False
        source_actor, target_actor = record.get('source_actor_id'), record.get('target_actor_id')
        if (source_actor or target_actor) and (not source_actor or not target_actor or str(source_actor) != str(target_actor)):
            return False
    if guard.get('recipient') == 'other_character':
        if not source_key or not target_key or source_key == target_key:
            return False
        source_actor, target_actor = record.get('source_actor_id'), record.get('target_actor_id')
        if (source_actor or target_actor) and (not source_actor or not target_actor or str(source_actor) == str(target_actor)):
            return False

    source_guard = str(guard.get("source_character_key") or guard.get("source_character_id") or "")
    if source_guard and source_key != source_guard:
        return False

    character_guard = str(guard.get("character_id") or "")
    if character_guard and character_guard not in {source_key, target_key}:
        return False

    source_skill = str(record.get("source_skill_key") or "")
    source_skill_family = str(record.get("source_skill_family_key") or source_skill)
    skill_guard = str(guard.get("source_skill_key") or "")
    if skill_guard and source_skill != skill_guard:
        return False
    family_guard = str(guard.get("source_skill_family_key") or "")
    if family_guard and source_skill_family != family_guard:
        return False

    weapon_guard = str(guard.get("weapon_id") or "")
    if weapon_guard:
        # New equipment approvals require the loadout observed at this Buff
        # instance's creation. A template name or later roster cannot supply it.
        if (guard.get('requires_source_loadout') is True
                and record.get('source_weapon_template') != weapon_guard):
            return False
        mapping_weapon = str(packet_mapping.get("weapon_id") or "")
        event_key = _normalize_buff_id(record.get("event_key"))
        raw_event_key = _normalize_buff_id(record.get("raw_event_key"))
        event_matches_weapon = event_key.startswith(f"buff_{weapon_guard}") or raw_event_key.startswith(f"buff_{weapon_guard}")
        if mapping_weapon and mapping_weapon != weapon_guard:
            return False
        if not mapping_weapon and not event_matches_weapon:
            return False

    suit_guard = str(guard.get("suit_id") or "")
    if suit_guard:
        mapping_suit = str(packet_mapping.get("suit_id") or "")
        if mapping_suit and mapping_suit != suit_guard:
            return False

    return True


def _rdps_registry_matching_effect_entry(record: dict[str, Any], *, require_guard: bool,
                                         root_lookup_cache: dict | None = None) -> dict[str, Any] | None:
    registry = _load_rdps_semantics_registry()
    verified = registry.get("verified_effects") if isinstance(registry.get("verified_effects"), dict) else {}
    candidates = {
        _normalize_buff_id(record.get("event_key")),
        _normalize_buff_id(record.get("raw_event_key")),
    }
    candidates.discard("")
    raw_numeric = _normalize_buff_id(record.get("raw_event_key"))

    # A current creation action may forward an approved field under a different
    # child key. The reviewed action/recipient contract, not the child name,
    # grants that existing approval to the actual packet instance.
    actual_candidates = {_load_num_id_str_buff_map().get(key, key) if key.isdigit() else key for key in candidates}
    index = _packet_catalog._RDPS_VERIFIED_INDEX
    indexed = index is not None and index[0] is registry and index[1] is verified
    runtime_keys = set().union(*(index[3].get(key, set()) for key in actual_candidates)) if indexed else None
    runtime_entries = verified.items() if runtime_keys is None else (
        (key, verified[key]) for key in sorted(runtime_keys, key=index[4].__getitem__)
    )
    for approval_key, entry in runtime_entries:
        if not isinstance(entry, dict):
            continue
        for binding in entry.get('runtime_bindings') or []:
            if binding.get('template') not in actual_candidates:
                continue
            if (binding.get('decoder') != _NATIVE_DAMAGE_SEMANTICS_BINDING
                    or not re.fullmatch(r'[0-9a-f]{64}', str(binding.get('sourceRootSha256') or ''))
                    or require_guard and not _rdps_registry_entry_matches_guard(entry, record)):
                continue
            origins = record.get('origin_observations') or []
            valid = bool(origins)
            for origin in origins:
                parent = origin.get('templateStrId')
                if parent in (None, '') and type(origin.get('templateIntId')) is int:
                    parent = (_load_num_id_str_skill_map() if binding.get('parent_kind') == 'Skill'
                              else _load_num_id_str_buff_map()).get(str(origin['templateIntId']))
                elif not isinstance(parent, str) or not parent or origin.get('templateIntId') is not None:
                    parent = None
                if (origin.get('_boundCreateRecord') is not True
                        or str(origin.get('environmentType') or '').lower() != str(binding.get('parent_kind') or '').lower()
                        or parent != binding.get('parent_template')
                        or type(origin.get('actionId')) is not int or origin['actionId'] not in binding.get('create_actions', [])
                        or origin.get('triggerType') != 0
                        or origin.get('buffUid') != record.get('uid')
                        or origin.get('buffTemplate') not in candidates | actual_candidates
                        or origin.get('sourceActorId') != record.get('source_actor_id')
                        or origin.get('targetActorId') != record.get('target_actor_id')
                        or any(not re.fullmatch(r'[1-9]\d*', str(origin.get(key) or ''))
                               or int(origin[key]) >= 2**64 for key in ('buffUid', 'sourceActorId', 'targetActorId'))
                        or binding.get('recipient') == 'other_character' and origin['sourceActorId'] == origin['targetActorId']):
                    valid = False
                    break
            if valid:
                remap = binding.get('bb_key_remap') or {}
                effects = [{**effect, 'bb_key': remap.get(effect.get('bb_key'), effect.get('bb_key'))}
                           for effect in entry.get('effects') or []]
                return {**entry, 'effects': effects, '_rdps_whitelist_keys': [approval_key],
                        '_runtime_binding': copy.deepcopy(binding)}

    exact_matches: list[dict[str, Any]] = []
    exact_keys: list[str] = []
    indexed_exact_keys = set().union(*(index[2].get(key, set()) for key in candidates)) if indexed else None
    exact_entries = verified.items() if indexed_exact_keys is None else (
        (key, verified[key]) for key in sorted(indexed_exact_keys, key=index[4].__getitem__)
    )
    for canonical_buff_id, entry in exact_entries:
        if not isinstance(entry, dict):
            continue
        aliases = {str(value) for value in entry.get("aliases") or [] if str(value)}
        numeric_ids = {str(value) for value in entry.get("numeric_ids") or [] if str(value)}
        if not (
            str(canonical_buff_id) in candidates
            or bool(candidates & aliases)
            or (raw_numeric and raw_numeric in numeric_ids)
        ):
            continue
        if require_guard and not _rdps_registry_entry_matches_guard(entry, record):
            continue
        exact_matches.append(entry)
        exact_keys.append(str(canonical_buff_id))
    if exact_matches:
        actual = _normalize_buff_id(record.get('event_key'))
        actual = _load_num_id_str_buff_map().get(actual, actual) if actual.isdigit() else actual
        lifecycle_approvals = {
            'buff_chr_0023_antal_tageffect': 'buff_chr_0023_antal_normal_fragile',
            'buff_common_natural_natural_corrupt_triggered': 'buff_chr_0025_ardelia_dynamic_def_decrease',
        }
        lifecycle_key = lifecycle_approvals.get(actual)
        if (lifecycle_key is None and len(exact_keys) == 1
                and verified[exact_keys[0]].get('lifecycle_only') is True):
            lifecycle_key = exact_keys[0]
        if lifecycle_key in exact_keys:
            root = _load_current_buff_roots().get(actual)
            if (isinstance(root, dict) and (root.get('attributeModifier') or {}).get('attributeModifiers') == []
                    and root.get('damageModifier') == [] and root.get('globalModifier') == []):
                entry = verified[lifecycle_key]
                return {**entry, 'dynamic': False, 'effects': [], 'dynamic_effects': [],
                        'ignored_bb_keys': sorted(set(entry.get('ignored_bb_keys') or [])
                                                  | _rdps_registry_effect_bb_keys(entry)),
                        '_rdps_whitelist_keys': [lifecycle_key], '_rdps_lifecycle_only': True}
        # The character approval and the generic corrosion approval describe
        # the same current Buff, not two independently stacked contributions.
        corrosion_key = 'buff_common_natural_natural_corrupt_do'
        ardelia_key = 'buff_chr_0025_ardelia_dynamic_def_decrease'
        if (actual == corrosion_key and set(exact_keys) == {corrosion_key, ardelia_key}
                and verified[corrosion_key].get('effects') == verified[ardelia_key].get('effects')
                and corrosion_key in (verified[ardelia_key].get('aliases') or [])):
            return {**verified[corrosion_key], '_rdps_whitelist_keys': sorted(exact_keys)}
        signatures = {
            json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for entry in exact_matches
        }
        return {**exact_matches[0], '_rdps_whitelist_keys': sorted(exact_keys)} if len(signatures) == 1 else None

    prefixes = registry.get("verified_prefixes") if isinstance(registry.get("verified_prefixes"), list) else []
    prefix_matches: list[dict[str, Any]] = []
    for key in candidates:
        if not key:
            continue
        for entry in prefixes:
            if not isinstance(entry, dict):
                continue
            prefix = str(entry.get("prefix") or "")
            if not prefix or not key.startswith(prefix):
                continue
            if require_guard and not _rdps_registry_entry_matches_guard(entry, record):
                continue
            if _rdps_registry_bb_keys_allowed(entry, record):
                prefix_matches.append(entry)
    if prefix_matches:
        signatures = {
            json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for entry in prefix_matches
        }
        return {**prefix_matches[0], '_rdps_whitelist_keys': sorted({str(row['prefix']) for row in prefix_matches})} if len(signatures) == 1 else None
    origins = record.get('origin_observations')
    keyword_map = registry.get('_keyword_buff_map')
    if isinstance(origins, list) and origins and isinstance(keyword_map, dict):
        projected = []
        for origin in origins:
            if (not isinstance(origin, dict) or origin.get('_boundCreateRecord') is not True
                    or origin.get('buffTemplate') not in {record.get('event_key'), record.get('raw_event_key')}
                    or any(type(origin.get(key)) is not str or not re.fullmatch(r'[1-9]\d*', origin[key])
                           or int(origin[key]) >= 2**64
                           for key in ('buffUid', 'sourceActorId', 'targetActorId', 'environmentInstId'))
                    or origin.get('buffUid') != record.get('uid')
                    or origin.get('sourceActorId') != record.get('source_actor_id')
                    or origin.get('targetActorId') != record.get('target_actor_id')
                    or str(origin.get('environmentType') or '').lower() != 'buff'
                    or str(origin.get('ownerType') or '') != '1'
                    or origin.get('environmentInstId') in (None, '', '0', '4294967295')
                    or type(origin.get('actionId')) is not int or origin['actionId'] < 0):
                return None
            actual_main = _normalize_buff_id(record.get('event_key'))
            for identity in (record.get('raw_event_key'), origin.get('buffTemplate')):
                if identity in (None, ''):
                    continue
                template = _normalize_buff_id(identity)
                if template.isdigit():
                    template = _load_num_id_str_buff_map().get(template)
                if template and template != actual_main:
                    return None
                if identity and not template:
                    return None
            parent = origin.get('templateStrId')
            numeric = origin.get('templateIntId')
            if isinstance(parent, str) and parent and numeric is None:
                parent = _normalize_buff_id(parent)
            elif parent in (None, '') and type(numeric) is int and numeric >= 0:
                parent = _load_num_id_str_buff_map().get(str(numeric))
            else:
                return None
            parent_entries = [(key, value) for key, value in verified.items()
                              if isinstance(value, dict) and (key == parent or parent in (value.get('aliases') or []))
                              and (not require_guard or _rdps_registry_entry_matches_guard(value, record))]
            parent_signatures = {json.dumps(value, sort_keys=True, ensure_ascii=False) for _, value in parent_entries}
            if len(parent_signatures) > 1:
                return None
            entry = parent_entries[0][1] if parent_entries else None
            parent_approval_keys = sorted(key for key, _ in parent_entries)
            root = _load_current_buff_roots().get(parent)
            if not isinstance(root, dict):
                return None
            if root_lookup_cache is None:
                actions = []; pending = [(root, True)]
                while pending:
                    value, ancestors_enabled = pending.pop()
                    if isinstance(value, dict):
                        enabled = ancestors_enabled and ('serverActionIndex' not in value or value.get('isEnable') is True)
                        if (value.get('$type') in {'Beyond.Gameplay.Core.VulnerableAction.Data', 'Beyond.Gameplay.Core.EnhancedAction.Data'}
                                and type(value.get('serverActionIndex')) is int
                                and value['serverActionIndex'] == origin['actionId']):
                            actions.append((value, enabled))
                        pending.extend((item, enabled) for item in value.values())
                    elif isinstance(value, list):
                        pending.extend((item, ancestors_enabled) for item in value)
            else:
                cached_lookup = indexed_root_actions(root, root_lookup_cache)
                actions = [(value, enabled) for value, enabled in cached_lookup[1].get(origin['actionId'], [])
                           if value.get('$type') in {'Beyond.Gameplay.Core.VulnerableAction.Data',
                                                     'Beyond.Gameplay.Core.EnhancedAction.Data'}]
            if len(actions) != 1 or actions[0][1] is not True:
                return None
            action = actions[0][0]
            kind = {'Beyond.Gameplay.Core.VulnerableAction.Data': 'Vulnerable',
                    'Beyond.Gameplay.Core.EnhancedAction.Data': 'Enhanced'}[action['$type']]
            child = (keyword_map.get(kind) or {}).get(action.get('subType'))
            if not child or child != _normalize_buff_id(record.get('event_key')):
                return None
            rate_config = action.get('rate') or {}
            if (rate_config.get('useBlackboardKey') is not True
                    or not isinstance(rate_config.get('blackboardKey'), str) or not rate_config['blackboardKey']):
                return None
            approval_key = parent_approval_keys[0] if parent_approval_keys else parent
            parent_approval = isinstance(entry, dict)
            if not isinstance(entry, dict):
                # Some historical approvals name the visual child. Resolve
                # the native keyword main -> explicitly selected child path;
                # neither naming conventions nor a visual rate create credit.
                main_root = _load_current_buff_roots().get(child)
                if not isinstance(main_root, dict):
                    return None
                child_config = action.get('childBuffId') or {}
                if (action.get('overrideChildBuffId') is True
                        and child_config.get('useBlackboardKey') is False):
                    visual_child = child_config.get('value')
                elif action.get('overrideChildBuffId') is False:
                    defaults = [row for row in main_root.get('blackboard') or []
                                if isinstance(row, dict) and row.get('key') == 'child_buff_id']
                    if len(defaults) != 1 or defaults[0].get('isDynamic') is not False:
                        return None
                    visual_child = defaults[0].get('valueStr')
                else:
                    return None
                if not isinstance(visual_child, str) or not visual_child:
                    return None
                entry = verified.get(visual_child)
                visual_root = _load_current_buff_roots().get(visual_child)
                if not isinstance(entry, dict) or not isinstance(visual_root, dict):
                    return None
                attributes = visual_root.get('attributeModifier')
                if (not isinstance(attributes, dict) or attributes.get('attributeModifiers') != []
                        or visual_root.get('damageModifier') != [] or visual_root.get('globalModifier') != []):
                    return None
                forwards = []
                if root_lookup_cache is None:
                    pending = [(main_root, True)]
                    while pending:
                        value, ancestors_enabled = pending.pop()
                        if isinstance(value, dict):
                            enabled = ancestors_enabled and ('serverActionIndex' not in value or value.get('isEnable') is True)
                            if value.get('$type') == 'Beyond.Gameplay.Core.CreateBuffAction.Data':
                                for created in value.get('buffs') or []:
                                    if (created.get('readIdFromBlackboard') is True
                                            and created.get('buffIdKey') == 'child_buff_id'):
                                        forwards.append((created, enabled))
                            pending.extend((item, enabled) for item in value.values())
                        elif isinstance(value, list):
                            pending.extend((item, ancestors_enabled) for item in value)
                else:
                    cached_lookup = indexed_root_actions(main_root, root_lookup_cache)
                    for value, enabled in cached_lookup[2]:
                        for created in value.get('buffs') or []:
                            if (created.get('readIdFromBlackboard') is True
                                    and created.get('buffIdKey') == 'child_buff_id'):
                                forwards.append((created, enabled))
                if len(forwards) != 1 or forwards[0][1] is not True or forwards[0][0].get('assignBlackboard') is not True:
                    return None
                assignments = forwards[0][0].get('assignItems') or []
                for key in ('rate', 'duration'):
                    assigned = [row for row in assignments if isinstance(row, dict) and row.get('targetKey') == key]
                    if (len(assigned) != 1 or assigned[0].get('useDirectValue') is not False
                            or assigned[0].get('inputValueKey') != key):
                        return None
                approval_key = visual_child
                expected_zone = {'Vulnerable': 'fragile', 'Enhanced': 'amp'}[kind]
                expected_element = {'All': 'all', 'Spell': 'spell', 'Physical': 'physical', 'Natural': 'natural',
                                    'Fire': 'fire', 'Crystal': 'cryst', 'Pulse': 'pulse'}.get(action.get('subType'))
                if any(spec.get('zone') != expected_zone or _normalize_effect_element(spec.get('element')) != expected_element
                       for spec in entry.get('effects') or []):
                    return None
            if require_guard and not _rdps_registry_entry_matches_guard(entry, record):
                return None
            if (parent == 'buff_chr_0023_antal_tageffect'
                    and parent_approval_keys == ['buff_chr_0023_antal_normal_fragile']):
                # The actual keyword Buff reports its current rate. It already
                # includes any enhancement applied during creation; later op15
                # observations update that same rate, never a guessed timer.
                entry = {**entry, 'dynamic': bool(record.get('keyword_rate_snapshots')),
                         'effects': [{'zone': 'fragile', 'element': element, 'bb_key': 'rate'}
                                     for element in ('pulse', 'fire')]}
            specs = entry.get('effects') or []
            # A reviewed parent input alias only authorizes the exact typed
            # origin; it must never become a fallback rate on the parent.
            # The actual keyword main Buff still must expose its own rate.
            if not specs or any((parent_approval and rate_config.get('blackboardKey') not in {spec.get('bb_key'), *(spec.get('bb_keys') or []), *(spec.get('origin_bb_keys') or [])})
                                or 'rate' not in {spec.get('bb_key'), *(spec.get('bb_keys') or [])}
                                for spec in specs):
                return None
            projected.extend((key, entry) for key in (parent_approval_keys if parent_approval else [approval_key]))
        signatures = {json.dumps(entry, sort_keys=True, ensure_ascii=False) for _, entry in projected}
        if len(signatures) == 1:
            return {**projected[0][1], '_rdps_whitelist_keys': sorted({key for key, _ in projected}),
                    '_keyword_origin': copy.deepcopy(origins)}
    return None


def _rdps_registry_effect_bb_keys(entry: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for effect in entry.get("effects") or []:
        if not isinstance(effect, dict):
            continue
        for field in ("bb_key", "add_bb_key", "delay_bb_key", "max_bb_key"):
            value = str(effect.get(field) or "")
            if value:
                keys.add(value)
        keys.update(str(value) for value in effect.get("bb_keys") or [] if str(value))
        keys.update(str(value) for value in effect.get("required_bb_keys") or [] if str(value))
    return keys


def _normalize_buff_id(buff_id: str | None) -> str:
    return str(buff_id or "unknown_buff")
