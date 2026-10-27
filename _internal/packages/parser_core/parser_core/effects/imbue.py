"""Validate exact imbue resources and build their observed effect windows."""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map
from parser_core.effects.registry import _rdps_registry_verified_effect_entry
from parser_core.ingestion.fields import _coerce_optional_float
import copy
import json
import re
from typing import Any


def _build_special_combo_windows(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
    *,
    battle_end_ms: int,
) -> list[dict[str, Any]]:
    # The packet names the modifier on this exact hit. The two explicit
    # creation origins identify its provider; no nearby cast is selected.
    trigger_id = 'buff_common_affixes_combo_trigger'
    imbue_id = 'buff_common_affixes_skillimbue'
    modifier_id = 'buff_common_affixes_skillimbue_atk'
    roots = _load_current_buff_roots()
    if not all(isinstance(roots.get(key), dict) for key in (trigger_id, imbue_id, modifier_id)):
        return []
    for parent_id, action_id, child_id in ((trigger_id, 4, imbue_id), (imbue_id, 0, modifier_id)):
        actions = []; pending = [(roots[parent_id], True)]
        while pending:
            node, enabled = pending.pop()
            if isinstance(node, dict):
                enabled = enabled and ('serverActionIndex' not in node or node.get('isEnable') is True)
                if (node.get('$type') == 'Beyond.Gameplay.Core.CreateBuffAction.Data'
                        and type(node.get('serverActionIndex')) is int and node['serverActionIndex'] == action_id):
                    actions.append((node, enabled))
                pending.extend((value, enabled) for value in node.values())
            elif isinstance(node, list):
                pending.extend((value, enabled) for value in node)
        if len(actions) != 1 or actions[0][1] is not True:
            return []
        action = actions[0][0]
        created = action.get('buffs') or []
        if (len(created) != 1 or created[0].get('readIdFromBlackboard') is not False
                or created[0].get('buffId') != child_id or created[0].get('assignBlackboard') is not True
                or action.get('buffSource') != 'ActionSource'
                or (action.get('targetSettings') or {}).get('targetSource') != 'Owner'):
            return []
        assigned = [row for row in created[0].get('assignItems') or []
                    if isinstance(row, dict) and row.get('targetKey') == 'imbue_scale']
        if (len(assigned) != 1 or assigned[0].get('useDirectValue') is not False
                or assigned[0].get('inputValueKey') != 'imbue_scale'):
            return []
    groups = roots[modifier_id].get('damageModifier') or []
    if len(groups) != 1 or groups[0].get('enableSide') != 'Attacker':
        return []
    processors = groups[0].get('damageProcessors') or []
    if (len(processors) != 1 or processors[0].get('$type') != 'Beyond.Gameplay.Core.DamageScaleProcessor'
            or processors[0].get('side') != 'Attacker' or processors[0].get('zoneName') != 'ComboCalcZone'
            or (processors[0].get('addition') or {}).get('blackboardKey') != 'real_imbue_scale'
            or (processors[0].get('addition') or {}).get('useBlackboardKey') is not True):
        return []
    conditions = (groups[0].get('condition') or {}).get('actionData') or []
    if (len(conditions) != 3 or any(row.get('isEnable') is not True for row in conditions)
            or conditions[0].get('$type') != 'Beyond.Gameplay.Core.Conditions.CheckSkillCastId.Data'
            or conditions[1].get('$type') != 'Beyond.Gameplay.Core.Conditions.CheckDamageDecorateMask.Data'
            or conditions[1].get('checkType') != 'HasAny' or conditions[1].get('mask') != 0x300
            or conditions[2].get('$type') != 'Beyond.Gameplay.Core.IfElseAction.IfElseActionData'):
        return []
    branch = conditions[2]
    checks = (branch.get('conditionAction') or {}).get('actionData') or []
    succeeds = (branch.get('succeedActions') or {}).get('actionData') or []
    failures = (branch.get('failActions') or {}).get('actionData') or []
    if (len(checks) != 1 or len(succeeds) != 1 or len(failures) != 1
            or any(row.get('isEnable') is not True for row in (*checks, *succeeds, *failures))
            or checks[0].get('$type') != 'Beyond.Gameplay.Core.Conditions.CheckDamageDecorateMask.Data'
            or checks[0].get('checkType') != 'HasAny' or checks[0].get('mask') != 0x100
            or succeeds[0].get('$type') != 'Beyond.Gameplay.Core.SimpleCalcBBAction.Data'
            or succeeds[0].get('operation') != 'Multiply' or succeeds[0].get('key') != 'real_imbue_scale'
            or (succeeds[0].get('value1') or {}).get('useBlackboardKey') is not True
            or (succeeds[0].get('value1') or {}).get('blackboardKey') != 'imbue_scale'
            or (succeeds[0].get('value2') or {}).get('useBlackboardKey') is not False
            or failures[0].get('$type') != 'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data'
            or failures[0].get('operation') != 'Assign' or failures[0].get('directValue') is not True
            or failures[0].get('key') != 'real_imbue_scale'
            or (failures[0].get('value') or {}).get('useBlackboardKey') is not True
            or (failures[0].get('value') or {}).get('blackboardKey') != 'imbue_scale'):
        return []
    skill_factor = _coerce_optional_float(succeeds[0]['value2'].get('value'))
    if skill_factor is None or skill_factor <= 0:
        return []
    by_uid: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in buff_starts:
        if record.get('event_key') in {trigger_id, imbue_id, modifier_id}:
            by_uid[str(record.get('uid') or '')].append(record)
    windows = []
    for hit in hits:
        raw_handles = (hit.get('packet_modifier_handles') or {}).get('attacker') or []
        grouped_handles: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for handle in raw_handles:
            if isinstance(handle, dict) and str(handle.get('buff_inst_id') or '') in by_uid:
                grouped_handles[str(handle['buff_inst_id'])].append(handle)
        for uid, handles in grouped_handles.items():
            if not any(row.get('event_key') == modifier_id for row in by_uid[uid]):
                continue
            rejection = None
            session = hit.get('packet_session_id')
            seq = hit.get('packet_seq_id')
            stamp = (hit.get('ts_ms'), hit.get('line_no'))
            if (not isinstance(session, str) or not session or type(seq) is not int or seq < 0
                    or any(type(value) is not int for value in stamp) or stamp[1] <= 0):
                rejection = 'missing_combo_hit_identity'
            elif (any(type(row.get('index')) is not int or row['index'] != 0 for row in handles)
                  or len({json.dumps(row, sort_keys=True, ensure_ascii=False) for row in handles}) != 1):
                rejection = 'conflicting_combo_modifier_handle'
            mask = hit.get('damage_decorate_mask')
            scope_source = 'observed_damage_decorate_mask'
            if mask is None:
                mask = hit.get('static_damage_decorate_mask')
                scope_source = hit.get('static_damage_decorate_mask_source')
                if scope_source != 'current_typed_skill_or_buff_exact_unit_generation_only':
                    mask = None
            if type(mask) is not int or mask < 0 or not mask & 0x300:
                rejection = rejection or 'unresolved_or_inapplicable_combo_skill_scope'
            selected = []; chain = []; origins_used = []; anchors_used = []
            current_uid, expected_id, point = uid, modifier_id, stamp
            for parent_id, expected_action in ((imbue_id, 0), (trigger_id, 4), (None, None)):
                if rejection:
                    break
                candidates = []
                for record in by_uid.get(current_uid, []):
                    if record.get('event_key') != expected_id:
                        continue
                    start = (record.get('ts_ms', record.get('start_ts_ms')), record.get('line_no', 0))
                    if any(type(value) is not int for value in start) or point < start:
                        continue
                    cutoffs = [(record.get(name), record.get(line_name)) for name, line_name in (
                        ('end_ts_ms', 'end_line_no'), ('snapshot_end_ts_ms', 'snapshot_end_line_no'))]
                    if any(type(end) is int and (point[0] > end or point[0] == end
                           and type(line) is int and point[1] >= line) for end, line in cutoffs):
                        continue
                    candidates.append(record)
                if len(candidates) != 1:
                    rejection = 'ambiguous_or_missing_combo_instance'
                    break
                record = candidates[0]
                if (record.get('rdps_live_identity_conflict') or record.get('rdps_dynamic_identity_conflict')
                        or not record.get('source_character_key')
                        or record.get('target_actor_id') != hit.get('source_actor_id')
                        or record.get('target_character_key') != hit.get('character_key')
                        or any(type(record.get(key)) is not str or not re.fullmatch(r'[1-9]\d*', record[key])
                               or int(record[key]) >= 2**64 for key in ('uid', 'source_actor_id', 'target_actor_id'))
                        or chain and (record['source_actor_id'] != chain[0]['source_actor_id']
                                      or record['source_character_key'] != chain[0]['source_character_key'])):
                    rejection = 'conflicting_combo_provider_or_recipient'
                    break
                chain.append(record)
                if parent_id is None:
                    break
                origins = record.get('origin_observations') or []
                normalized_origins = []
                for origin in origins:
                    parent = origin.get('templateStrId')
                    if parent in (None, '') and type(origin.get('templateIntId')) is int:
                        parent = _load_num_id_str_buff_map().get(str(origin['templateIntId']))
                    elif not isinstance(parent, str) or not parent or origin.get('templateIntId') is not None:
                        parent = None
                    if (origin.get('_boundCreateRecord') is not True or parent != parent_id
                            or origin.get('buffUid') != current_uid or origin.get('buffTemplate') != expected_id
                            or origin.get('sourceActorId') != record['source_actor_id']
                            or origin.get('targetActorId') != record['target_actor_id']
                            or str(origin.get('environmentType') or '').lower() != 'buff'
                            or str(origin.get('ownerType')) != '1'
                            or type(origin.get('actionId')) is not int or origin['actionId'] != expected_action
                            or origin.get('triggerType') != 0 or type(origin.get('operationSeq')) is not int
                            or type(origin.get('environmentInstId')) is not str
                            or not re.fullmatch(r'[1-9]\d*', origin['environmentInstId'])):
                        rejection = 'invalid_combo_creation_origin'
                        break
                    normalized_origins.append(origin)
                parent_uids = {row['environmentInstId'] for row in normalized_origins}
                if rejection or not normalized_origins or len(parent_uids) != 1:
                    rejection = rejection or 'missing_or_conflicting_combo_creation_origin'
                    break
                anchors = [row for row in record.get('creation_observations') or []
                           if row.get('sessionId') == session and row.get('buffUid') == current_uid
                           and row.get('buffTemplate') == expected_id and row.get('sourceActorId') == record['source_actor_id']
                           and row.get('targetActorId') == record['target_actor_id']
                           and row.get('sourceEvent') == 'BattleOpTriggerAction'
                           and type(row.get('operationSeq')) is int and row['operationSeq'] <= seq
                           and any(row['operationSeq'] == origin['operationSeq'] for origin in normalized_origins)]
                if not anchors or any(not isinstance(row.get('assignedItems'), list) for row in anchors):
                    rejection = 'missing_combo_creation_parameters'
                    break
                rates = set()
                for anchor in anchors:
                    values = [row for row in anchor['assignedItems'] if isinstance(row, dict) and row.get('target_key') == 'imbue_scale']
                    if (not values or any(row.get('use_direct_value') is not True or row.get('string_value')
                                          or _coerce_optional_float(row.get('numeric_value')) is None for row in values)
                            or 'imbue_scale' in (anchor.get('bb_conflicts') or []) or '*' in (anchor.get('bb_conflicts') or [])):
                        rejection = 'invalid_combo_creation_rate'
                        break
                    rates.update(float(row['numeric_value']) for row in values)
                if rejection or len(rates) != 1 or next(iter(rates)) <= 0:
                    rejection = rejection or 'conflicting_combo_creation_rate'
                    break
                selected.append(next(iter(rates)))
                points = {(row.get('ts_ms'), row.get('line_no')) for row in anchors}
                if len(points) != 1 or any(type(value) is not int for value in next(iter(points))):
                    rejection = 'ambiguous_combo_creation_boundary'
                    break
                point = next(iter(points))
                current_uid, expected_id = next(iter(parent_uids)), parent_id
                origins_used.extend(normalized_origins)
                anchors_used.extend(anchors)
            if not rejection and (len(chain) != 3 or len(selected) != 2 or selected[0] != selected[1]):
                rejection = 'combo_forwarded_rate_conflict'
            if not rejection:
                states = chain[0].get('enable_observations') or []
                prior = [row for row in states if type(row.get('operationSeq')) is int and row['operationSeq'] <= seq]
                if prior:
                    latest = max(row['operationSeq'] for row in prior)
                    enabled = {row.get('enabled') for row in prior if row['operationSeq'] == latest}
                    if enabled != {True}:
                        rejection = 'disabled_or_conflicting_combo_modifier'
                elif chain[0].get('rdps_conflicting_enable_state'):
                    rejection = 'disabled_or_conflicting_combo_modifier'
            if rejection:
                hit['rdps_unresolved_effect_conditions'] = True
                hit.setdefault('combo_unresolved_reasons', []).append({'uid': uid, 'reason': rejection})
                continue
            projection_key = f'{trigger_id}::packet/{session}/{seq}/{stamp[1]}'
            approval = _rdps_registry_verified_effect_entry({'event_key': projection_key,
                'source_character_key': chain[0]['source_character_key'], 'target_character_key': hit['character_key']})
            if (not approval or not approval.get('_rdps_whitelist_keys')
                    or not any(row.get('zone') == 'combo' and row.get('element') == 'all' for row in approval.get('effects') or [])):
                continue
            rate = selected[0] * (skill_factor if mask & 0x100 else 1.0)
            if not isfinite(rate) or rate <= 0:
                continue
            windows.append({'uid': uid, 'start_ts_ms': stamp[0], 'end_ts_ms': stamp[0],
                'start_line_no': stamp[1], 'end_line_no': stamp[1] + 1, 'line_no': stamp[1],
                'snapshot_update': True, 'snapshot_end_ts_ms': stamp[0], 'snapshot_end_line_no': stamp[1] + 1,
                'duration_ms': 1, 'stacking_type': (roots[modifier_id].get('stackingSettings') or {}).get('stackingType'),
                'stack_limit': None, 'source_character_key': chain[0]['source_character_key'],
                'source_character_name': chain[0].get('source_character_name'), 'source_actor_id': chain[0]['source_actor_id'],
                'target_character_key': hit['character_key'], 'target_character_name': hit.get('character_name') or hit['character_key'],
                'target_actor_id': hit['source_actor_id'],
                'target_player_key': hit['character_key'], 'target_enemy_key': None,
                'event_key': projection_key, 'event_name': '连击增伤', 'skill_family_key': None,
                'zone_effects': [{'zone': 'combo', 'element': 'all', 'rate': rate,
                                  'external_rdps_allowed': True, 'rdps_whitelist_keys': list(approval['_rdps_whitelist_keys'])}],
                'combo_rate_model': 'exact_packet_modifier_and_creation_chain', 'combo_imbue_scale': selected[0],
                'combo_skill_scope_mask': mask & 0x300, 'combo_skill_scope_source': scope_source,
                'combo_source_uids': [row['uid'] for row in reversed(chain)],
                'combo_origins': copy.deepcopy(origins_used), 'combo_creation_observations': copy.deepcopy(anchors_used),
                'combo_hit_identity': {'sessionId': session, 'operationSeq': seq, 'lineNo': stamp[1],
                                       'targetActorId': hit.get('target_actor_id'), 'damageUnitIndex': hit.get('damage_unit_index')}})
    return windows
