"""On-demand squad, actor mapping and skill-list export, independent of live state."""
from datetime import datetime, timedelta, timezone

from parser_core.trace_values import restore_value


def identity_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in ('squad', 'actor_mapping', 'character_skills', 'identity_inference'):
        raise ValueError('Expected identity event')
    if 'legacy_layout' not in event.data:
        raise ValueError('Identity event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    if event.type == 'squad':
        members = data['members']
        labels = [f"{row['template']}_{row['entity_id']}" for row in members]
        body = f"SQUAD size={len(members)} members=[{' '.join(labels)}]"
    elif event.type == 'character_skills':
        skills = data['skills']
        tokens = [f"{row['skill']}:{row['level']}" for row in skills]
        body = (f"CHAR_SKILLS owner={data['template']} ownerId={data['entity_id'] or 'unknown'} "
                f"count={len(skills)} skills=[{' '.join(tokens)}]")
    elif event.type == 'identity_inference':
        body = f"IDENTITY_INFERENCE actorId={data['entity_id']} template={data['template']} source={data['inference_source']}"
    else:
        body = (f"ACTOR_MAP id={data['entity_id']} template={data['template']} "
                f"source={data['mapping_source']} skill={data.get('skill')}")
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {body}\n"]
