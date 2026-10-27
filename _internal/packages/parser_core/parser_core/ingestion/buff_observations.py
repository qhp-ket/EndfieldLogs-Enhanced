"""Observed keyword state, enable state and typed creation evidence."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map
from parser_core.effects.approval import _rdps_registry_matching_effect_entry
from parser_core.ingestion.fields import _coerce_optional_float, _extract_fields
from parser_core.ingestion.state import IngestionState
import json
import re

from parser_core.effects.enemy_status import _apply_enemy_status_bb_overrides
from parser_core.effects.packet_mapping import _preserve_raw_numeric_internal_trigger_buff_id


def consume_buff_observation(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " BUFF_ACTION_UNRESOLVED " in raw_line:
        fields = _extract_fields(raw_line)
        ingestion.unresolved_buff_actions.append({
            'uid': fields.get('uid'), 'seq': fields.get('seq'),
            'ts_ms': ts_ms, 'line_no': line_no,
            'trigger_type': fields.get('triggerType'), 'action_id': fields.get('actionId'),
            'target_actor_id': fields.get('ownerId'), 'source_actor_id': fields.get('srcId'),
            'reason': 'unresolved_buff_action_phase',
        })
        return True

    if " BUFF_KEYWORD_UPDATE " in raw_line or " BUFF_KEYWORD_UPDATE_UNRESOLVED " in raw_line:
        keyword_record = None
        keyword_bound = False
        keyword_observation = {}
        try:
            tag = (' BUFF_KEYWORD_UPDATE_UNRESOLVED ' if ' BUFF_KEYWORD_UPDATE_UNRESOLVED ' in raw_line
                   else ' BUFF_KEYWORD_UPDATE ')
            encoded = raw_line.split(tag, 1)[1]
            pairs = json.loads(encoded, object_pairs_hook=list)
            if (not encoded.startswith('{') or not isinstance(pairs, list)
                    or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs)):
                raise ValueError('invalid_keyword_observation')
            keyword_observation = dict(pairs)
            if len(keyword_observation) != len(pairs):
                raise ValueError('duplicate_keyword_fields')
            uid = keyword_observation.get('buffUid')
            owner = keyword_observation.get('ownerId')
            session = keyword_observation.get('sessionId')
            seq = keyword_observation.get('operationSeq')
            generation = keyword_observation.get('generation')
            added = keyword_observation.get('addedBuffNumId')
            keyword_record = ingestion.active_buff_starts_by_uid.get(uid) if isinstance(uid, str) else None
            if (keyword_observation.get('schemaVersion') != 1
                    or type(keyword_observation.get('schemaVersion')) is not int
                    or keyword_observation.get('operationPayloadCase') != 'trigger_keyword_op_data'
                    or keyword_record is None or keyword_record.get('rdps_live_identity_conflict')
                    or not isinstance(session, str) or not session
                    or type(seq) is not int or seq < 0
                    or type(generation) is not int or not 0 <= generation < 2**32
                    or type(added) is not int or added < 0
                    or any(not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value)
                           or int(value) >= 2**64 for value in (uid, owner))
                    or keyword_record.get('target_actor_id') != owner
                    or (ts_ms, line_no) < (keyword_record['ts_ms'], keyword_record['line_no'])):
                raise ValueError('unbound_keyword_identity')
            anchors = keyword_record.get('creation_observations') or []
            if (not any(anchor.get('sessionId') == session for anchor in anchors)
                    or any(anchor.get('sessionId') not in (None, session) for anchor in anchors)):
                raise ValueError('keyword_creation_session_mismatch')
            if any(anchor.get('sessionId') == session and anchor.get('operationSeq', -1) >= seq
                   for anchor in anchors if anchor.get('line_no', 0) >= keyword_record['line_no']):
                raise ValueError('keyword_update_before_creation')
            approved = _rdps_registry_matching_effect_entry(keyword_record, require_guard=True,
                                                              root_lookup_cache=ingestion.buff_root_action_indices)
            if (not approved or approved.get('_rdps_whitelist_keys') != ['buff_chr_0023_antal_normal_fragile']
                    or not approved.get('_keyword_origin')):
                raise ValueError('keyword_update_without_approved_origin')
            keyword_bound = True
            raw_rows = keyword_observation.get('modify')
            normalized_rows = []
            for raw_row in raw_rows if isinstance(raw_rows, list) else []:
                normalized_rows.append(dict(raw_row) if isinstance(raw_row, list)
                                       and all(isinstance(pair, tuple) and len(pair) == 2 for pair in raw_row)
                                       else raw_row)
            signature = (generation, added, json.dumps(normalized_rows if isinstance(raw_rows, list) else raw_rows,
                                                      sort_keys=True, ensure_ascii=False))
            seen = keyword_record.setdefault('_keyword_seen_updates', {})
            snapshots = keyword_record.setdefault('keyword_rate_snapshots', [])
            if seq in seen:
                if seen[seq] != signature:
                    for previous in snapshots:
                        if previous['operation_seq'] == seq:
                            previous['status'] = 'conflicting_keyword_update'
                    raise ValueError('conflicting_keyword_update')
                return True
            seen[seq] = signature
            if keyword_observation.get('validationErrors'):
                raise ValueError('unresolved_keyword_packet_fields')
            if not isinstance(raw_rows, list) or len(raw_rows) != 1:
                raise ValueError('invalid_keyword_modify_rows')
            row_pairs = raw_rows[0]
            if (not isinstance(row_pairs, list)
                    or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in row_pairs)):
                raise ValueError('invalid_keyword_modify_row')
            row = dict(row_pairs)
            if len(row) != len(row_pairs) or type(row.get('configIndex')) is not int or row['configIndex'] != 0:
                raise ValueError('invalid_keyword_config_index')
            rate = row.get('rateAfter')
            if type(rate) not in (int, float) or _coerce_optional_float(rate) is None or rate < 0:
                raise ValueError('invalid_keyword_rate')
            added_id = _load_num_id_str_buff_map().get(str(added))
            parent_root = _load_current_buff_roots().get('buff_chr_0023_antal_tageffect') or {}
            for origin in approved['_keyword_origin']:
                selected = []; pending = [parent_root]
                while pending:
                    node = pending.pop()
                    if isinstance(node, dict):
                        if (node.get('$type') == 'Beyond.Gameplay.Core.VulnerableAction.Data'
                                and node.get('serverActionIndex') == origin['actionId']):
                            selected.append(node)
                        pending.extend(node.values())
                    elif isinstance(node, list):
                        pending.extend(node)
                enhancing = selected[0].get('enhancingList') if len(selected) == 1 else None
                if (not isinstance(enhancing, list) or len(enhancing) != 1
                        or enhancing[0].get('operationType') != 'Add'
                        or (enhancing[0].get('value') or {}).get('useBlackboardKey') is not True
                        or (enhancing[0].get('value') or {}).get('blackboardKey') != 'potential_5_rate'
                        or added_id not in (enhancing[0].get('buffIds') or [])):
                    raise ValueError('keyword_marker_not_in_current_config')
            snapshots.append({'operation_seq': seq, 'line_no': line_no, 'ts_ms': ts_ms,
                              'session_id': session, 'generation': generation,
                              'rate_after': float(rate), 'status': 'observed',
                              'added_buff_id': added_id, 'config_index': row['configIndex']})
        except (ValueError, TypeError, KeyError, IndexError) as error:
            if keyword_bound and keyword_record is not None:
                snapshots = keyword_record.setdefault('keyword_rate_snapshots', [])
                if not any(row['operation_seq'] == keyword_observation['operationSeq'] for row in snapshots):
                    snapshots.append({'operation_seq': keyword_observation['operationSeq'], 'line_no': line_no,
                                      'ts_ms': ts_ms, 'session_id': keyword_observation['sessionId'],
                                      'generation': keyword_observation['generation'], 'rate_after': None,
                                      'status': 'unresolved_keyword_update'})
            ingestion.unresolved_buff_actions.append({'ts_ms': ts_ms, 'line_no': line_no,
                                            'reason': str(error), 'source': 'BUFF_KEYWORD_UPDATE'})
        return True

    if " BUFF_ENABLE " in raw_line:
        try:
            state_text = raw_line.split(' BUFF_ENABLE ', 1)[1]
            pairs = json.loads(state_text, object_pairs_hook=list)
            if not state_text.startswith('{') or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                raise ValueError('state_not_object')
            state = dict(pairs)
            if len(state) != len(pairs):
                raise ValueError('duplicate_state_fields')
            uid = state.get('buffUid')
            record = ingestion.active_buff_starts_by_uid.get(uid) if isinstance(uid, str) else None
            if (type(state.get('schemaVersion')) is not int or state['schemaVersion'] != 1
                    or type(state.get('enabled')) is not bool or record is None
                    or type(state.get('ownerId')) is not str or state['ownerId'] != record.get('target_actor_id')
                    or type(state.get('operationSeq')) is not int or state['operationSeq'] < 0):
                raise ValueError('unbound_buff_enable_state')
            previous = record.setdefault('enable_observations', [])
            if any(row['operationSeq'] == state['operationSeq'] and row['enabled'] != state['enabled'] for row in previous):
                record['rdps_conflicting_enable_state'] = True
                ingestion.unresolved_buff_actions.append({'uid': uid, 'ts_ms': ts_ms, 'line_no': line_no,
                                               'reason': 'conflicting_buff_enable_state'})
            previous.append({**state, 'ts_ms': ts_ms, 'line_no': line_no})
        except (ValueError, TypeError, KeyError):
            ingestion.unresolved_buff_actions.append({'ts_ms': ts_ms, 'line_no': line_no, 'reason': 'unbound_buff_enable_state'})
        return True

    if " BUFF_CREATE_OBSERVED " in raw_line:
        try:
            blob = raw_line.split(' BUFF_CREATE_OBSERVED ', 1)[1]
            pairs = json.loads(blob, object_pairs_hook=list)
            if not blob.startswith('{') or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                raise ValueError('creation_not_object')
            observation = dict(pairs)
            if len(observation) != len(pairs):
                raise ValueError('duplicate_creation_fields')
            uid = observation.get('buffUid')
            record = ingestion.active_buff_starts_by_uid.get(uid) if isinstance(uid, str) else None
            template = observation.get('buffTemplate')
            if isinstance(template, str) and template.isdigit():
                template = _load_num_id_str_buff_map().get(template)
            reported_templates = []
            number = observation.get('buffNumId')
            if number not in (None, 0):
                if type(number) is not int or number < 0:
                    raise ValueError('invalid_creation_numeric_template')
                reported_templates.append(_load_num_id_str_buff_map().get(str(number)))
            elif type(number) is bool:
                raise ValueError('invalid_creation_numeric_template')
            literal = observation.get('buffId')
            if literal not in (None, ''):
                if not isinstance(literal, str):
                    raise ValueError('invalid_creation_string_template')
                reported_templates.append(literal)
            template_pairs = observation.get('buffTemplateId')
            if template_pairs is not None:
                if (not isinstance(template_pairs, list)
                        or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in template_pairs)):
                    raise ValueError('invalid_creation_template_object')
                template_object = dict(template_pairs)
                if len(template_object) != len(template_pairs):
                    raise ValueError('duplicate_creation_template_fields')
                observation['buffTemplateId'] = template_object
                choices = [key for key in ('int_id', 'str_id') if key in template_object]
                if (len(choices) != 1 or type(template_object.get('type')) not in (int, str)
                        or template_object['type'] not in (1, 'Buff')):
                    raise ValueError('invalid_creation_template_oneof')
                if choices[0] == 'int_id':
                    number = template_object['int_id']
                    if type(number) is not int or number < 0:
                        raise ValueError('invalid_creation_numeric_template')
                    reported_templates.append(_load_num_id_str_buff_map().get(str(number)))
                else:
                    literal = template_object['str_id']
                    if not isinstance(literal, str) or not literal:
                        raise ValueError('invalid_creation_string_template')
                    reported_templates.append(literal)
            if not reported_templates or any(value != template for value in reported_templates):
                raise ValueError('creation_template_evidence_conflict')
            if (record is not None and template == record.get('event_key')
                    and observation.get('sourceEvent') == 'BattleOpTriggerAction'
                    and observation.get('sourceActorId') == record.get('source_actor_id')
                    and observation.get('targetActorId') == record.get('target_actor_id')
                    and isinstance(observation.get('sessionId'), str) and observation['sessionId']
                    and type(observation.get('operationSeq')) is int and observation['operationSeq'] >= 0):
                context = {'session_id': observation['sessionId'], 'operation_seq': observation['operationSeq']}
                contexts = record.setdefault('packet_creation_contexts', [])
                if context not in contexts:
                    contexts.append(context)
            if (type(observation.get('schemaVersion')) is not int or observation['schemaVersion'] != 1
                    or record is None or template != record.get('event_key')
                    or observation.get('sourceEvent') not in {'BattleOpTriggerAction', 'BattleOpAddBuff'}
                    or not isinstance(observation.get('sessionId'), str) or not observation['sessionId']
                    or type(observation.get('operationSeq')) is not int or observation['operationSeq'] < 0
                    or observation.get('generationScope') != 'operation_owner'
                    or any(type(observation.get(key)) is not str or not re.fullmatch(r'[1-9]\d*', observation[key])
                           or int(observation[key]) >= 2**64 for key in ('buffUid', 'targetActorId', 'operationOwnerId'))
                    or uid in {'0', '4294967295'}
                    or observation['targetActorId'] != record.get('target_actor_id')
                    or (record.get('source_actor_id') and observation.get('sourceActorId') != record['source_actor_id'])):
                raise ValueError('unbound_buff_creation_observation')
            previous = record.setdefault('creation_observations', [])
            observed_values = dict(record.get('_observed_bb_values') or {})
            bb_conflicts = set()
            assigned = observation.get('assignedItems')
            if isinstance(assigned, list):
                decoded_items = []
                observed_values = {}
                for item_pairs in assigned:
                    if (not isinstance(item_pairs, list)
                            or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in item_pairs)):
                        bb_conflicts.add('*')
                        continue
                    item = dict(item_pairs)
                    if len(item) != len(item_pairs):
                        bb_conflicts.add('*')
                        continue
                    decoded_items.append(item)
                    key = item.get('target_key')
                    operand = item.get('numeric_value')
                    if not isinstance(key, str) or not key:
                        bb_conflicts.add('*')
                        continue
                    if (item.get('use_direct_value') is not True or type(operand) not in (int, float)
                            or _coerce_optional_float(operand) is None):
                        bb_conflicts.add(key)
                        continue
                    operand = float(operand)
                    if key in observed_values and observed_values[key].hex() != operand.hex():
                        bb_conflicts.add(key)
                    observed_values[key] = operand
                observation['assignedItems'] = decoded_items
                for key in bb_conflicts:
                    observed_values.pop(key, None)
                if '*' in bb_conflicts:
                    observed_values = {}
            creation_key = (observation['sessionId'], observation['operationOwnerId'],
                            observation.get('operationGeneration'), observation['operationSeq'], uid)
            historical_creation = ingestion.buff_creation_operation_history.get(creation_key)
            same_operations = [historical_creation['observation']] if historical_creation is not None else []
            pending_state = record.get('_dynamic_pending_state')
            comparable_anchors = [row for row in previous if
                (row['sessionId'], row['operationOwnerId'], row.get('operationGeneration')) == creation_key[:3]]
            stale = any(row['operationSeq'] > observation['operationSeq'] for row in comparable_anchors)
            if (pending_state is not None and pending_state['context'] == creation_key[:3]
                    and observation['operationSeq'] < pending_state['last_seq']):
                stale = True
            conflicting = any(observed_values and row.get('bb_values') and row['bb_values'] != observed_values for row in same_operations)
            if same_operations or stale:
                prior_record = record.get('_previous_snapshot_record')
                incoming_record = record
                if prior_record is not None:
                    for key, old_value in record['_previous_snapshot_boundary'].items():
                        if old_value is None:
                            prior_record.pop(key, None)
                        else:
                            prior_record[key] = old_value
                    ingestion.active_buff_starts_by_uid[uid] = prior_record
                    ingestion.pending_buff_record = prior_record
                    record = prior_record
                elif historical_creation is not None and historical_creation['instance_start_line_no'] != record['instance_start_line_no']:
                    ingestion.active_buff_starts_by_uid.pop(uid, None)
                    ingestion.pending_buff_record = None
                    record = historical_creation['record']
                if record is not incoming_record:
                    ingestion.buff_starts = [row for row in ingestion.buff_starts if row is not incoming_record]
                record.setdefault('repeated_creation_observations', []).append({
                    **observation, 'ts_ms': ts_ms, 'line_no': line_no, 'bb_values': observed_values,
                    'status': 'conflicting' if conflicting else 'duplicate' if same_operations else 'out_of_order'})
                if conflicting:
                    affected_record = historical_creation['record'] if historical_creation is not None else record
                    affected_record.setdefault('_dynamic_unresolved_keys', set()).add('*')
                    if affected_record.get('_dynamic_pending_state') is not None:
                        affected_record['_dynamic_pending_state']['invalid_keys'].add('*')
                    for snapshot in affected_record.get('attribute_refresh_snapshots') or []:
                        if snapshot['operation_seq'] >= observation['operationSeq']:
                            snapshot['status'] = 'conflicting_creation_parameters'
                return True
            if any(row['sessionId'] != observation['sessionId'] for row in previous):
                record['rdps_dynamic_identity_conflict'] = True
                raise ValueError('conflicting_buff_creation_session')
            accepted = {**observation, 'ts_ms': ts_ms, 'line_no': line_no, 'bb_values': observed_values,
                        'bb_conflicts': sorted(bb_conflicts), 'bb_observation_source': 'unverified_creation_bb'}
            previous.append(accepted)
            ingestion.buff_creation_operation_history[creation_key] = {
                'observation': accepted, 'record': record, 'instance_start_line_no': record['instance_start_line_no']}
            record['_observed_bb_values'] = {}
            if pending_state is not None:
                context = pending_state['context']
                same_owner_wrong_generation = (observation['operationOwnerId'] == context[1]
                                                and observation.get('operationGeneration') != context[2])
                if not same_owner_wrong_generation:
                    pending_state['values'].update(observed_values)
                    pending_state['invalid_keys'].difference_update(observed_values)
                    record.setdefault('_dynamic_unresolved_keys', set()).difference_update(observed_values)
                    pending_state['invalid_keys'].update(bb_conflicts)
                    for key in observed_values:
                        pending_state['value_sources'][key] = {'kind': 'creation_observation', 'creation_key': creation_key}
        except (ValueError, TypeError, KeyError):
            ingestion.unresolved_buff_actions.append({'ts_ms': ts_ms, 'line_no': line_no,
                                           'reason': 'unbound_buff_creation_observation'})
        return True

    if " BUFF_ORIGIN " in raw_line:
        try:
            origin_text = raw_line.split(' BUFF_ORIGIN ', 1)[1]
            pairs = json.loads(origin_text, object_pairs_hook=list)
            if (not origin_text.startswith('{') or not isinstance(pairs, list)
                    or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs)):
                raise ValueError('origin_not_object')
            origin = dict(pairs)
            if len(origin) != len(pairs):
                raise ValueError('duplicate_origin_fields')
            uid = origin.get('buffUid')
            record = ingestion.active_buff_starts_by_uid.get(uid) if isinstance(uid, str) else None
            if (type(origin.get('schemaVersion')) is not int or origin['schemaVersion'] != 1
                    or record is None or origin.get('buffTemplate') not in {record.get('event_key'), record.get('raw_event_key')}
                    or any(type(origin.get(key)) is not str or not re.fullmatch(r'[1-9]\d*', origin[key])
                           or int(origin[key]) >= 2**64 for key in ('buffUid','sourceActorId','targetActorId','environmentInstId'))
                    or origin['sourceActorId'] != record.get('source_actor_id')
                    or origin['targetActorId'] != record.get('target_actor_id')
                    or type(origin.get('actionId')) is not int or origin['actionId'] < 0
                    or type(origin.get('operationSeq')) is not int or origin['operationSeq'] < 0
                    or type(origin.get('triggerType')) is not int or origin['triggerType'] != 0):
                raise ValueError('unbound_origin_identity')
            record.setdefault('origin_observations', []).append({**origin, 'lineNo': line_no, '_boundCreateRecord': True})
        except (ValueError, TypeError, KeyError):
            ingestion.unresolved_buff_actions.append({'ts_ms': ts_ms, 'line_no': line_no,
                                           'reason': 'unbound_buff_origin'})
        return True
    return False


def consume_buff_blackboard(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " BB[" in raw_line:
        if ingestion.pending_buff_record is not None:
            parsed_bb_fields = _extract_fields(raw_line)
            ingestion.pending_buff_record["bb_keys"].extend(parsed_bb_fields.keys())
            for key, raw_value in parsed_bb_fields.items():
                # Do not discard signed BB values. Negative values are
                # meaningful for typed resistance reductions.
                rate = _coerce_optional_float(raw_value)
                if rate is not None:
                    ingestion.pending_buff_record["bb_values"][key] = rate
                    ingestion.pending_buff_record.setdefault('_observed_bb_values', {})[key] = rate
            _apply_enemy_status_bb_overrides(
                ingestion.pending_buff_record,
                context_enemy_hint=ingestion.context_enemy_hint,
            )
            _preserve_raw_numeric_internal_trigger_buff_id(ingestion.pending_buff_record)
        return True
    return False
