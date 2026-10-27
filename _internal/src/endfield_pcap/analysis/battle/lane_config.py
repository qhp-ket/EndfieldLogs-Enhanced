"""Per-character skill-track preferences; membership never changes evidence."""
import json

DEFAULT_GROUPS = (
    ('战技', '战技', ('战技',)),
    ('连携', '连携 / 终结', ('连携', '大招')),
)


def skill_key(block):
    raw = str(block.cast_evidence.get('skill_key') or
              next((event.get('event_key') for event in block.events if event.get('event_key')), '') or block.name)
    return json.dumps([block.category, raw], ensure_ascii=False, separators=(',', ':'))


def skill_options(blocks, owner):
    options = {}
    for block in blocks:
        if block.lane == 'skill' and block.character_key == owner:
            key = skill_key(block)
            options.setdefault(key, dict(key=key, name=block.name, category=block.category))
    return list(options.values())


def normalize_lane_configs(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for owner, rows in list(value.items())[:500]:
        if not isinstance(owner, str) or not owner or len(owner) > 160 or not isinstance(rows, list):
            continue
        lanes, ids, assigned = [], set(), set()
        for index, row in enumerate(rows[:32]):
            if not isinstance(row, dict) or not isinstance(row.get('skills'), list):
                continue
            key = str(row.get('id') or f'track-{index}')[:80]
            if key in ids:
                continue
            ids.add(key)
            skills = []
            for skill in row['skills'][:256]:
                if isinstance(skill, str) and 0 < len(skill) <= 1024 and skill not in assigned:
                    skills.append(skill)
                    assigned.add(skill)
            lanes.append(dict(id=key, name=str(row.get('name') or f'轨道 {index+1}')[:60], skills=skills))
        if lanes or not rows:
            result[owner] = lanes
    return result


def default_lanes(options):
    rows = []
    for key, name, categories in DEFAULT_GROUPS:
        skills = [option['key'] for option in options if option['category'] in categories]
        if skills:
            rows.append(dict(id=key, name=name, skills=skills))
    return rows


def resolved_lanes(blocks, owner, saved=None):
    """Keep absent skills in preferences and append newly evidenced skills.

    The default shows battle skills and combined combo/ultimate skills only.
    Custom preferences retain an Other fallback for unassigned skill evidence.
    Empty preferences remain editable but have no explicit plotted row.
    """
    options = skill_options(blocks, owner)
    rows = normalize_lane_configs({owner: saved}).get(owner)
    if rows is None:
        return default_lanes(options)
    assigned = {skill for row in rows for skill in row['skills']}
    missing = [option['key'] for option in options if option['key'] not in assigned]
    if missing:
        target = next((row for row in rows if row['name'] == '其他'), None)
        if target is None:
            key, used = '其他', {row['id'] for row in rows}
            while key in used:
                key += '-new'
            target = dict(id=key, name='其他', skills=[])
            rows.append(target)
        target['skills'].extend(missing)
    return rows
