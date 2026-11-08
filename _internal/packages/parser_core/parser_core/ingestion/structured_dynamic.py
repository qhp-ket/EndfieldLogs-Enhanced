"""Runtime observations enter the existing pending/refresh state machine."""
from parser_core.ingestion.buff_packet_wire import packet_observation
from parser_core.ingestion.dynamic_evidence import apply_dynamic_observation
from parser_core.ingestion.dynamic_wire import dynamic_fields
from parser_core.ingestion.structured_damage import _object, _identity
from parser_core.trace_model import event_data


def consume_structured_dynamic(ingestion, event, evidence_index):
    if event.type not in ('blackboard_dynamic', 'buff_attribute_refresh', 'blackboard_skill_setting'):
        raise ValueError('Expected dynamic blackboard event')
    data = _object(event.data)
    observation = _object(data.get('observation'))
    for fields in (data, observation):
        for key in ('buff_inst_id', 'owner_id', 'operation_owner_id', 'environment_inst_id'):
            if key in fields:
                _identity(fields[key])
    restored = event_data(event)
    # Skill-setting packets have always been diagnostic evidence only; they
    # must not create an attribute refresh or an independently usable value.
    if event.type != 'blackboard_skill_setting':
        refresh = event.type == 'buff_attribute_refresh'
        apply_dynamic_observation(ingestion, refresh, {} if refresh else dynamic_fields(restored),
                                  packet_observation(restored), evidence_index, event.captured_at_ms)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
