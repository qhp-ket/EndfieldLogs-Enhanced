"""Freeze canonical detailed-hit projection and packet damage conservation."""
import argparse
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace


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
    args = parser.parse_args()
    fixture_dir = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixture_dir / 'report-accounting.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    basis = importlib.import_module('parser_core.allocation.basis')
    details = importlib.import_module('parser_core.reporting.hit_details')
    selection = importlib.import_module('parser_core.allocation.stack_selection')
    rules = importlib.import_module('parser_core.effects.stacking_rules')
    identity = importlib.import_module('parser_core.effects.window_identity')
    resistance = importlib.import_module('parser_core.allocation.resistance')
    attack = importlib.import_module('parser_core.allocation.attack_model')
    debug = importlib.import_module('parser_core.allocation.debug')
    explanation = importlib.import_module('parser_core.allocation.explanation')
    current = {}
    for module in (selection, rules, identity, resistance):
        module._load_current_buff_roots = lambda: current.get('roots', {})
    rules._load_local_buff_semantic_entries = lambda: {}
    rules._load_weapon_buff_stack_limits = lambda: {}
    attack._load_skill_action_damage_units = lambda _: {}
    debug._resolve_character_name = lambda key: current.get('names', {}).get(key, key) if key else None
    explanation._resolve_character_name = debug._resolve_character_name
    explanation._collect_buff_labels = lambda record: record.get('test_labels', [])
    cases = []
    def add(name, operation, **config):
        config = dict(operation=operation, **config)
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        current.clear()
        current.update(owned)
        try:
            if operation == 'basis':
                result = basis._build_rdps_damage_basis(owned['hits'], owned['totals'], owned['total_damage'])
            else:
                for hit, numeric in zip(owned['hits'], owned['numeric_baselines']):
                    if numeric:
                        hit.setdefault('baseline', {}).update({int(key): value for key, value in numeric.items()})
                rows = details.build_debug_hits(SimpleNamespace(hits=owned['hits'], buff_starts=owned['records']), owned['windows'])
                result = dict(hits=[{key: value for key, value in hit.items() if key != 'baseline'} for hit in rows], windows=owned['windows'])
        except (ValueError, TypeError, OverflowError, KeyError, AttributeError) as error:
            result = {'error': type(error).__name__}
        cases.append(dict(name=f'{len(cases):04d}-{name}', config_json=json.dumps(config, ensure_ascii=True, separators=(',', ':')), expected=canonical(result)))

    source = fixture_dir / 'allocation-hit.json'
    for row in json.loads(source.read_text(encoding='utf8')):
        config = json.loads(row['config_json'])
        records = config['records'] or [record for rows in (config.get('buff_records') or {}).values() for record in rows]
        add('details-' + row['name'], 'details', hits=[config['hit']], numeric_baselines=[config['numeric_baseline']], windows=config['windows'], records=records,
            roots=config.get('roots', {}), names=config.get('names', {}))
    for raw, final, packet_hit, overkill in itertools.product([None, 0, -120.12345], [None, 0, -100.98765], [None, 0, 100], [0, 20]):
        add('packet-basis', 'basis', hits=[dict(hit_value=100, rdps_contributions={'a': 80, 'b': 20}, packet_raw_value=raw, packet_final_value=final,
            packet_hit_value=packet_hit, overkill_damage=overkill)], totals={'a': 80, 'b': 20}, total_damage=100)
    for first, second in itertools.product([0, .009, .01000001, -30, 30, float('nan'), float('inf')], repeat=2):
        add('conservation', 'basis', hits=[dict(hit_value=50, rdps_contributions={'a': 50+first}), dict(hit_value=50, rdps_contributions={'a': 50+second})],
            totals={'a': 100+first+second}, total_damage=100)
    for values in [{}, {'a': None}, {'a': False}, {'a': '12.5'}, {'a': 10**400}, {'a': float('inf'), 'b': float('-inf')},
                   {'a': 10**100, 'b': -10**100, 'c': 1.23456789}]:
        add('numeric-basis', 'basis', hits=[dict(hit_value=100, rdps_contributions=values)], totals=values, total_damage=100)
    for count in [0, 1, 100]:
        add('count-and-total', 'basis', hits=[dict(hit_value=10**20, rdps_contributions={'a': 10**20}) for _ in range(count)],
            totals={'a': count*10**20}, total_damage=count*10**20)
    add('empty', 'basis', hits=[], totals={}, total_damage=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies,
        inputs={source.name: hashlib.sha256(source.read_bytes()).hexdigest()}), indent=2), encoding='utf8')
    print('Report accounting fixtures:', len(cases))


if __name__ == '__main__':
    main()
