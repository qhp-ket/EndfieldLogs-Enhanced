"""Typed skill lists share legacy level folding and verified refinement rules."""
from parser_core.ingestion.loadout import apply_character_skills, character_skill_levels
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.trace_values import restore_value


def consume_structured_character_skills(ingestion, event, evidence_index):
    data = _object(event.data)
    if event.type != 'character_skills' or not isinstance(data.get('template'), str) or 'entity_id' not in data:
        raise ValueError('Expected character skill identity')
    _identity(data['entity_id'])
    rows = data.get('skills')
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('skill'), str)
                                         or 'level' not in row for row in rows):
        raise ValueError('Expected character skill observations')
    restored = restore_value(data, _object(data.get('legacy_layout', {})))
    parsed = character_skill_levels(restored['template'], ((row['skill'], str(row['level'])) for row in restored['skills']))
    apply_character_skills(ingestion, parsed, str(restored['entity_id'] or 'unknown'), evidence_index, event.captured_at_ms)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
