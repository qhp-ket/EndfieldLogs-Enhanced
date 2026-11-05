"""Freeze full static baseline orchestration against the immutable Python report implementation."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType, SimpleNamespace
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
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixtures / 'report-baseline.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies, inputs = {}, {}

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed report baseline reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    prefix = '_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    baseline = importlib.import_module('parser_core.reporting.baseline')
    static = importlib.import_module('parser_core.allocation.static_loadout')
    resources = importlib.import_module('parser_core.catalog.resources')
    names = importlib.import_module('parser_core.catalog.names')

    def setup(name):
        data = (fixtures / (name + '.json')).read_bytes()
        inputs[name] = hashlib.sha256(data).hexdigest()
        return json.loads(json.loads(data)['resources_json'])

    shared = setup('static-multipliers')
    shared['arts_catalog'] = setup('static-arts-strength')['catalog']
    modifiers = shared['equipment']['equip_a']['attribute_modifiers']
    modifiers.extend([
        dict(attrIndex=1, attrType=2, modifierType=7, modifyAttributeType=0, attrValues=[25., 30.]),
        dict(attrIndex=2, attrType=87, modifierType=5, modifyAttributeType=0, attrValues=[20., 25.]),
        dict(attrIndex=3, attrType=2, modifierType=6, modifyAttributeType=0, attrValues=[.1, .2]),
    ])
    character = dict(raw=dict(mainAttrType=39, subAttrType=40, attributes=[
        dict(breakStage=0, Attribute=dict(attrs=[dict(attrType=0, attrValue=1), dict(attrType=2, attrValue=100)])),
        dict(breakStage=1, Attribute=dict(attrs=[dict(attrType=0, attrValue=2), dict(attrType=2, attrValue=120)])),
    ]))
    shared['files'] = {'data/local_tables/character/items/chr_test.json': json.dumps(character)}
    datasets = {'synthetic': shared}
    current = {}
    original_equipment = static._load_equip_item_catalog
    original_weapons = static._load_weapon_catalog
    static._load_equip_item_catalog = lambda: current['equipment']
    static._load_weapon_catalog = lambda: current['weapons']
    static._load_num_id_str_skill_map = lambda: current['numbers']
    names._load_num_id_str_skill_map = lambda: current['numbers']
    cases = []
    with tempfile.TemporaryDirectory(prefix='endfield-report-baseline-reference-') as directory:
        root = Path(directory)
        static._repo_root = lambda: root
        resources._repo_root = lambda: root

        def add(label, row=None, hits=None, groups=None, fallback=None, first_hit_ms=1000, suits=None, dataset='synthetic'):
            config = copy.deepcopy(dict(resource_id=dataset, hits=hits or [], groups=groups or [],
                fallback=fallback if fallback is not None else ({'chr_test': row} if row is not None else {}),
                first_hit_ms=first_hit_ms, active_suits=suits if suits is not None else {'chr_test': ['suit_a']}))
            current.clear()
            current.update(datasets[dataset])
            for name, text in current['files'].items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf8')
            for name, catalog in [('item_damage_baseline_catalog.json', current['catalog']), ('item_arts_strength_catalog.json', current['arts_catalog'])]:
                path = root / 'data/local_static/skill' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(catalog), encoding='utf8')
            resources._load_character_base_stat_catalog.cache_clear()
            prepared_hits = []
            for wrapper in config['hits']:
                hit = copy.deepcopy(wrapper['evidence'])
                for name, mapping in wrapper.get('numeric', {}).items():
                    hit.setdefault(name, {}).update({int(key): value for key, value in mapping.items()})
                prepared_hits.append(hit)
            state = SimpleNamespace(hits=prepared_hits, loadout_groups=copy.deepcopy(config['groups']),
                loadout_by_char=copy.deepcopy(config['fallback']),
                active_suits_by_char={key: set(values) for key, values in config['active_suits'].items()},
                active_weapons_by_char={'old': 'must-be-rebuilt'})
            try:
                selected, stale, arts = baseline.prepare_static_baseline(state, config['first_hit_ms'])
                result = dict(loadouts=selected, stale=stale, arts_strength=arts, hits=state.hits,
                    active_suits={key: sorted(value) for key, value in state.active_suits_by_char.items()}, active_weapons=state.active_weapons_by_char)
            except (TypeError, ValueError, OverflowError, AttributeError, KeyError) as exc:
                result = dict(error=type(exc).__name__)
            cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

        row = dict(weapon_template='wpn_a', weapon_base_atk=50, character_level=1,
            weapon_source_skills=[dict(skill_id=101, bb=dict(damage=.3, arts=40))],
            equipment_snapshot_complete=True, equips=[dict(item_id='equip_a', slot=0)],
            suit_effects=[dict(suit_id='suit_a', active=True, value=dict(damage=.2, arts=30))])

        def hit(character_key='chr_test', **changes):
            evidence = dict(character_key=character_key, ts_ms=1000, line_no=10, target_enemy_key='eny_test',
                target_actor_id='7', enemy_hp_after=900, hit_value=100)
            evidence.update(changes)
            return dict(evidence=evidence)

        numeric = dict(attacker_stats_basic_attrs={'2': 110}, attacker_stats_attrs={'39': 10.9, '40': 5.9, '78': .01, '79': .02})
        add('empty')
        add('row-no-hits', row)
        add('hit-no-loadout', hits=[hit()])
        add('complete', row, [dict(hit(), numeric=numeric)])
        for weapon_attack, basic in itertools.product([None, -1, 0, 50, '50', True], [None, -1, 0, 110, '110', True]):
            add('attack-baseline', dict(row, weapon_base_atk=weapon_attack), [dict(hit(), numeric={'attacker_stats_basic_attrs': {'2': basic}})])
        for loadout_level, observed_level in itertools.product([None, -1, 0, 1, 2, 3, 1., '1', True], [None, 0, 1, 2, '1', True]):
            add('level-selection', dict(row, character_level=loadout_level), [hit(attacker_stats_level=observed_level)])
        for main, sub, scale in itertools.product([None, -1, 0, 10.9, '10.9', True, float('inf')], [None, 0, 5.9], [None, -1, 0, .01, '0.01']):
            values = {'39': main, '40': sub, '78': scale, '79': .02}
            add('ability-factor', row, [dict(hit(), numeric={'attacker_stats_attrs': values})])
        add('text-attributes-are-not-integer-keys', row, [hit(attacker_stats_basic_attrs={'2': 999}, attacker_stats_attrs={'39': 99, '40': 99, '78': .01, '79': .01})])
        add('numeric-attributes-take-own-keys', row, [dict(hit(attacker_stats_basic_attrs={'2': 999}), numeric=numeric)])
        for existing in [0, 1.5, 'existing']:
            add('retain-unreplaced-derived-fields', dict(row, weapon_base_atk=0), [hit(base_attack_for_percent=existing, attack_ability_factor=existing)])
        for actors in [['chr_test'], ['chr_test', 'chr_missing'], ['eny_other'], [''], ['chr_missing']]:
            add('stale-party', row, [hit(character_key=actor) for actor in actors])
        for timestamp, line_no in itertools.product([999, 1000, 1001, '1000', 1000.9], [None, 0, 9, 10, 11, '10', 10.9]):
            groups = [dict(ts_ms=900, line_no=1, rows={'chr_test': dict(row, weapon_base_atk=40)}),
                dict(ts_ms=1000, line_no=10, rows={'chr_test': dict(row, weapon_base_atk=60)})]
            add('first-hit-boundary', row, [hit(ts_ms=timestamp, line_no=line_no)], groups)
        for first_hit_ms in [800, 900, 1000, 1001]:
            add('no-hit-boundary', row, groups=[dict(ts_ms=900, line_no=1, rows={'chr_test': row})], first_hit_ms=first_hit_ms)
        for selected in [{}, {'chr_test': row}, {'chr_other': row}, {'chr_test': row, 'chr_other': row}]:
            add('latest-party-membership', row, [hit()], [dict(ts_ms=800, rows={'chr_test': row}), dict(ts_ms=900, rows=selected)])
        add('blockers-retained', dict(row, unresolved_equip_inst_ids=['7'], weapon_source_skills=[dict(skill_id=101, bb=dict(damage=.3, arts=40, unknown=1))]), [dict(hit(), numeric=numeric)])
        add('conflicting-cards', dict(row, weapon_source_skills=[dict(skill_id=101, bb=dict(damage=value, arts=value * 100)) for value in [.2, .3, .2]]), [hit()])
        add('independent-hp-targets', row, [hit(), hit(ts_ms=1001, enemy_hp_after=800), hit(ts_ms=1002, target_actor_id='8', enemy_hp_after=900),
            hit(ts_ms=1003, enemy_hp_after=1000, target_enemy_max_hp=1200)])
        add('zero-sources', {}, [hit()])
        add('no-character-base', dict(row, character_level=90), [dict(hit(), numeric=numeric)])
        if args.bundled:
            archive = '_internal/data/runtime-data.zip'
            pinned(archive)
            with zipfile.ZipFile(args.reference / archive) as bundle:
                character_paths = [info.filename for info in bundle.infolist()
                    if info.filename.startswith('data/local_tables/character/items/chr_') and info.filename.endswith('.json')]
                for info in bundle.infolist():
                    if info.is_dir():
                        continue
                    path = (root / info.filename).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError('Runtime archive outside temporary directory')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bundle.read(info))
            original_equipment.cache_clear()
            original_weapons.cache_clear()
            datasets['bundled'] = dict(equipment=original_equipment(), weapons=original_weapons(),
                numbers=json.loads((root / 'data/local_tables/NumIdStrTable.json').read_text(encoding='utf8'))['skill_id']['dic'],
                catalog=json.loads((root / 'data/local_static/skill/item_damage_baseline_catalog.json').read_text(encoding='utf8')),
                arts_catalog=json.loads((root / 'data/local_static/skill/item_arts_strength_catalog.json').read_text(encoding='utf8')),
                files={name: (root / name).read_text(encoding='utf8') for name in character_paths})
            actual = datasets['bundled']
            item = next(iter(actual['equipment']))
            weapon_id, weapon_meta = next(iter(actual['weapons'].items()))
            for path in sorted(actual['files']):
                character_key = Path(path).stem
                for level in [1, 10, 90]:
                    candidate = dict(character_level=level, weapon_template=weapon_id, weapon_base_atk=100,
                        equipment_snapshot_complete=True, equips=[dict(item_id=item, slot=0)],
                        weapon_source_skills=[dict(skill_id=skill, bb=dict(atk=.1)) for skill in weapon_meta.get('weapon_skill_ids', [])])
                    add('bundled-character', hits=[dict(hit(character_key), numeric=numeric)], fallback={character_key: candidate}, dataset='bundled')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(dict(resources_json=json.dumps(datasets, ensure_ascii=True), cases=cases), ensure_ascii=True, separators=(',', ':')), encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies, synthetic_input_sha256=inputs), indent=2), encoding='utf8')
        print('Report baseline fixtures:', len(cases))


if __name__ == '__main__':
    main()
