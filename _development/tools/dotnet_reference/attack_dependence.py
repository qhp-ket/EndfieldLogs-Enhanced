"""Freeze attack dependency classification from the immutable Python allocation model."""
import argparse
import copy
import gzip
import hashlib
import importlib
import itertools
import json
from pathlib import Path
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/attack-dependence.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed attack dependence reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    model = importlib.import_module('parser_core.allocation.attack_model')
    original_loader = model._load_skill_action_damage_units
    cases = []

    def add(label, hit, units=None):
        config = copy.deepcopy(dict(hit=hit, units=units or {}))
        calls = []

        def load(skill):
            calls.append(skill)
            return config['units']

        model._load_skill_action_damage_units = load
        owned = copy.deepcopy(config['hit'])
        try:
            kind, calculation = model.observed_attack_dependence(owned)
            result = dict(kind=kind, calculation=calculation, calls=calls)
            if owned['attack_damage_dependency'] != kind:
                raise AssertionError('Reference dependency assignment changed')
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            result = dict(error=type(exc).__name__, calls=calls)
        cases.append(dict(name=f'{len(cases):05d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    def calc(kind='AtkScaleCalculation', **kwargs):
        return dict(source='current_typed_damage_unit', simpleCalculation=False,
                    atkCalculation=dict({'$type': 'Beyond.Gameplay.Core.' + kind}, **kwargs))

    def unit(calculation, attribute='hp'):
        return dict(index=0, damage_attribute_type=attribute, damage_calculation=calculation)

    calculations = [None, {}, [], False, 1, 'invalid']
    for source, simple, custom in itertools.product(
            [None, '', 'other', 'current_typed_damage_unit'], [None, True, False, 0, 1, '', [], {}],
            [None, {}, [], False, 0, '', 'invalid', [1], 2, {'$type': []}, {'$type': {}}, {'$type': 'unknown'},
             {'$type': 'Beyond.Gameplay.Core.AtkScaleCalculation'}]):
        calculation = dict(source=source, simpleCalculation=simple, atkCalculation=custom)
        calculations.append(calculation)
        add('direct-shape', dict(damage_calculation=calculation, skill_key='chr_test_skill'))
    for kind in ['AtkScaleCalculation', 'BreakingAttackCalculation', 'DefiniteValueCalculation', 'PrimaryAttrCalculation', 'Other']:
        calculations.append(calc(kind))
        add('typed-kind', dict(damage_calculation=calc(kind)))
    for attr, owner, addition in itertools.product([None, 'Atk', 'MaxHp', [], {}],
            [None, 'AttackerOrHealer', 'Defender', [], {}],
            [None, {}, [], 'invalid', [1], {'useBlackboardKey': False, 'value': 0}, {'useBlackboardKey': True, 'value': 0}]):
        calculation = calc('MultiplyAttributeCalculation', attributeType=attr, valueSource=owner, addition=addition)
        add('multiply-target', dict(damage_calculation=calculation))
    for flag, value in itertools.product([None, True, False, 0, 1],
            [None, 0, -0., 1, '0', ' 0 ', 'invalid', False, True, [], {}, float('nan'), float('inf'), 10**500]):
        calculation = calc('MultiplyAttributeCalculation', attributeType='Atk', valueSource='AttackerOrHealer',
                           addition=dict(useBlackboardKey=flag, value=value))
        calculations.append(calculation)
        add('affine-addition', dict(damage_calculation=calculation))
    linear, independent = calc(), calc('DefiniteValueCalculation')
    affine = calc('MultiplyAttributeCalculation', attributeType='Atk', valueSource='AttackerOrHealer')
    for skill in [None, '', 'chr_test_skill', 12, True, [], ['x'], {}]:
        add('missing-field', dict(skill_key=skill), {'0': [unit(independent)]})
        for value in [None, [], 0, '', 'invalid']:
            add('present-empty', dict(skill_key=skill, damage_calculation=value))
            add('fallback-linear', dict(skill_key=skill, damage_calculation=value), {'0': [unit(linear)]})
    for left, right, attribute in itertools.product([linear, independent, affine, {}, None],
            [linear, independent, affine, {}, None], ['hp', 'energy', 'HP', '']):
        add('fallback-consensus', dict(damage_calculation=None, skill_key='test'),
            {'0': [unit(left)], '9': [unit(right, attribute)]})
    for calculation in calculations:
        add('fallback-calculation', dict(damage_calculation=None, skill_key='chr_test_skill'), {'0': [unit(calculation)]})
    if args.bundled:
        relative = '_internal/data/runtime-data.zip'
        digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed runtime data changed')
        dependencies[relative] = digest
        with zipfile.ZipFile(args.reference / relative) as archive:
            skills = json.loads(archive.read('data/local_static/skill/damage_element_catalog.json'))['skills']
            roots = json.loads(gzip.decompress(archive.read('data/local_static/buff/typed_roots.json.gz')))['entries']
        damage = importlib.import_module('parser_core.catalog.skill_damage')
        damage._canonical_packet_skill_id = lambda skill: skill
        damage._load_official_skill_damage_catalog = lambda: skills
        damage._load_current_buff_roots = lambda: {key: row['root'] for key, row in roots.items()}
        for skill in sorted(skills):
            units = original_loader(skill)
            if not units:
                continue
            add('resource-' + skill, dict(skill_key=skill, damage_calculation=None), units)
            for action, values in units.items():
                for index, item in enumerate(values):
                    if item.get('damage_attribute_type') == 'hp':
                        add(f'resource-{skill}-{action}-{index}', dict(skill_key=skill,
                            damage_calculation=item.get('damage_calculation')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Attack dependence fixtures:', len(cases))


if __name__ == '__main__':
    main()
