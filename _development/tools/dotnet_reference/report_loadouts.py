"""Pin battle equipment selection and weapon transfer repair to the fixed Python reference."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import random
import struct
import sys
from types import ModuleType
import zipfile


def canonical(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return {'int': str(value)}
    if isinstance(value, float):
        return {'f64': struct.pack('>d', value).hex()}
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    return [canonical(item) for item in value]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/report-loadouts.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed loadout reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    prefix = '_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    report = importlib.import_module('parser_core.reporting.loadout')
    numbers = {'101': 'sk_wpn_a', '102': 'sk_wpn_b', '103': 'sk_wpn_c', '901': 'sk_character'}
    if args.bundled:
        archive = '_internal/data/runtime-data.zip'
        pinned(archive)
        with zipfile.ZipFile(args.reference / archive) as bundle:
            for name in bundle.namelist():
                if name.endswith('/NumIdStrTable.json') or name == 'NumIdStrTable.json':
                    numbers.update({str(key): str(value) for key, value in json.loads(bundle.read(name))['skill_id']['dic'].items()})
                    break
            else:
                raise ValueError('No numeric skill table in pinned archive')
    report._load_num_id_str_skill_map = lambda: numbers
    cases = []

    def add(label, operation='resolve', **fields):
        config = dict(operation=operation, groups=[], fallback={}, anchor_ms=None, anchor_line_no=None, **{})
        config.update(fields)
        original = copy.deepcopy(config)
        try:
            if operation == 'sanitize':
                result = report._loadout_without_mismatched_weapon_skills(config['row'])
            else:
                groups = copy.deepcopy(config['groups'])
                fallback = copy.deepcopy(config['fallback'])
                if operation == 'resolve':
                    fallback = report._repair_weapon_puton_loadout_groups(groups, fallback)
                selected = report._select_loadout_snapshot_for_battle(groups, fallback,
                    anchor_ms=config['anchor_ms'], anchor_line_no=config['anchor_line_no'])
                result = dict(groups=groups, fallback=fallback, selected=selected)
        except (TypeError, ValueError, OverflowError, AttributeError, KeyError) as exc:
            result = dict(error=type(exc).__name__)
        assert original == config
        cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    def weapon(key, **fields):
        row = dict(weapon_inst_id=key, weapon_template='wpn_' + key, weapon_name='weapon-' + key,
            weapon_level=20, weapon_refine=2, weapon_refine_source='source_skill', potential=3,
            weapon_source_skills=[dict(skill_id={'a': 101, 'b': 102, 'c': 103}[key], potential_level=3, level=2)],
            weapon_refine_stats=[], skill_int_ids=[901, {'a': 101, 'b': 102, 'c': 103}[key]],
            equips=[dict(slot=0, item_id='equip_' + key, stats=[dict(value=.2)])], suit_effects=[], character_key='chr_' + key)
        row.update(fields)
        return row

    def group(rows, ts=1000, line=10, reason='SC_SCENE_INFO'):
        return dict(ts_ms=ts, line_no=line, reason=reason, rows=rows)

    base = group(dict(a=weapon('a'), b=weapon('b', potential=5)))
    # Source ordering, line boundaries and absence of historical evidence are independent of packet reason.
    for timestamp, anchor, line, boundary in itertools.product([None, True, 0, 999, 1000, 1001, '1000'],
            [None, 0, 1000, 1001], [None, 0, 9, 10, 11, '10'], [None, 0, 10]):
        add('boundary', 'select', groups=[group(dict(a=weapon('a')), timestamp, line)],
            fallback=dict(future=weapon('c')), anchor_ms=anchor, anchor_line_no=boundary)
    for groups in [[], [dict(rows={})], [dict(rows=[])], [dict(rows=None)], [group(dict(a=None))]]:
        add('fallback', 'select', groups=groups, fallback=dict(a=weapon('a')), anchor_ms=500)
    add('source-order', 'select', groups=[group(dict(a=weapon('a')), 900), group(dict(a=dict(level=99)), 800)])
    add('last-keys', 'select', groups=[base, group(dict(a=dict(level=99)))])
    add('last-invalid-row-retains-earlier-key', 'select', groups=[base, group(dict(a=None))])
    add('partial-fields', groups=[base, group(dict(a=dict(weapon_base_atk=200), b=dict(weapon_base_atk=300)))])
    for owner_present, reason, receiver, follow_reason, sync_instance in itertools.product([False, True],
            ['SC_WEAPON_PUTON', 'SC_SYNC_CHAR_BAG_INFO', 'other'], ['a', 'b'],
            ['SC_SCENE_INFO', 'SC_SYNC_CHAR_BAG_INFO', 'SC_WEAPON_PUTON'], ['a', 'b', 'c']):
        other = 'b' if receiver == 'a' else 'a'
        rows = {receiver: weapon(receiver, weapon_inst_id=other)}
        if owner_present:
            rows[other] = weapon(other)
        follow = group({receiver: weapon(receiver, weapon_inst_id=sync_instance), other: weapon(other)}, 1200, 30, follow_reason)
        add('transfer', groups=[base, group(rows, 1100, 20, reason), follow], fallback=dict(a=weapon('a'), b=weapon('b')))
    for source, template, skill, refine_source in itertools.product(['weapon_source_skills', 'weapon_refine_stats'],
            ['wpn_a', 'wpn_b', 'wpn_unknown', '', None], [101, 102, 901, 'sk_wpn_b', 'skill_101', 0, None],
            ['source_skill', 'catalog', None]):
        row = weapon('a', weapon_source_skills=[], weapon_refine_stats=[], weapon_template=template, weapon_refine_source=refine_source)
        row[source] = [dict(skill_id=skill), None]
        add('sanitize', 'sanitize', row=row)
    randomizer = random.Random(20261028)
    for _ in range(160):
        groups = [copy.deepcopy(base)]
        for index in range(randomizer.randint(1, 7)):
            rows = {key: weapon(key, weapon_inst_id=randomizer.choice(['a', 'b', 'c']))
                    for key in ['a', 'b', 'c'] if randomizer.choice([False, True])}
            if randomizer.choice([False, True]):
                rows = {key: dict(weapon_inst_id=row['weapon_inst_id'], potential=3, skill_int_ids=[901]) for key, row in rows.items()}
            groups.append(group(rows, 1000 + index * 10, 10 + index,
                randomizer.choice(['SC_WEAPON_PUTON', 'SC_SCENE_INFO', 'SC_SYNC_CHAR_BAG_INFO'])))
        add('sequence', groups=groups, fallback=dict(a=weapon('a')), anchor_ms=randomizer.choice([None, 999, 1020, 1100]))
    if args.bundled:
        for number, skill in numbers.items():
            if skill.startswith('sk_wpn_'):
                for template in [skill[3:], 'wpn_other']:
                    add('bundled-identity', 'sanitize', row=weapon('a', weapon_template=template,
                        weapon_source_skills=[dict(skill_id=int(number) if number.isdecimal() else number)]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(numbers=numbers, cases=cases), ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Report loadout fixtures:', len(cases))


if __name__ == '__main__':
    main()
