"""On-demand entity export; structured ingestion never calls the text formatter."""
from datetime import datetime, timedelta, timezone

from parser_core.trace_values import restore_value
from endfield_pcap.trace.formatting import _entity_attr_tokens, _intish, _floatish
from parser_core.ingestion.skill_wire import integer, identity_token, label
from parser_core.ingestion.structured_entity import ENTITY_TYPES


def entity_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in ENTITY_TYPES:
        raise ValueError('Expected entity event')
    if 'legacy_layout' not in event.data:
        raise ValueError('Entity event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    attrs = ' '.join(_entity_attr_tokens(data.get('attributes')))
    def present(key):
        value = data.get(key)
        return value if value is not None else 'unknown'
    if event.type == 'entity_stats':
        body = (f"ENTITY_STATS id={data['entity_id']} template={data['template']} kind={data['kind']} "
                f"level={present('level')} hp={present('hp')} attrs=[{attrs}]")
    elif event.type == 'entity_attributes':
        body = (f"ENTITY_ATTR_UPDATE id={data['entity_id']} obj={present('object_id')} "
                f"template={data['template']} attrs=[{attrs}]")
    elif event.type == 'entity_die':
        body = f"ENTITY_DIE id={data.get('entity_id')}"
    elif event.type == 'entity_value':
        def number(key):
            value = _floatish(data.get(key))
            return repr(value) if value is not None else 'unknown'
        body = (f"ENTITY_VALUE seq={data.get('operation_seq')} id={identity_token(data.get('entity_id'))} "
            f"scene={present('scene_num_id')} hp={number('hp')} ult={number('ultimate_sp')} delta={number('delta')} "
            f"srcType={label(data, 'source_type')} srcInt={identity_token(data.get('source_int'))} "
            f"origSrcType={label(data, 'original_source_type')} origSrcInt={identity_token(data.get('original_source_int'))}")
    else:
        detail = data['detail']
        def vector(key):
            values = detail.get(key) if isinstance(detail.get(key), dict) else {}
            return ','.join(repr(number) if (number := _floatish(values.get(axis))) is not None else 'unknown' for axis in ('x', 'y', 'z'))
        source_id = _intish(detail.get('source_actor_id')) or _intish(data.get('owner_id'))
        body = (f"ABILITY_ENTITY_SPAWN seq={integer(data.get('operation_seq')) or 0} tick={integer(data.get('client_tick_ms')) or 0} "
            f"actionId={integer(data.get('action_id')) or 0} inst={identity_token(data.get('event_inst_id'))} "
            f"skill={label(data, 'skill', 'unknown_skill')} templateIntId={identity_token(data.get('template_int_id'))} "
            f"ownerId={identity_token(data.get('owner_id'))} owner={label(data, 'owner', '?')} "
            f"sourceId={identity_token(source_id)} source={label(data, 'source', '?')} entityId={identity_token(detail.get('entity_id'))} "
            f"pos={vector('position')} rot={vector('rotation')}")
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {body}\n"]
