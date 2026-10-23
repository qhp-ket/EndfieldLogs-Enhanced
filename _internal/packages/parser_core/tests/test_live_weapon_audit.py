"""Constructed loadouts exercise approved static fields, without player gear."""
from copy import deepcopy

import pytest

from parser_core import battle_log_parser as parser


def loadout(character, weapon, skills, **extra):
    return dict(character_key=character, character_name=character, weapon_template=weapon,
                suit_effects=[], equips=[], unresolved_equip_inst_ids=[],
                equipment_snapshot_complete=True,
                weapon_source_skills=[{'skill_id': key, 'bb': values} for key, values in skills], **extra)


ROWS = [
    dict(loadout=loadout('chr_0016_laevat', 'wpn_sword_0006', [
        ('1247', {'wisd': 100}), ('2237', {'duration': 10, 'fire_dmg_up': .2, 'normal_atk_up': 1.1}),
        ('1249', {'atk': .25})]),
        expected_static=[('weapon_skill', 'atk', 'all', .25), ('weapon_skill', 'dmg_inc', 'fire', .2)],
        expected_arts=[]),
    dict(loadout=loadout('chr_0023_antal', 'wpn_funnel_0008', [
        ('2253', {'atk': 0, 'physpell': 15}),
        ('2228', {'duration': 10, 'lv': 3, 'second_attr_up': .2, 'spell_damage_taken_up': .15}),
        ('1391', {'mainattr': 20})]), expected_static=[],
        expected_arts=[('weapon_skill', 'arts_strength', 'all', 15)]),
    dict(loadout=loadout('chr_0006_wolfgd', 'wpn_pistol_0012', [
        ('2439', {'agi': 50}), ('2290', {'atk_up': .1, 'count': '', 'duration': 10,
            'nature_dmg_up': '', 'nature_dmg_up_mult': .1}), ('2456', {'usgs': .2})],
        weapon_refine=0, weapon_refine_source='synthetic_explicit'),
        expected_static=[('weapon_skill', 'atk', 'all', .1)], expected_arts=[]),
    dict(loadout=loadout('chr_0025_ardelia', 'wpn_funnel_0013', [
        ('1247', {'wisd': 50}), ('2449', {'heal': .2}),
        ('2273', {'duration': 15, 'lv': 3, 'second_attr_up': .2, 'spell_dmg_taken_up': .1})]),
        expected_static=[], expected_arts=[]),
]


def signature(entries):
    return [(entry['source_type'], entry['zone'], entry['element'], entry['rate']) for entry in entries]


@pytest.mark.parametrize('sample', ROWS, ids=[row['loadout']['character_name'] for row in ROWS])
def test_live_reviewed_trigger_fields_are_not_missing_static_inputs(sample):
    row = deepcopy(sample['loadout'])
    entries = parser._derive_static_self_multiplier_entries(row)
    assert signature(entries) == sample['expected_static']
    assert signature(parser._derive_static_arts_strength_entries(row)) == sample['expected_arts']
    assert row['rdps_unresolved_static_multiplier_sources'] == []
    assert row.get('weapon_refine') == sample['loadout'].get('weapon_refine')
    assert 'weapon_level' not in row

    # Audit classification must not change allocation. Both copies use the
    # same constructed static entries and an identical, explicit external effect.
    hit = {'character_key': row['character_key'], 'target_enemy_key': 'enemy',
           'ts_ms': 500, 'hit_value': 1000, 'skill_key': 'explicit',
           'damage_element': 'fire', 'damage_school': 'spell',
           'damage_decorate_mask': 128, 'baseline': None,
           'static_multiplier_entries': entries}
    windows = [{'uid': 'external', 'event_key': 'explicit',
                'source_character_key': 'other_character',
                'target_character_key': row['character_key'],
                'start_ts_ms': 0, 'end_ts_ms': 1000,
                'zone_effects': [{'zone': 'atk', 'element': 'all', 'rate': 0.2},
                                 {'zone': 'dmg_inc', 'element': 'fire', 'rate': 0.3}]}]
    before = parser._allocate_rdps_for_hit({**hit,
        'static_multiplier_entries': deepcopy(entries),
        'rdps_unresolved_static_multiplier_sources': [{'reason': 'synthetic_diagnostic'}]}, windows)
    after = parser._allocate_rdps_for_hit({**hit,
        'rdps_unresolved_static_multiplier_sources': []}, windows)
    assert before['contributions_map'] == after['contributions_map']


@pytest.mark.parametrize('sample', ROWS, ids=[row['loadout']['character_name'] for row in ROWS])
def test_new_field_on_reviewed_weapon_remains_unresolved(sample):
    row = deepcopy(sample['loadout'])
    row['weapon_source_skills'][0]['bb']['new_unreviewed_field'] = 0.123
    parser._derive_static_self_multiplier_entries(row)
    assert row['rdps_unresolved_static_multiplier_sources'][-1]['trigger_blackboard_keys'] == [
        'new_unreviewed_field']


@pytest.mark.parametrize('sample', ROWS, ids=[row['loadout']['character_name'] for row in ROWS])
def test_trigger_field_on_wrong_declared_skill_is_not_authorized(sample):
    row = deepcopy(sample['loadout'])
    row['weapon_source_skills'] = [{'skill_id': '1247', 'bb': {
        'normal_atk_up': 1.2, 'nature_dmg_up_mult': 0.05, 'spell_dmg_taken_up': 0.16}}]
    parser._derive_static_self_multiplier_entries(row)
    assert row['rdps_unresolved_static_multiplier_sources']


def test_arts_skill_zero_attack_placeholder_cannot_authorize_nonzero_attack():
    row = deepcopy(ROWS[1]['loadout'])
    row['weapon_source_skills'][0]['bb']['atk'] = 0.1
    assert parser._derive_static_self_multiplier_entries(row) == []
    assert row['rdps_unresolved_static_multiplier_sources'][-1]['trigger_blackboard_keys'] == ['atk']


def test_known_trigger_does_not_erase_an_unknown_field_on_same_weapon(monkeypatch):
    char = 'chr_0030_zhuangfy'
    monkeypatch.setattr(parser, '_select_loadout_snapshot_for_battle', lambda *args, **kwargs: {
        char: {'character_key': char, 'weapon_template': 'wpn_funnel_0017',
               'weapon_source_skills': [{'skill_id': '2913', 'level': 9,
                   'bb': {'pulse_dmg_up2': 0.154, 'new_unreviewed_field': 0.4}}],
               'suit_effects': [], 'equips': [], 'equipment_snapshot_complete': True}})
    result = parser.parse_raw_battle_log_text('\n'.join([
        f'[10:00:00.000] BUFF_START #1 id="buff_wpn_funnel_0017_layer" uid=77 '
        f'owner={char} src={char} ownerId=100 srcId=100 dur=30 lifeT=30 passed=0 enh=1',
        '[10:00:00.000]   BB[77]: pulse_dmg_up2=0.154 duration=30 max_stack=3',
        f'[10:00:01.000] HP_V2 #1 hit=100 eHP=1000 skill="{char}_attack1" '
        f'src={char} atk={char} tgt=eny_0051_rodin actionId=0 damageUnitIndex=0',
    ]), include_rdps_debug=True)
    blockers = result['debug_hits'][0]['rdps_unresolved_static_multiplier_sources']
    assert any('new_unreviewed_field' in row.get('trigger_blackboard_keys', []) for row in blockers)
