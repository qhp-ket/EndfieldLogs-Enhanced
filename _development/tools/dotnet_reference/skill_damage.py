"""Generate exact action damage projections from the fixed Python reference."""
from pathlib import Path
from types import ModuleType
import argparse
import copy
import gzip
import hashlib
import importlib
import json
import random
import struct
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--bundled', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    if args.output is None:
        args.output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/skill-damage.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed damage reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    damage = importlib.import_module('parser_core.catalog.skill_damage')
    elements = importlib.import_module('parser_core.effects.damage_types')
    arts = importlib.import_module('parser_core.allocation.arts_strength')
    current = {}
    damage._canonical_packet_skill_id = lambda key: current.get('canonical', key)
    damage._load_official_skill_damage_catalog = lambda: {current['canonical']: current['profile']} if current.get('profile') is not None else {}
    damage._load_current_buff_roots = lambda: {current['canonical']: current.get('root')} if current.get('root') is not None else {}
    elements._load_skill_action_damage_units = damage._load_skill_action_damage_units

    def encode(value):
        if type(value) is int:
            return {'int': str(value)}
        if type(value) is float:
            return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        if isinstance(value, dict):
            return {str(key): encode(item) for key, item in value.items()}
        return value

    cases = []

    def add(name, profile, root=None, canonical='skill_test'):
        current.clear()
        current.update(profile=profile, root=root, canonical=canonical)
        damage._load_skill_action_damage_units.cache_clear()
        units = damage._load_skill_action_damage_units(canonical)
        queries = [(None, None), (0, 0), (-1, 0), (1, None), (1, -1)]
        for action, values in units.items():
            queries.extend((action, unit.get('index')) for unit in values
                           if type(unit.get('index')) is int)
        classifications = []
        for action, index in queries:
            element = elements._infer_skill_action_damage_element(canonical, action, index)
            classifications.append(dict(element=element, school=elements._damage_school_from_element(element)))
        cases.append(dict(name=name, kind='units', canonical=canonical,
            profile_json=json.dumps(profile, ensure_ascii=True), root_json=json.dumps(root, ensure_ascii=True),
            queries=[[str(action) if action is not None else None, str(index) if index is not None else None]
                     for action, index in queries],
            expected=encode(dict(units=units, classifications=classifications))))

    def unit(**changes):
        return dict(index=0, element='fire', damageAttribute='hp', source='typed_memorypack_full_object', **changes)

    if args.bundled:
        with zipfile.ZipFile(args.reference / '_internal/data/runtime-data.zip') as archive:
            profiles = json.loads(archive.read('data/local_static/skill/damage_element_catalog.json'))['skills']
            roots = json.loads(gzip.decompress(archive.read('data/local_static/buff/typed_roots.json.gz')))['entries']
        for key, profile in profiles.items():
            add('bundled/' + key, profile, roots.get(key, {}).get('root'), key)
    else:
        add('missing-profile', None)
        add('empty-profile', {})
        add('empty-key', dict(actions={'1': [unit()]}), canonical='')
        for index in (None, True, False, -1, 0, 1, 1.0, '0', 2**80):
            for mask in (None, True, False, -1, 0, 0x4000, 0x400000, 0x40004000, 2**64):
                value = unit()
                value.update(index=index, damageDecorateMask=mask, ignoreDamageImmuneLevel='None')
                add(f'index-mask/{len(cases)}', dict(actions={'1': [value]}))
        for action in ('-1', '+1', ' 1 ', '1_0', '1.0', '1e0', '', 'bad', '١', '1__0'):
            add('action/' + action, dict(actions={action: [unit()]}))
        for element in ('physical', 'fire', 'pulse', 'cryst', 'natural', 'ether', 'real', 'Fire', '', None):
            for attribute in ('hp', 'poise', 'HP', '', None):
                value = unit()
                value.update(element=element, damageAttribute=attribute)
                add(f'element/{element}/{attribute}', dict(actions={'1': [value]}))
        add('duplicate-index', dict(actions={'1': [unit(), unit()]}))
        add('duplicate-numeric-actions', dict(actions={'1': [unit()], '+1': [unit()]}))
        for direct in (None, 0, -1, 16, 32, True):
            for root_mask in (None, 0, 16, '16', 16.0, True):
                value = unit()
                value.update(damageDecorateMask=direct, ignoreDamageImmuneLevel='None')
                root_unit = dict(damageDecorateMask=root_mask, ignoreDamageImmuneLevel='None',
                                 damageType=' FIRE ', damageAttributeType=' HP ')
                root = dict(serverActionIndex='1', damageUnits=[root_unit])
                add(f'static/{len(cases)}', dict(actions={'1': [value]}), root)
                add(f'static-conflict/{len(cases)}', dict(actions={'1': [value]}),
                    dict(a=root, b=dict(serverActionIndex=1, damageUnits=[dict(root_unit, damageDecorateMask=64)])))
        for calculation in (None, {}, [], {'source': 'untrusted', 'sourceProof': {}},
                            {'a': [-0.0, 2**80, {'b': None}], 'multiplier': 'x'}):
            value = unit(damageCalculation=calculation)
            value.update(byteOffset=8, byteEnd=32)
            add('calculation/' + str(len(cases)), dict(actions={'1': [value]},
                proof=dict(sourceBytes=64, consumedBytes=64, sourceSha256='synthetic', sourceAsset='synthetic.bin')))
        rng = random.Random(20261027)
        for index in range(120):
            units = []
            for _ in range(rng.randrange(1, 5)):
                value = unit()
                value.update(index=rng.choice([0, 1, True, None, -1, 1.0]),
                    element=rng.choice(['fire', 'physical', 'ether', None]),
                    damageAttribute=rng.choice(['hp', 'poise']),
                    damageDecorateMask=rng.choice([None, -1, 16, 0x4000]),
                    ignoreDamageImmuneLevel=rng.choice(['None', None, 'Other']))
                units.append(value)
            add('random/' + str(index), dict(actions={'1': units}))
        masks = [None, True, False, '16', -1, 0, 1.0, 1, 8, 16, 32, 0x4000, 0x100000,
                 0x400000, 0x40004000, 2**64 - 1, 2**64]
        for runtime in masks:
            for static in (None, -1, 0, 16, 0x4000, 0x40004000, 2**64):
                for source in (None, 'stale', 'current_typed_skill_or_buff_exact_unit_generation_only'):
                    for previous, previous_source in ((False, None), (True, None),
                                                     (True, 'stale'), (True, 'caller_supplied_classification')):
                        hit = dict(damage_decorate_mask=runtime, static_damage_decorate_mask=static,
                                   static_damage_decorate_mask_source=source,
                                   arts_strength_damage_observed=previous, arts_strength_damage_source=previous_source)
                        arts._is_arts_strength_damage_hit(hit)
                        expected = {key: value for key, value in hit.items() if key.startswith('arts_strength_')}
                        cases.append(dict(name='arts/' + str(len(cases)), kind='arts',
                            input=dict(runtime=runtime, static=static, source=source, previous=previous, previous_source=previous_source),
                            expected=encode(expected)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases), source_head=metadata['head'],
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Skill damage fixtures:', len(cases))


if __name__ == '__main__':
    main()
