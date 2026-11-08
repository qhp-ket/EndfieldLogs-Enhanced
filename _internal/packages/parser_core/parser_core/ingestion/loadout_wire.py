"""Decoded loadout fields retain their evidence; only analysis applies old projections."""
from parser_core.ingestion.loadout_observation import LoadoutSlotObservation, LoadoutStatsObservation
from parser_core.ingestion.fields import _coerce_int


SLOT_FIELDS = ('slot', 'char_level', 'potential', 'weapon_template', 'weapon_lv', 'refine', 'breakthrough',
               'equip_inst_ids', 'equips', 'equip_suit', 'skill_int_ids', 'equipment_snapshot_complete')
STATS_FIELDS = ('slot', 'weapon_template', 'weapon_sync_source', 'weapon_base_atk', 'weapon_base_atk_lv1',
                'weapon_base_atk_max', 'weapon_refine_stats_source', 'weapon_refine_stats',
                'weapon_source_skills', 'gem_template', 'gem_terms')


def loadout_data(row, *, stats=False):
    result = {key: row[key] for key in (STATS_FIELDS if stats else SLOT_FIELDS) if key in row}
    result['template'] = str(row.get('char') or '')
    identities = [('weapon_inst_id', 'weapon_id'), ('attached_gem', 'gem_id')]
    identities.append(('gem_weapon_id', 'gem_weapon_id') if stats else ('char_inst_id', 'entity_id'))
    for source, target in identities:
        if source in row:
            result[target] = row[source]
    if not stats and isinstance(row.get('unresolved_equip_inst_ids'), list):
        result['unplaced_equipment'] = [{'entity_id': value} for value in row['unresolved_equip_inst_ids']]
    return result


def source_integer(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def source_text(data, key, fallback=''):
    return str(data.get(key) or fallback)


def source_number(data, key):
    return source_integer(data.get(key)) or 0


def compact_body(value):
    # Parse the upstream field's balanced braces, never an assembled trace row.
    start = value.find('{')
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(value)):
        if value[index] == '{':
            depth += 1
        elif value[index] == '}':
            depth -= 1
            if depth == 0:
                return value[start + 1:index]
    return None


def slot_observation(data):
    level = source_number(data, 'weapon_lv')
    refine = source_integer(data.get('refine'))
    unplaced = data.get('unplaced_equipment')
    return LoadoutSlotObservation(character=data['template'], slot=source_number(data, 'slot'),
        character_level=source_number(data, 'char_level') or None, potential=source_number(data, 'potential'),
        weapon_instance=str(source_number(data, 'weapon_id')), weapon=source_text(data, 'weapon_template', 'unknown_weapon'),
        weapon_level=level if level > 0 else None, refine=refine if refine is not None and 0 <= refine <= 5 else None,
        breakthrough=source_number(data, 'breakthrough'),
        suits=native_rows(data, 'equip_suit'), equipment=native_rows(data, 'equips'),
        skill_ids=[str(value) for value in native_rows(data, 'skill_int_ids')],
        unplaced_ids=[row['entity_id'] for row in unplaced if row['entity_id'] is not None] if unplaced is not None else None,
        equipment_complete=data.get('equipment_snapshot_complete')
        if type(data.get('equipment_snapshot_complete')) is bool and 'equips' not in data.get('invalid_fields', {}) else None)


def native_rows(data, key):
    rows = data.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError(f'Expected native loadout array: {key}')
    return rows


def stats_observation(data):
    # LOADOUT_STATS never supplied weaponLv; its missing-level fallback stays unknown.
    def attack(key):
        value = data.get(key)
        return _coerce_int(str(value) if value is not None else 'unknown')
    return LoadoutStatsObservation(character=data['template'], weapon=source_text(data, 'weapon_template', 'unknown_weapon'),
        weapon_instance=str(source_number(data, 'weapon_id')),
        refine_stats=native_rows(data, 'weapon_refine_stats'), source_skills=native_rows(data, 'weapon_source_skills'),
        base_attack=attack('weapon_base_atk'), base_attack_lv1=attack('weapon_base_atk_lv1'), base_attack_max=attack('weapon_base_atk_max'),
        gem_instance=str(source_number(data, 'gem_id')), gem_weapon=str(source_number(data, 'gem_weapon_id')),
        gem_template=str(source_number(data, 'gem_template')),
        terms=native_rows(data, 'gem_terms'))
