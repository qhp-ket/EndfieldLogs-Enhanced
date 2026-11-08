"""Ordered BUFF lifecycle and blackboard snapshots enter shared state directly."""
from parser_core.ingestion.hits import apply_buff_lifecycle
from parser_core.ingestion.buff_observations import apply_buff_blackboard
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.ingestion.skill_wire import identity_token, projected_number
from parser_core.trace_model import event_data


def _blackboard_value(value):
    return type(value) in (int, float) or (isinstance(value, dict) and set(value) == {'number_status'}
        and value['number_status'] in ('nan', 'positive_infinity', 'negative_infinity'))


def consume_structured_buff(ingestion, event, evidence_index):
    data = _object(event.data)
    if event.type not in {'buff_start', 'buff_end', 'buff_blackboard'}:
        raise ValueError('Expected BUFF lifecycle or blackboard event')
    for key in ('buff_inst_id', 'target_id', 'source_actor_id'):
        if key in data:
            _identity(data[key])
    if 'buff_inst_id' not in data:
        raise ValueError('Expected BUFF instance')
    for key in ('template', 'owner', 'source'):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError('Expected BUFF label')
    rows = data.get('values')
    if event.type == 'buff_blackboard' and (not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get('key'), str)
            or not _blackboard_value(row.get('value')) for row in rows)):
        raise ValueError('Expected BUFF blackboard values')
    restored = event_data(event)
    if event.type == 'buff_blackboard':
        # Repeated keys retain their original position and final observed value,
        # exactly as the legacy field reader. No UID-based rebinding is added.
        fields = {row['key']: projected_number(row['value']) for row in restored['values']}
        apply_buff_blackboard(ingestion, fields)
    else:
        fields = {'uid': identity_token(restored.get('buff_inst_id')),
                  'id': restored.get('template') or '', 'owner': restored.get('owner') or '?',
                  'src': restored.get('source') or '?',
                  'ownerId': identity_token(restored.get('target_id')),
                  'srcId': identity_token(restored.get('source_actor_id')), 'dur': 'unknown'}
        apply_buff_lifecycle(ingestion, 'start' if event.type == 'buff_start' else 'end',
                             fields, evidence_index, event.captured_at_ms)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
