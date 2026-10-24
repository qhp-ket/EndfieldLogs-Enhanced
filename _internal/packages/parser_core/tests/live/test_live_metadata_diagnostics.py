"""Constructed control fields must not become additional rDPS effects."""
from copy import deepcopy
import pytest
from parser_core import battle_log_parser as parser


def metadata_records():
    definitions = [
        ('buff_common_affixes_vulnerable_pulse', 'chr_0023_antal', 912, 'Buff', 0,
         {'rate': .2, 'duration': 20, 'child_buff_id': 0}),
        ('buff_common_affixes_enhance_fire', 'chr_0023_antal', 1074, 'Buff', 1,
         {'rate': .3, 'duration': 10, 'child_buff_id': 0}),
        ('buff_common_natural_natural_corrupt_triggered', 'chr_0025_ardelia', 1836, 'Skill', 3,
         {'def_decrease': 0, 'max_def_decrease': -20, 'duration': 10, 'def_decrease_tick': -1,
          'def_decrease_tick_final': 0, 'max_def_decrease_final': 0, 'additional_def_decrease': 0,
          'tick': 0, 'count': 2, 'start_def_decrease': -5, 'consumed_type': 3,
          'consumed_layer': 0, 'extra_scaling': 1}),
        ('buff_wpn_funnel_0008_magic_damage_taken_up', 'chr_0023_antal', 2228, 'Skill', 0,
         {'spell_damage_taken_up': .2, 'duration': 10, 'lv': 3}),
    ]
    for index, (key, source, template, kind, action, values) in enumerate(definitions):
        uid = str(1000 + index)
        yield {'event_key': key, 'raw_event_key': key, 'uid': uid,
               'source_character_key': source, 'target_character_key': 'eny_0051_rodin',
               'source_actor_id': '100', 'target_actor_id': '200', 'bb_values': values,
               'origin_observations': [{
                   'schemaVersion': 1, '_boundCreateRecord': True, 'buffUid': uid, 'buffTemplate': key,
                   'sourceActorId': '100', 'targetActorId': '200', 'environmentType': kind,
                   'ownerType': '1' if kind == 'Buff' else '2', 'environmentInstId': str(2000 + index),
                   'templateStrId': None, 'templateIntId': template, 'actionId': action,
                   'operationSeq': 10 + index, 'triggerType': 0}]}


RECORDS = list(metadata_records())


@pytest.mark.parametrize('record', RECORDS, ids=lambda record: record['event_key'])
def test_observed_known_metadata_does_not_fail_approved_effect_validation(record):
    entry = parser._rdps_registry_verified_effect_entry(deepcopy(record))
    assert entry is not None
    assert parser._rdps_registry_validation_error(entry, deepcopy(record)) is None
    unknown = deepcopy(record)
    unknown['bb_values']['unreviewed_damage_rate_fixture'] = .75
    error = parser._rdps_registry_validation_error(entry, unknown)
    assert error['unknown_bb_keys'] == ['unreviewed_damage_rate_fixture']


def test_corrosion_carrier_retains_known_forwarded_fields_without_allocating_them():
    record = deepcopy(next(row for row in RECORDS if row['event_key'].endswith('corrupt_triggered')))
    entry = parser._rdps_registry_verified_effect_entry(record)
    assert entry['_rdps_lifecycle_only'] is True
    assert entry['effects'] == []
    assert {'def_decrease', 'additional_def_decrease', 'def_decrease_tick_final',
            'max_def_decrease_final'} <= set(entry['ignored_bb_keys'])
    assert parser._collect_zone_effects(record) == []


def test_reviewed_metadata_names_exist_in_current_typed_roots():
    for record in RECORDS:
        root = parser._load_current_buff_roots()[record['event_key']]
        declared = {row['key'] for row in root['blackboard']}
        expected = ({'child_buff_id'} if record['event_key'].startswith('buff_common_affixes_') else
                    {'lv'} if record['event_key'].startswith('buff_wpn_') else
                    {'def_decrease_tick_final', 'max_def_decrease_final'})
        assert expected <= declared
