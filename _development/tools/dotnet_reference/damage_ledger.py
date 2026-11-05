"""Freeze ordered allocation, temporal candidates and source-to-ink report accounting."""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import random
import struct
import sys
from types import ModuleType


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
    output = args.output or fixture_dir / 'damage-ledger.json'
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
    ledger = importlib.import_module('parser_core.allocation.ledger')
    selection = importlib.import_module('parser_core.allocation.stack_selection')
    rules = importlib.import_module('parser_core.effects.stacking_rules')
    identity = importlib.import_module('parser_core.effects.window_identity')
    resistance = importlib.import_module('parser_core.allocation.resistance')
    attack = importlib.import_module('parser_core.allocation.attack_model')
    debug = importlib.import_module('parser_core.allocation.debug')
    explanation = importlib.import_module('parser_core.allocation.explanation')
    fields = importlib.import_module('parser_core.ingestion.fields')
    indices = importlib.import_module('parser_core.condition_index')
    ink = importlib.import_module('parser_core.ink_provenance')
    current = {}
    for module in (ledger, selection, rules, identity, resistance):
        module._load_current_buff_roots = lambda: current.get('roots', {})
    rules._load_local_buff_semantic_entries = lambda: {}
    rules._load_weapon_buff_stack_limits = lambda: {}
    attack._load_skill_action_damage_units = lambda _: {}
    debug._resolve_character_name = lambda key: current.get('names', {}).get(key, key) if key else None
    explanation._resolve_character_name = debug._resolve_character_name
    explanation._collect_buff_labels = lambda record: record.get('test_labels', [])
    cases = []
    def add(name, **config):
        config.setdefault('operation', 'ledger')
        config.setdefault('roots', {})
        config.setdefault('numeric_baselines', [{} for _ in config.get('hits', [])])
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        current.clear()
        current.update(owned)
        try:
            if owned['operation'] == 'index':
                condition = indices.ConditionRecordIndex(owned['records'], fields._coerce_optional_int)
                windows = indices.EffectWindowIndex(owned['windows'])
                result = [dict(conditions=condition.candidates(target, stamp), windows=windows.candidates(stamp)) for target, stamp in owned['queries']]
            else:
                hits = owned['hits']
                for hit, baseline in zip(hits, owned['numeric_baselines']):
                    if baseline:
                        hit.setdefault('baseline', {}).update({int(key): value for key, value in baseline.items()})
                summary = {}
                totals = ledger._compute_rdps_damage_shares(hits, owned['windows'], condition_buff_records=owned.get('records'),
                    trace_text=owned.get('trace'), ink_summary=summary)
                result = dict(totals=totals, hits=[{key: value for key, value in hit.items() if key != 'baseline'} for hit in hits], windows=owned['windows'], summary=summary)
        except (ValueError, TypeError, OverflowError, KeyError, AttributeError, ZeroDivisionError) as error:
            result = {'error': type(error).__name__}
        cases.append(dict(name=f'{len(cases):04d}-{name}', config_json=json.dumps(config, ensure_ascii=True, separators=(',', ':')), expected=canonical(result)))

    hit_source = fixture_dir / 'allocation-hit.json'
    ink_source = fixture_dir / 'ink-provenance.json'
    for row in json.loads(hit_source.read_text(encoding='utf8')):
        config = json.loads(row['config_json'])
        add('single-' + row['name'], hits=[config['hit']], numeric_baselines=[config['numeric_baseline']], windows=config['windows'], records=config['records'],
            roots=config.get('roots', {}), names=config.get('names', {}))
    # Multi-hit order deliberately runs time backwards, reusing the same windows and records.
    normal = dict(seq=1, character_key='chr_a', target_enemy_key='enemy', source_actor_id='a1', target_actor_id='e1',
                  ts_ms=1000, line_no=10, hit_value=120, damage_element='fire', damage_school='spell')
    window = dict(uid='u1', event_key='buff', source_character_key='chr_b', target_character_key='chr_a', target_actor_id='a1',
                  start_ts_ms=900, start_line_no=1, end_ts_ms=1100, zone_effects=[dict(zone='dmg_inc', element='all', rate=.2)])
    for stamps in [[1000, 1100, 1200], [1200, 1000, 900, 1100, 899], [1000]*8, [1101, 1100, 900, 899, 1000]]:
        for records in [None, [], [dict(uid='c', event_key='condition', target_character_key='chr_a', ts_ms=900, end_ts_ms=1100)]]:
            add('ordered-hits', hits=[normal | dict(seq=i+1, ts_ms=stamp, line_no=i+10) for i, stamp in enumerate(stamps)], windows=[window], records=records)
    # Use the same fixed synthetic ink traces, but calculate each source's attribution through the real allocator first.
    for row in json.loads(ink_source.read_text(encoding='utf8')):
        config = json.loads(row['config_json'])
        if config['operation'] != 'apply':
            continue
        hits = []
        for source in config['hits']:
            hit = normal | dict(character_key=source['character_key'], source_actor_id='a1') | source
            if source.get('skill_key') != ink.EXPLOSION:
                hit['hit_value'] = abs(source.get('packet_final_value') or 0)
            hits.append(hit)
        source_window = window | dict(target_character_key='attacker', source_character_key='support')
        add('ink-connected-' + row['name'], hits=hits, windows=[source_window], records=config['records'], trace=config['text'], roots=config['roots'])

    rng = random.Random(20261028)
    choices = [None, 0, -1, 900, 1000, 1100, 1200, 2**80, '1000', 'invalid', True, 1000.9]
    for _ in range(180):
        records, windows = [], []
        for i in range(rng.randrange(0, 12)):
            record = dict(uid=str(i), ts_ms=rng.choice(choices), end_ts_ms=rng.choice(choices), raw_duration_ms=rng.choice(choices),
                          target_character_key=rng.choice(['chr_a', 'chr_b', '', None]), target_enemy_key=rng.choice(['enemy', '', None]))
            records.append(record)
            windows.append(dict(uid=str(i), start_ts_ms=rng.choice(choices), end_ts_ms=rng.choice(choices)))
        queries = [(rng.choice(['chr_a', 'chr_b', '', 'enemy']), stamp) for stamp in [0, 899, 900, 1000, 1100, 1200, 1000, 900, 2**80, 0]]
        add('temporal-index', operation='index', records=records, windows=windows, queries=queries)
    add('empty', hits=[], windows=[], records=[], trace='')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies,
        inputs={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [hit_source, ink_source]}), indent=2), encoding='utf8')
    print('Damage ledger fixtures:', len(cases))


if __name__ == '__main__':
    main()
