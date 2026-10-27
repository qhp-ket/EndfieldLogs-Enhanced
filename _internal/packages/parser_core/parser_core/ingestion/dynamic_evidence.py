"""Observed dynamic parameters and attribute refresh snapshots."""
from __future__ import annotations

from typing import Any

from parser_core.effects.action_index import indexed_root_actions

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map
from parser_core.catalog.skill_damage import _load_skill_item_metadata
from parser_core.ingestion.fields import _coerce_optional_float, _coerce_optional_int, _extract_fields
from parser_core.ingestion.state import IngestionState
import copy
import json
import re


def consume_dynamic_observation(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if (" BB_MODIFY_DYNAMIC " in raw_line or " BUFF_ATTR_REFRESH " in raw_line
            or " BUFF_ATTR_REFRESH_UNRESOLVED " in raw_line):
        refresh_tag = (' BUFF_ATTR_REFRESH_UNRESOLVED ' if ' BUFF_ATTR_REFRESH_UNRESOLVED ' in raw_line
                       else ' BUFF_ATTR_REFRESH ')
        is_refresh = refresh_tag in raw_line
        fields = _extract_fields(raw_line.split(' identity=', 1)[0]) if not is_refresh else {}
        value = _coerce_optional_float(fields.get("value"))
        blackboard_key = None
        skill_key = fields.get("skill")
        action_id = _coerce_optional_int(fields.get("actionId"))
        root = _load_current_buff_roots().get(str(skill_key or ""))
        action_metadata: dict[str, Any] = {}
        if isinstance(root, dict) and action_id is not None:
            action_index = indexed_root_actions(root, ingestion.buff_root_action_indices)[1]
            matches = [node for node, _enabled in action_index.get(action_id, [])
                       if str(node.get('$type') or '').replace('+', '.')
                       == 'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data']
            if len(matches) == 1:
                node = matches[0]
                blackboard_key = str(node.get("key") or "") or None
                operand = node.get("value") or {}
                action_metadata = {
                    "blackboard_key_source": "typed_current_buff_action",
                    "operand_blackboard_key": (operand.get("blackboardKey")
                                               if operand.get("useBlackboardKey") is True else None),
                    "operation": node.get("operation"),
                }
            elif len(matches) > 1:
                action_metadata["mapping_error"] = "ambiguous_dynamic_action"
            else:
                action_metadata["mapping_error"] = "missing_dynamic_action"
        elif action_id is not None:
            skill_metadata = _load_skill_item_metadata(str(skill_key or ""))
            action_keys = skill_metadata.get("dynamic_action_keys") if isinstance(skill_metadata, dict) else None
            if isinstance(action_keys, dict):
                blackboard_key = action_keys.get(action_id)
                if blackboard_key is not None:
                    action_metadata["blackboard_key_source"] = "unversioned_skill_observation"
        event = {
            "line_no": line_no,
            "ts_ms": ts_ms,
            "seq": _coerce_optional_int(fields.get("seq")),
            "tick": _coerce_optional_int(fields.get("tick")),
            "instance_id": fields.get("inst"),
            "owner_id": fields.get("ownerId"),
            "owner": fields.get("owner"),
            "skill_key": skill_key,
            "action_id": action_id,
            "blackboard_key": blackboard_key,
            "value": value,
            **action_metadata,
        }
        (ingestion.buff_attribute_refresh_events if is_refresh else ingestion.dynamic_bb_events).append(event)
        # Legacy decoded packets kept exact Buff/owner/template/operation
        # identities before the later generation/oneof envelope existed.
        # Preserve that narrower evidence separately; do not fabricate the
        # missing envelope or let an invalid modern identity fall back to it.
        try:
            observation = json.loads(raw_line.split(refresh_tag if is_refresh else ' identity=', 1)[1])
            context = observation.get('eventContext')
            legacy = (isinstance(context, dict)
                      and all(observation.get(key) is None for key in
                              ('operationOwnerId', 'ownerId', 'environmentInstId', 'generation',
                               'templateType', 'templateIdCase', 'actionRuntimeCase', 'operationPayloadCase')))
            if legacy and str(context.get('owner_type')) == '1' and context.get('template_type') == 'Buff':
                legacy_uid = str(context.get('inst_id'))
                legacy_owner = str(context.get('owner_id'))
                legacy_seq = context.get('seq_id')
                legacy_action = observation.get('actionId')
                template_int = context.get('template_int_id')
                template_str = context.get('template_str_id')
                legacy_template = (_load_num_id_str_buff_map().get(str(template_int))
                                   if type(template_int) is int and not template_str else template_str)
                legacy_record = ingestion.active_buff_starts_by_uid.get(legacy_uid)
                creation_contexts = (legacy_record or {}).get('packet_creation_contexts') or []
                creation_sessions = {row['session_id'] for row in creation_contexts}
                if (legacy_template in {'buff_common_natural_natural_corrupt_do', 'buff_common_natural_cryst_triggered', 'buff_common_natural_fire_triggered'}
                        and type(observation.get('schemaVersion')) is int and observation['schemaVersion'] == 1
                        and type(legacy_seq) is int and legacy_seq >= 0
                        and type(legacy_action) is int and legacy_record is not None
                        and legacy_record.get('event_key') == legacy_template
                        and legacy_record.get('target_actor_id') == legacy_owner
                        and legacy_record.get('source_actor_id')
                        and all(re.fullmatch(r'[1-9]\d*', str(value)) and int(value) < 2**64
                                for value in (legacy_uid, legacy_owner, legacy_record.get('source_actor_id')))
                        and legacy_record.get('source_character_key')
                        and not legacy_record.get('rdps_live_identity_conflict')
                        and creation_sessions == {observation.get('sessionId')}
                        and all(legacy_seq > row['operation_seq'] for row in creation_contexts)
                        and observation.get('operationSeq') == legacy_seq
                        and observation.get('actionType') == (31 if is_refresh else 7)):
                    candidates = []; nodes = [(_load_current_buff_roots().get(legacy_template), True)]
                    while nodes:
                        item, enabled = nodes.pop()
                        if isinstance(item, dict):
                            enabled = enabled and ('serverActionIndex' not in item or item.get('isEnable') is True)
                            if item.get('serverActionIndex') == legacy_action:
                                candidates.append((item, enabled))
                            nodes.extend((value, enabled) for value in item.values())
                        elif isinstance(item, list):
                            nodes.extend((value, enabled) for value in item)
                    expected = ('Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data' if is_refresh else
                                'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data')
                    if (len(candidates) == 1 and candidates[0][1] is True
                            and candidates[0][0].get('$type') == expected):
                        keys = ('def_decrease', 'additional_def_decrease')
                        state = legacy_record.setdefault('_resistance_parameter_state', {
                            'values': {key: _coerce_optional_float((legacy_record.get('bb_values') or {}).get(key)) for key in keys},
                            'seen': {}, 'last_seq': -1, 'invalid': set()})
                        key = candidates[0][0].get('key')
                        if not is_refresh and key in keys:
                            if (fields.get('inst') == legacy_uid and fields.get('ownerId') == legacy_owner
                                    and skill_key == legacy_template and action_id == legacy_action
                                    and _coerce_optional_int(fields.get('seq')) == legacy_seq):
                                signature = (legacy_action, key, value)
                                if legacy_seq in state['seen']:
                                    if state['seen'][legacy_seq] != signature:
                                        state['invalid'].add(key)
                                        for saved in legacy_record.get('resistance_parameter_snapshots') or []:
                                            if saved['operation_seq'] >= legacy_seq:
                                                saved['status'] = 'conflicting_dynamic_operation'
                                elif legacy_seq < state['last_seq']:
                                    state['invalid'].add(key)
                                else:
                                    state['seen'][legacy_seq] = signature
                                    state['last_seq'] = legacy_seq
                                    state['values'][key] = value
                                    if value is None or value > 0:
                                        state['invalid'].add(key)
                                    else:
                                        state['invalid'].discard(key)
                        elif is_refresh:
                            complete = (not state['invalid'] and legacy_seq > state['last_seq']
                                        and all(state['values'].get(key) is not None and state['values'][key] <= 0 for key in keys))
                            saved = {'operation_seq': legacy_seq, 'line_no': line_no, 'ts_ms': ts_ms,
                                     'bb_values': dict(state['values']),
                                     'status': 'attribute_parameters_observed' if complete else 'missing_attribute_parameters',
                                     'identity_source': 'legacy_packet_uid_owner_template_sequence',
                                     'buff_uid': legacy_uid, 'owner_id': legacy_owner,
                                     'action_id': legacy_action, 'session_id': observation.get('sessionId')}
                            prior = legacy_record.setdefault('resistance_parameter_snapshots', [])
                            duplicate = [row for row in prior if row['operation_seq'] == legacy_seq]
                            if not duplicate:
                                prior.append(saved)
                            elif any(row['bb_values'] != saved['bb_values'] for row in duplicate):
                                for row in duplicate:
                                    row['status'] = 'conflicting_dynamic_operation'
        except (ValueError, TypeError, KeyError, IndexError):
            pass
        record = None
        identity = None
        identity_bound = False
        try:
            if is_refresh:
                identity_text = raw_line.split(refresh_tag, 1)[1]
            elif ' identity=' in raw_line:
                identity_text = raw_line.split(' identity=', 1)[1]
            else:
                raise ValueError('missing_dynamic_identity')
            pairs = json.loads(identity_text, object_pairs_hook=list)
            if not identity_text.startswith('{') or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                raise ValueError('dynamic_identity_not_object')
            identity = dict(pairs)
            if len(identity) != len(pairs):
                raise ValueError('duplicate_dynamic_identity_fields')
            event['identity'] = identity
            expected_type = 31 if is_refresh else 7
            runtime_case = 'refresh_buff_attr_modifier_value_action' if is_refresh else 'modify_dynamic_blackboard_action'
            uid = identity.get('environmentInstId')
            if (type(identity.get('schemaVersion')) is not int or identity['schemaVersion'] != 1
                    or type(identity.get('actionType')) is not int or identity['actionType'] != expected_type
                    or identity.get('actionRuntimeCase') != runtime_case
                    or identity.get('operationPayloadCase') != 'trigger_action_op_data'
                    or str(identity.get('ownerType')) != '1' or type(identity.get('ownerType')) not in (int, str)
                    or identity.get('templateType') != 'Buff'
                    or type(identity.get('triggerType')) is not int or identity['triggerType'] != 0
                    or not isinstance(identity.get('sessionId'), str) or not identity['sessionId']
                    or any(type(identity.get(key)) is not int or identity[key] < 0
                           for key in ('operationSeq', 'generation', 'actionId'))
                    or any(type(identity.get(key)) is not str or not re.fullmatch(r'[1-9]\d*', identity[key])
                           or int(identity[key]) >= 2**64 for key in ('environmentInstId', 'ownerId', 'operationOwnerId'))
                    or uid in {'0', '4294967295'} or identity['ownerId'] != identity['operationOwnerId']
                    or (is_refresh and identity.get('buffUid') != uid)):
                raise ValueError('invalid_dynamic_buff_identity')
            if (identity.get('templateIdCase') == 'int_id' and type(identity.get('templateIntId')) is int
                    and identity['templateIntId'] >= 0 and identity.get('templateStrId') is None):
                template = _load_num_id_str_buff_map().get(str(identity['templateIntId']))
            elif (identity.get('templateIdCase') == 'str_id' and isinstance(identity.get('templateStrId'), str)
                    and identity['templateStrId'] and identity.get('templateIntId') is None):
                template = identity['templateStrId']
            else:
                raise ValueError('invalid_dynamic_template_oneof')
            record = ingestion.active_buff_starts_by_uid.get(uid)
            if (record is None or record.get('rdps_live_identity_conflict') or record.get('rdps_dynamic_identity_conflict')
                    or template != record.get('event_key') or identity['ownerId'] != record.get('target_actor_id')):
                raise ValueError('unbound_dynamic_buff_instance')
            anchors = record.get('creation_observations') or []
            if (not anchors or any(row['sessionId'] != identity['sessionId'] for row in anchors)
                    or not any(row['operationSeq'] <= identity['operationSeq'] for row in anchors)):
                raise ValueError('missing_compatible_buff_creation_observation')
            if not is_refresh and (fields.get('inst') != uid or fields.get('ownerId') != identity['ownerId']
                    or action_id != identity['actionId'] or skill_key != template
                    or _coerce_optional_int(fields.get('seq')) != identity['operationSeq'] or value is None):
                raise ValueError('dynamic_text_identity_conflict')
            identity_bound = True
            root = _load_current_buff_roots().get(template)
            expected_action = ('Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data' if is_refresh else
                               'Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data')
            action_index = indexed_root_actions(root, ingestion.buff_root_action_indices)[1]
            matches = action_index.get(identity['actionId'], [])
            if len(matches) != 1 or matches[0][1] is not True or matches[0][0].get('$type') != expected_action:
                raise ValueError('dynamic_action_not_in_current_template')
            node = matches[0][0]
            for anchor in anchors:
                anchor['bb_observation_source'] = 'unverified_creation_bb'
                if (template not in {'buff_common_natural_natural_corrupt_do', 'buff_common_natural_cryst_triggered', 'buff_common_natural_fire_triggered'}
                        or (root.get('stackingSettings') or {}).get('stackingType') != 'Stack'
                        or anchor.get('sourceEvent') != 'BattleOpTriggerAction'
                        or anchor.get('creationActionType') != 'BattleActionCreateBuff'
                        or anchor.get('creationActionRuntimeCase') != 'create_buff_action'
                        or not isinstance(anchor.get('assignedItems'), list)):
                    continue
                origins = [origin for origin in record.get('origin_observations') or []
                           if origin.get('_boundCreateRecord') is True and origin.get('operationSeq') == anchor['operationSeq']
                           and origin.get('buffUid') == uid and origin.get('sourceActorId') == anchor.get('sourceActorId')
                           and origin.get('targetActorId') == anchor['targetActorId']]
                creator_signatures = set()
                valid_origins = bool(origins)
                for origin in origins:
                    if (str(origin.get('environmentType') or '').lower() != 'buff' or str(origin.get('ownerType')) != '1'
                            or origin.get('environmentInstId') in (None, '', '0', '4294967295')):
                        valid_origins = False
                        break
                    parent = origin.get('templateStrId')
                    if isinstance(parent, str) and parent and origin.get('templateIntId') is None:
                        pass
                    elif parent in (None, '') and type(origin.get('templateIntId')) is int and origin['templateIntId'] >= 0:
                        parent = _load_num_id_str_buff_map().get(str(origin['templateIntId']))
                    else:
                        valid_origins = False
                        break
                    creator_root = _load_current_buff_roots().get(parent)
                    action_index = indexed_root_actions(creator_root, ingestion.buff_root_action_indices)[1]
                    try:
                        creator_actions = action_index.get(origin.get('actionId'), [])
                    except TypeError:
                        creator_actions = []
                    if (len(creator_actions) != 1 or creator_actions[0][1] is not True
                            or creator_actions[0][0].get('$type') != 'Beyond.Gameplay.Core.CreateBuffAction.Data'):
                        valid_origins = False
                        break
                    creator_signatures.add((parent, origin['actionId'], origin.get('environmentInstId')))
                if valid_origins and len(creator_signatures) == 1:
                    anchor['bb_observation_source'] = 'typed_post_create_runtime_bb'
                    anchor['bb_observation_scope'] = 'current_default_corrosion_stack_path'
                    anchor_key = (anchor['sessionId'], anchor['operationOwnerId'], anchor.get('operationGeneration'), anchor['operationSeq'], uid)
                    if anchor_key in ingestion.buff_creation_operation_history:
                        ingestion.buff_creation_operation_history[anchor_key]['observation']['bb_observation_source'] = anchor['bb_observation_source']
                        ingestion.buff_creation_operation_history[anchor_key]['observation']['bb_observation_scope'] = anchor['bb_observation_scope']
            context = (identity['sessionId'], identity['operationOwnerId'], identity['generation'])
            state = record.get('_dynamic_pending_state')
            seen_contexts = record.setdefault('_dynamic_seen_contexts', set())
            if state is None:
                seeds = [row for row in anchors if row['operationSeq'] <= identity['operationSeq'] and row.get('bb_values')]
                newest_seq = max((row['operationSeq'] for row in seeds), default=-1)
                seeds = [row for row in seeds if row['operationSeq'] == newest_seq]
                seed_values = {}
                seed_sources = {}
                if (seeds and len({json.dumps(row['bb_values'], sort_keys=True) for row in seeds}) == 1
                        and all(row['operationOwnerId'] != context[1] or row.get('operationGeneration') == context[2] for row in seeds)):
                    seed_values = dict(seeds[0]['bb_values'])
                    seed = seeds[0]
                    seed_key = (seed['sessionId'], seed['operationOwnerId'], seed.get('operationGeneration'), seed['operationSeq'], uid)
                    seed_sources = {key: {'kind': 'creation_observation', 'creation_key': seed_key} for key in seed_values}
                state = {'context': context, 'values': seed_values,
                         'value_sources': seed_sources, 'last_seq': -1, 'operations': {},
                         'invalid_keys': set(record.get('_dynamic_unresolved_keys') or []) | {key for seed in seeds for key in seed.get('bb_conflicts') or []}}
                record['_dynamic_pending_state'] = state
            elif state['context'] != context:
                if context in seen_contexts:
                    raise ValueError('dynamic_context_reused_out_of_order')
                # generation belongs to the operation owner. A changed
                # message context is not a new Buff, nor permission to
                # combine updates from incompatible operation streams.
                state = {'context': context, 'values': {}, 'value_sources': {}, 'last_seq': -1,
                         'operations': {}, 'invalid_keys': set()}
                record['_dynamic_pending_state'] = state
            seen_contexts.add(context)
            seq = identity['operationSeq']
            key = str(node.get('key') or '') if not is_refresh else ''
            signature = (expected_type, identity['actionId'], key,
                         value.hex() if value is not None else None,
                         json.dumps(identity, sort_keys=True, ensure_ascii=False))
            if seq in state['operations'] and state['operations'][seq] == signature:
                event['state_status'] = 'duplicate_dynamic_observation'
                return True
            if seq < state['last_seq'] or (seq in state['operations'] and state['operations'][seq] != signature):
                if key:
                    state['values'].pop(key, None)
                    state['invalid_keys'].add(key)
                else:
                    state['invalid_keys'].add('*')
                for snapshot in record.get('attribute_refresh_snapshots') or []:
                    snapshot_identity = snapshot['identity']
                    if (snapshot_identity['sessionId'], snapshot_identity['operationOwnerId'], snapshot_identity['generation']) == context and snapshot['operation_seq'] >= seq:
                        snapshot['status'] = 'conflicting_dynamic_operation'
                        snapshot.setdefault('conflicting_operation_seqs', []).append(seq)
                raise ValueError('conflicting_dynamic_operation_order')
            duplicate = seq in state['operations']
            state['operations'][seq] = signature
            state['last_seq'] = seq
            if not is_refresh:
                if not key:
                    raise ValueError('missing_dynamic_target_key')
                # client_value is the result after AssignDynamic, including
                # Add/Sub operations. Assign it exactly once; never add it.
                state['values'][key] = value
                state['value_sources'][key] = {'kind': 'typed_runtime_post_assignment', 'operation_seq': seq,
                                              'session_id': context[0], 'operation_owner_id': context[1], 'generation': context[2]}
                state['invalid_keys'].discard(key)
                record.setdefault('_dynamic_unresolved_keys', set()).discard(key)
                event.update(blackboard_key=key, blackboard_key_source='typed_current_buff_action',
                             operation=node.get('operation'), state_status='pending_attribute_refresh',
                             instance_start_line_no=record['instance_start_line_no'])
            else:
                event.update(instance_id=uid, owner_id=identity['ownerId'], skill_key=template,
                             action_id=identity['actionId'], seq=seq, state_status='attribute_refresh_observed')
                parameters = []; missing = []; unverified = []
                attributes = (root.get('attributeModifier') or {}).get('attributeModifiers')
                if not isinstance(attributes, list):
                    raise ValueError('missing_current_attribute_modifiers')
                for index, modifier in enumerate(attributes):
                    param = modifier.get('param') or {}
                    bb_key = param.get('blackboardKey') if param.get('useBlackboardKey') is True else None
                    raw_value = (state['values'].get(bb_key) if bb_key is not None else param.get('value'))
                    operand = _coerce_optional_float(raw_value)
                    operand_source = state['value_sources'].get(bb_key, {'kind': 'unknown'}) if bb_key is not None else {'kind': 'typed_static_literal'}
                    if operand_source.get('kind') == 'creation_observation':
                        source_anchor = ingestion.buff_creation_operation_history.get(tuple(operand_source['creation_key']), {}).get('observation')
                        operand_source = {**operand_source, 'kind': source_anchor.get('bb_observation_source', 'unverified_creation_bb') if source_anchor else 'unverified_creation_bb'}
                    if operand is None or bb_key in state['invalid_keys'] or '*' in state['invalid_keys']:
                        missing.append(bb_key or f'attribute:{index}')
                    elif operand_source['kind'] not in {'typed_runtime_post_assignment', 'typed_post_create_runtime_bb', 'typed_static_literal'}:
                        unverified.append(bb_key or f'attribute:{index}')
                    parameters.append({'index': index, 'attribute_type': modifier.get('attributeType'),
                        'formula': modifier.get('formulaItem'), 'bb_key': bb_key, 'operand': operand, 'operand_source': operand_source})
                snapshot = {'ts_ms': ts_ms, 'line_no': line_no, 'operation_seq': seq,
                    'identity': copy.deepcopy(identity), 'bb_values': dict(state['values']),
                    'attribute_parameters': parameters, 'missing_parameters': sorted(set(missing)),
                    'unverified_parameters': sorted(set(unverified)),
                    'status': ('missing_attribute_parameters' if missing else 'unverified_attribute_parameters' if unverified else 'attribute_parameters_observed'),
                    'enhance_multiplier': None, 'final_modifiers_verified': False,
                    'instance_start_line_no': record['instance_start_line_no']}
                if not duplicate:
                    record.setdefault('attribute_refresh_snapshots', []).append(snapshot)
                event['snapshot_status'] = snapshot['status']
                # Keep the complete observation even if this Buff falls
                # outside the selected battle window. Share the object
                # so later conflicting evidence invalidates both views.
                event['snapshot'] = snapshot
        except (ValueError, TypeError, KeyError) as error:
            event['state_error'] = str(error)
            if not is_refresh and (identity_bound or identity is None):
                affected = ingestion.active_buff_starts_by_uid.get(str(fields.get('inst') or ''))
                if (affected is not None and fields.get('ownerId') == affected.get('target_actor_id')
                        and skill_key == affected.get('event_key')):
                    unknown_key = blackboard_key or '*'
                    affected.setdefault('_dynamic_unresolved_keys', set()).add(unknown_key)
                    affected_state = affected.get('_dynamic_pending_state')
                    if affected_state is not None:
                        affected_state['invalid_keys'].add(unknown_key)
            if is_refresh:
                ingestion.unresolved_buff_actions.append({'ts_ms': ts_ms, 'line_no': line_no,
                    'uid': event.get('instance_id'), 'reason': 'unbound_buff_attribute_refresh', 'detail': str(error)})
        return True
    return False
