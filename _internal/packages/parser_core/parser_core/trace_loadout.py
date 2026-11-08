"""Typed equipment evidence; string decoding is confined to capture/v1 adaptation."""
import re

from parser_core.ingestion.fields import _parse_equip_levels, _parse_inline_equip_stats


def typed_loadout(data):
    result = dict(data)
    invalid = dict(data.get('invalid_fields', {}))
    from parser_core.ingestion.loadout_wire import compact_body
    for key in ('equip_suit', 'equip_inst_ids'):
        if isinstance(result.get(key), str):
            raw = result[key]
            body = compact_body(raw)
            pattern = r'\[([^\]]+)\]=([0-9]+)' if key == 'equip_suit' else r'\[([0-9]+)\]=([0-9]+)'
            result[key] = [{'suit_id' if key == 'equip_suit' else 'slot': name if key == 'equip_suit' else int(name),
                            'piece_count' if key == 'equip_suit' else 'entity_id': int(value) if key == 'equip_suit' else value}
                           for name, value in re.findall(pattern, body or '')]
            if body is None or re.sub(pattern, '', body).strip():
                invalid[key] = raw
    if isinstance(result.get('skill_int_ids'), str):
        result['skill_int_ids'] = [int(value) for value in re.findall(r'\d+', result['skill_int_ids'].split(']', 1)[0])]
    if isinstance(result.get('equips'), str):
        raw = result['equips']
        body = compact_body(raw)
        blob = body or ''
        matches = list(re.finditer(r'\[(\d+)\]=', blob))
        rows = []
        for index, match in enumerate(matches):
            entry = blob[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(blob)].strip()
            level, stats = re.search(r'\|lv=([^|]+)', entry), re.search(r'\|stats=(.*)$', entry)
            rows.append({'slot': int(match[1]), 'item_id': entry.split('|', 1)[0].strip(),
                         'enhance_levels': _parse_equip_levels(level[1] if level else None),
                         'stats': _parse_inline_equip_stats(stats[1] if stats else None)})
        result['equips'] = rows
        if body is None or blob.strip() and not rows:
            invalid['equips'] = raw
    for key in ('weapon_source_skills', 'weapon_refine_stats'):
        if isinstance(result.get(key), str):
            from parser_core.ingestion.loadout import _parse_weapon_source_skills
            raw = result[key]
            result[key] = _parse_weapon_source_skills(raw)
            if raw.strip('{} ') and not result[key]:
                invalid[key] = raw
    if isinstance(result.get('gem_terms'), str):
        text = result['gem_terms']
        parts = [re.fullmatch(r'(\d+):([^,@{}]*)@cost(\d+)', part.strip()) for part in text.split(',')] if text else []
        if all(parts):
            result['gem_terms'] = [{'term_num_id': int(match[1]), 'template': match[2], 'cost': int(match[3])} for match in parts]
        else:
            result['gem_terms'] = []
            invalid['gem_terms'] = text
    if invalid:
        result['invalid_fields'] = invalid
    return result


def legacy_loadout(data):
    """Generate the old display grammar only when exporting compatibility text."""
    result = dict(data)
    def scalar(value):
        return format(value, '.17g') if isinstance(value, float) else str(value)
    def boards(value):
        return ','.join(f'{key}={scalar(child)}' for key, child in value.items())
    for key in ('equip_suit', 'equip_inst_ids'):
        if isinstance(result.get(key), list):
            name, count = ('suit_id', 'piece_count') if key == 'equip_suit' else ('slot', 'entity_id')
            result[key] = '{' + ' '.join(f'[{row[name]}]={row[count]}' for row in result[key]) + '}'
    if isinstance(result.get('skill_int_ids'), list):
        result['skill_int_ids'] = ' '.join(str(value) for value in result['skill_int_ids'])
    if isinstance(result.get('equips'), list):
        rows = []
        for row in result['equips']:
            levels = ','.join(f"{value['index']}:{value['level']}" for value in row['enhance_levels'])
            stats = ';'.join(f"{value['slot']}:{value['name']}={scalar(value['value'])}" + (f"@{value['level']}" if value['level'] is not None else '') for value in row['stats'])
            rows.append(f"[{row['slot']}]={row['item_id']}|lv={levels}|stats={stats}")
        result['equips'] = '{' + ' '.join(rows) + '}'
    for key in ('weapon_source_skills', 'weapon_refine_stats'):
        if isinstance(result.get(key), list):
            result[key] = ';'.join(row['skill_id'] + (f":level={row['level']}" if row['level'] is not None else '')
                + (f":potentialLv={row['potential_level']}" if row['potential_level'] is not None else '')
                + ':bb={' + boards(row['bb']) + '}' for row in result[key])
    if isinstance(result.get('gem_terms'), list):
        result['gem_terms'] = result.get('invalid_fields', {}).get('gem_terms', ','.join(
            f"{row['term_num_id']}:{row['template']}@cost{row['cost']}" for row in result['gem_terms']))
    result.update(result.get('invalid_fields', {}))
    return result
