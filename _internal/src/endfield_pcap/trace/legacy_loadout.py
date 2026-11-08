"""Independent loadout export from decoded fields, with no live bridge state."""
from datetime import datetime, timedelta, timezone

from parser_core.ingestion.loadout_wire import source_integer, source_number, source_text
from endfield_pcap.trace.export_values import export_data


def loadout_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in ('loadout_group', 'loadout_slot', 'loadout_stats'):
        raise ValueError('Expected loadout event')
    data = export_data(event)
    def n(key):
        return source_number(data, key)
    def t(key, fallback=''):
        return source_text(data, key, fallback)
    def observed(key):
        value = data.get(key)
        return 'unknown' if value is None else str(value)
    if event.type == 'loadout_group':
        roster = ' '.join(str(row['entity_id']) for row in data['roster'])
        body = f"LOADOUT reason={data['reason']} slotCount={data['slot_count']} memberCount={data['member_count']} roster=[{roster}]"
    elif event.type == 'loadout_slot':
        complete = f"equipsComplete={int(data['equipment_snapshot_complete'])} " if type(data.get('equipment_snapshot_complete')) is bool else ''
        unplaced = 'unplacedEquipInstIds=[' + ','.join(str(row['entity_id']) for row in data['unplaced_equipment']) + '] ' if 'unplaced_equipment' in data else ''
        refine = source_integer(data.get('refine'))
        body = (f"LOADOUT slot={n('slot')} char={data['template']} slotCharInstId={n('entity_id')} "
                f"resolvedCharInstId={n('entity_id')} character=packet charInfo.instId={n('entity_id')} "
                f"template={data['template']} charLv={n('char_level')} potential={n('potential')} weaponInstId={n('weapon_id')} "
                f"weaponTemplate={t('weapon_template', 'unknown_weapon')} weaponLv={n('weapon_lv')} refine={refine if refine is not None else 'unknown'} break={n('breakthrough')} "
                f"attachedGem={n('gem_id')} equipInsts={t('equip_inst_ids', '{}')} equips={t('equips', '{}')} "
                f"{complete}{unplaced}equipSuit={t('equip_suit', '{}')} skillIntIds=[{t('skill_int_ids')}]")
    else:
        body = (f"LOADOUT_STATS slot={n('slot')} char={data['template']} weaponInstId={n('weapon_id')} "
                f"weaponTemplate={t('weapon_template', 'unknown_weapon')} weaponSync={t('weapon_sync_source', 'missing')} "
                f"weaponBaseAtk={observed('weapon_base_atk')} weaponBaseAtkLv1={observed('weapon_base_atk_lv1')} weaponBaseAtkMax={observed('weapon_base_atk_max')} "
                f"weaponRefineStatsSource={t('weapon_refine_stats_source', 'unknown')} weaponRefineStats={{{t('weapon_refine_stats')}}} "
                f"weaponSourceSkills={{{t('weapon_source_skills')}}} gemInstId={n('gem_id')} gemWeaponId={n('gem_weapon_id')} "
                f"gemTemplate={n('gem_template')} gemTerms={{{t('gem_terms')}}}")
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {body}\n"]
