"""Independent rendering of packet proof objects in the established log layout."""
import json
from datetime import datetime, timezone, timedelta
from parser_core.ingestion.buff_packet_wire import packet_observation
from parser_core.ingestion.structured_buff_packet import unresolved_fields
from endfield_pcap.trace.export_values import export_data


def buff_packet_legacy_lines(event, *, timezone_offset_minutes):
    data = export_data(event)
    if event.type == 'buff_unresolved':
        fields = unresolved_fields(data)
        body = (f'BUFF_ACTION_UNRESOLVED uid={fields["uid"]} seq={fields["seq"]} '
                f'triggerType={fields["triggerType"]} actionId={fields["actionId"]} '
                f'ownerId={fields["ownerId"]} srcId={fields["srcId"]}')
    else:
        observation = packet_observation(data)
        marker = {'buff_creation': 'BUFF_CREATE_OBSERVED', 'buff_origin': 'BUFF_ORIGIN',
                  'buff_enable': 'BUFF_ENABLE', 'buff_keyword': 'BUFF_KEYWORD_UPDATE'}[event.type]
        if event.type == 'buff_keyword' and observation.get('validationErrors'):
            marker += '_UNRESOLVED'
        body = marker + ' ' + json.dumps(observation, ensure_ascii=event.type == 'buff_enable',
            separators=(',', ':'), allow_nan=event.type not in ('buff_creation', 'buff_keyword'))
    stamp = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f'[{stamp:%H:%M:%S}.{event.captured_at_ms % 1000:03d}] {body}\n']
