"""Explicit team membership and mapping diagnostics, without new identity inference."""
from parser_core.ingestion.identity import apply_squad, squad_bindings
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.trace_model import event_data


def consume_structured_identity(ingestion, event, evidence_index):
    projected = _object(event.data)
    if event.type == 'squad':
        rows = projected.get('members')
        if not isinstance(rows, list):
            raise ValueError('Expected squad members')
        for row in rows:
            row = _object(row)
            if 'entity_id' not in row or not isinstance(row.get('template'), str):
                raise ValueError('Expected squad identity fields')
            _identity(row['entity_id'])
    elif event.type in ('actor_mapping', 'identity_inference'):
        source_key = 'inference_source' if event.type == 'identity_inference' else 'mapping_source'
        if 'entity_id' not in projected or not all(isinstance(projected.get(key), str) for key in ('template', source_key)):
            raise ValueError('Expected mapping identity fields')
        _identity(projected['entity_id'])
    else:
        raise ValueError('Expected identity event')
    data = event_data(event)
    if event.type == 'squad':
        apply_squad(ingestion, squad_bindings((row['template'], row['entity_id']) for row in data['members']))
    # ACTOR_MAP was a diagnostic line, not authority to modify ingestion identity.
    ingestion.timestamp_clock_origin = ingestion.timestamp_clock_origin if ingestion.timestamp_clock_origin is not None else event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
