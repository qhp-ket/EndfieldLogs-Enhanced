"""Independent rendering of calculation, preset and ink-release evidence."""
import json
from datetime import datetime, timezone, timedelta
from parser_core.ingestion.blackboard_wire import blackboard_fields, release_observation
from endfield_pcap.trace.export_values import export_data
from endfield_pcap.trace.formatting import _trace_string


def blackboard_legacy_lines(event, *, timezone_offset_minutes):
    data = export_data(event)
    if event.type == 'ink_release':
        body = 'INK_RELEASE ' + json.dumps(release_observation(data), ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    else:
        fields = blackboard_fields(data)
        if event.type == 'blackboard_calculation':
            fields.update(key=data['key'], final=repr(float(data['final_value'])))
            for source, target in (('value_a', 'valueA'), ('value_b', 'valueB')):
                if source in data:
                    fields[target] = repr(float(data[source]))
            marker = 'BB_SIMPLE_CALC'
        elif event.type == 'blackboard_modify':
            if 'key' in data:
                fields['key'] = data['key']
            if 'value' in data:
                fields['value'] = format(float(data['value']), '.6g')
            marker = 'BB_MULTI_MODIFY'
        else:
            fields['modifiedValue'] = _trace_string(data['modified_value'])
            marker = 'BB_SET_PRESET'
        body = marker + ' ' + ' '.join(f'{key}={value}' for key, value in fields.items())
    stamp = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f'[{stamp:%H:%M:%S}.{event.captured_at_ms % 1000:03d}] {body}\n']
