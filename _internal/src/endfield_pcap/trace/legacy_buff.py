"""Independent old-log rendering of ordered BUFF snapshots."""
from datetime import datetime, timezone, timedelta
from parser_core.ingestion.skill_wire import identity_token
from parser_core.trace_values import restore_value


def buff_legacy_lines(event, *, timezone_offset_minutes):
    data = restore_value(event.data, event.data['legacy_layout'])
    uid = identity_token(data.get('buff_inst_id'))
    if event.type == 'buff_start':
        body = (f'BUFF_START #{data["buff_seq"]} id="{data.get("template") or "unknown_buff"}" uid={uid} '
                f'owner={data.get("owner") or "?"} src={data.get("source") or "?"} '
                f'ownerId={identity_token(data.get("target_id"))} srcId={identity_token(data.get("source_actor_id"))} '
                'dur=unknown lifeT=unknown passed=unknown enh=unknown')
    elif event.type == 'buff_end':
        template = data.get('template') or ('unknown_buff' if data.get('template_status') == 'unresolved' else '')
        body = f'BUFF_END #{data["buff_seq"]} id="{template}" uid={uid}'
    elif event.type == 'buff_blackboard':
        body = f'BB[{uid}]: ' + ' '.join(f'{row["key"]}={row["value"]:.6g}' for row in data['values'])
    else:
        raise ValueError('Expected BUFF lifecycle or blackboard event')
    stamp = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f'[{stamp:%H:%M:%S}.{event.captured_at_ms % 1000:03d}] {body}\n']
