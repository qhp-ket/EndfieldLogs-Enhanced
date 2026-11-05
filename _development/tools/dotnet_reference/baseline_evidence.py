"""Freeze exact character levels, target HP state and integer ratios from the fixed reference."""
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
import tempfile
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/baseline-evidence.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed baseline reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    prefix = '_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    resources = importlib.import_module('parser_core.catalog.resources')
    static = importlib.import_module('parser_core.allocation.static_loadout')
    enemy = importlib.import_module('parser_core.effects.enemy_status')
    cases = []
    queries = [dict(character='chr_test', level=level) for level in [None, False, True, -1, 0, 1, 1., '1', 2, 3, 4, 90]]

    def add(label, operation='character', **fields):
        config = dict(operation=operation)
        config.update(fields)
        original = copy.deepcopy(config)
        try:
            if operation == 'character':
                with tempfile.TemporaryDirectory(prefix='endfield-baseline-reference-') as directory:
                    root = Path(directory)
                    for name, text in config['files'].items():
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(text, encoding='utf8')
                    resources._repo_root = lambda: root
                    resources._load_character_base_stat_catalog.cache_clear()
                    catalog = resources._load_character_base_stat_catalog()
                    result = dict(catalog=catalog, lookups=[static._character_base_stats(row['character'], row['level']) for row in config['queries']])
            elif operation == 'hp':
                result = copy.deepcopy(config['hits'])
                enemy._annotate_hit_enemy_hp_state(result)
            else:
                result = config['numerator'] / config['denominator']
        except (TypeError, ValueError, OverflowError, AttributeError, KeyError, ZeroDivisionError) as exc:
            result = dict(error=type(exc).__name__)
        assert json.dumps(original, sort_keys=True) == json.dumps(config, sort_keys=True)
        cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    def row(level=1, attack=100, **changes):
        value = dict(breakStage=0, Attribute=dict(attrs=[dict(attrType=0, attrValue=level), dict(attrType=2, attrValue=attack)]))
        value.update(changes)
        return value

    def character(rows, **changes):
        raw = dict(mainAttrType=39, subAttrType=40, attributes=rows)
        raw.update(changes)
        return dict(raw=raw)

    def charcase(label, payload, **fields):
        files = {'data/local_tables/character/items/chr_test.json': json.dumps(payload, ensure_ascii=True)}
        add(label, files=files, queries=queries, **fields)

    for level, attack, stage in itertools.product([None, False, True, -1, 0, 1, 1.5, 2, '1', '2.0', 'bad'],
            [0, 1, 100.5, '100.5', None], [None, 0, '2.0', True]):
        charcase('coercion', character([row(level, attack, breakStage=stage)]))
    for rows in [[], [None, False], [dict(Attribute=[])], [row(), row()],
            [row(), row(attack=101), row()], [row(), row(attack=101), row(2)],
            [row(Attribute=dict(attrs=[dict(attrType=0, attrValue=1), dict(attrType=0, attrValue=1.5), dict(attrType=2, attrValue=120)]))],
            [row(Attribute=dict(attrs=[dict(attrType=0, attrValue=1), dict(attrType=2, attrValue=99), dict(attrType=2, attrValue=120)]))],
            [row(Attribute=dict(attrs=[dict(attrType=0, attrValue=1), dict(attrType=True, attrValue=100), dict(attrType=2.9, attrValue=50)]))]]:
        charcase('duplicates-and-level-markers', character(rows))
    for payload in [{}, [], None, dict(raw=[]), dict(raw=dict(attributes={})), dict(raw=dict(attributes=[dict(Attribute=None)]))]:
        charcase('malformed-container', payload)
    for value in [float('inf'), float('-inf'), float('nan'), 'nan', 'Infinity', 2**1025]:
        charcase('special-value', character([row(value), row(1, value)]))
    for value in [float('nan'), 'nan', '-nan', float('inf'), -0.0]:
        charcase('special-value-duplicate', character([row(1, value), row(1, value)]))
    charcase('full-fields', character([row(Attribute=dict(attrs=[dict(attrType=key, attrValue=key + .25) for key in [0, 1, 2, 3, 39, 40, 41, 42]])), row(90, 140)]))
    add('missing-and-invalid-json', files={'data/local_tables/character/items/chr_invalid.json': '{',
        'data/local_tables/character/items/other.json': json.dumps(character([row()]))}, queries=queries)

    def hit(**changes):
        value = dict(target_enemy_key='enemy', target_actor_id='1', enemy_hp_after=90, hit_value=10)
        value.update(changes)
        return value

    for actor, after, damage, maximum in itertools.product([None, 0, '0', '01', 1, '1', '2', '1a', True, '1\u0662'],
            [None, True, -1, 0, 90, '90.0', 90.5], [-10, 0, 10, None, True], [None, 0, 100, '100.0']):
        add('hp-coercion', 'hp', hits=[hit(target_actor_id=actor, enemy_hp_after=after, hit_value=damage, target_enemy_max_hp=maximum)])
    for sequence in [[90, 80, 50, 0], [90, 95, 80, -10], [0, 0, 50], [-10, -20], [90, None, 80], [90, 'bad', '80.0']]:
        add('observed-transitions', 'hp', hits=[hit(enemy_hp_after=value, target_enemy_max_hp=100) for value in sequence])
    add('same-template-two-actors', 'hp', hits=[hit(enemy_hp_after=90), hit(target_actor_id='2', enemy_hp_after=200), hit(enemy_hp_after=80), hit(target_actor_id='2', enemy_hp_after=150)])
    add('template-fallback', 'hp', hits=[hit(target_actor_id='0'), hit(target_actor_id=None, enemy_hp_after=70), hit(target_enemy_key='other', target_actor_id=None, enemy_hp_after=150)])
    add('missing-target-still-carries-observed-actor', 'hp', hits=[hit(), hit(target_enemy_key='', enemy_hp_before=40, target_enemy_max_hp=100)])
    add('observed-max-is-not-explicit', 'hp', hits=[hit(enemy_hp_after=90), hit(enemy_hp_after=50), hit(enemy_hp_after=120)])
    for power in [53, 64, 1024, 4096]:
        add('large-target-hp', 'hp', hits=[hit(enemy_hp_after=2**power + 1, target_enemy_max_hp=2**power + 20), hit(enemy_hp_after=0, hit_value=2**power + 1)])
    for numerator, denominator in [(0, 1), (0, -1), (1, 3), (-1, 3), (1, -3), (-1, -3), (1, 0),
            (2**4096, 2**4096 + 1), (2**4096 + 1, 3), (1, 2**1074), (1, 2**1075), (3, 2**1075),
            (2**53 + 1, 2**53), (2**53 + 3, 2**53), (2**1024 - 2**970, 1), (2**1024 - 2**971, 1)]:
        add('exact-ratio-boundary', 'ratio', numerator=numerator, denominator=denominator)
    randomizer = random.Random(20261028)
    for _ in range(200):
        numerator = randomizer.getrandbits(randomizer.randint(0, 4200)) * randomizer.choice([-1, 1])
        denominator = (randomizer.getrandbits(randomizer.randint(1, 4200)) or 1) * randomizer.choice([-1, 1])
        add('exact-ratio', 'ratio', numerator=numerator, denominator=denominator)
    if args.bundled:
        archive = '_internal/data/runtime-data.zip'
        pinned(archive)
        with zipfile.ZipFile(args.reference / archive) as bundle:
            for name in bundle.namelist():
                if name.startswith('data/local_tables/character/items/chr_') and name.endswith('.json'):
                    key = Path(name).stem
                    add('bundled-character-' + key, files={name: bundle.read(name).decode('utf8')},
                        queries=[dict(character=key, level=level) for level in range(0, 101)])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Baseline evidence fixtures:', len(cases))


if __name__ == '__main__':
    main()
