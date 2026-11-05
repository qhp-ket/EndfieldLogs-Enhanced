"""Independent old-log rendering of observed dynamic blackboard packets."""
import json
from datetime import datetime, timezone, timedelta
from parser_core.ingestion.buff_packet_wire import packet_observation
from parser_core.ingestion.dynamic_wire import dynamic_fields
from parser_core.trace_values import restore_value


def dynamic_legacy_lines(event, *, timezone_offset_minutes):
    data = restore_value(event.data, event.data['legacy_layout'])
    observation = packet_observation(data)
    proof = json.dumps(observation, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if event.type == 'blackboard_dynamic':
        fields = dynamic_fields(data)
        body = 'BB_MODIFY_DYNAMIC ' + ' '.join(f'{key}={value}' for key, value in fields.items()) + ' identity=' + proof
    elif event.type in ('buff_attribute_refresh', 'blackboard_skill_setting'):
        marker = 'BUFF_ATTR_REFRESH' if event.type == 'buff_attribute_refresh' else 'BB_READ_SKILL_SETTING'
        body = marker + ('_UNRESOLVED' if observation.get('validationErrors') else '') + ' ' + proof
    else:
        raise ValueError('Expected dynamic blackboard event')
    stamp = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f'[{stamp:%H:%M:%S}.{event.captured_at_ms % 1000:03d}] {body}\n']
