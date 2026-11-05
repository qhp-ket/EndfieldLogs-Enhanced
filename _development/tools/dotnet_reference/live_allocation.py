"""Freeze live allocation reuse, dependency invalidation, retraction and continuing ink accounting."""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixtures / 'live-allocation.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed live allocation reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    incremental = importlib.import_module('parser_core.realtime.incremental')
    ledger = importlib.import_module('parser_core.allocation.ledger')
    modules = [importlib.import_module('parser_core.' + name) for name in ('allocation.stack_selection', 'effects.stacking_rules',
        'effects.window_identity', 'allocation.resistance')]
    current = {}
    for module in [ledger, *modules]:
        module._load_current_buff_roots = lambda: current.get('roots', {})
    modules[1]._load_local_buff_semantic_entries = lambda: {}
    modules[1]._load_weapon_buff_stack_limits = lambda: {}
    importlib.import_module('parser_core.allocation.attack_model')._load_skill_action_damage_units = lambda _: {}
    debug = importlib.import_module('parser_core.allocation.debug')
    explanation = importlib.import_module('parser_core.allocation.explanation')
    debug._resolve_character_name = lambda key: current.get('names', {}).get(key, key) if key else None
    explanation._resolve_character_name = debug._resolve_character_name
    explanation._collect_buff_labels = lambda record: record.get('test_labels', [])
    cases = []

    def add(label, base, steps):
        current.clear()
        current.update(base)
        cache = incremental.AllocationFrontier()
        token = incremental.ACTIVE_ALLOCATION_CACHE.set(cache)
        expected = []
        try:
            for step in steps:
                hits = copy.deepcopy(step['hits'])
                for hit, baseline in zip(hits, step['numeric_baselines']):
                    hit['baseline'] = {int(key): value for key, value in baseline.items()}
                windows, records = copy.deepcopy(step['windows']), copy.deepcopy(step.get('records') or [])
                summary = {}
                totals = ledger._compute_rdps_damage_shares(hits, windows, records, trace_text=step.get('trace'), ink_summary=summary)
                diagnostics = dict(allocated_hits=cache.allocated_hits, reused_hits=cache.reused_hits,
                    total_allocated_hits=cache.total_allocated_hits, total_reused_hits=cache.total_reused_hits,
                    finalized_hits=len(cache.finalized), pending_start_line=cache.pending_start_line,
                    replays=cache.replays, last_replay_reason=cache.last_replay_reason,
                    ink_replays=cache.ink_replays, last_ink_replay_reason=cache.last_ink_replay_reason)
                expected.append(canonical(dict(hits=[{key: value for key, value in hit.items() if key != 'baseline'} for hit in hits],
                    windows=windows, totals=totals, summary=summary, diagnostics=diagnostics,
                    maxima=cache.maxima_prefix[-1] if cache.maxima_prefix else {})))
        finally:
            incremental.ACTIVE_ALLOCATION_CACHE.reset(token)
        cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(dict(base=base, steps=steps)), expected=expected))

    def hit(time, line, value=120, **extra):
        return dict(character_key='attacker', target_enemy_key='enemy', source_actor_id='1', target_actor_id='3',
            hit_value=value, ts_ms=time, line_no=line, damage_element='fire', damage_school='spell', **extra)
    window = dict(uid='u', event_key='buff', source_character_key='support', target_character_key='attacker',
        target_actor_id='1', start_ts_ms=900, end_ts_ms=3000, zone_effects=[dict(zone='dmg_inc', element='all', rate=.2)])
    def step(hits=None, windows=None, records=None):
        rows = hits if hits is not None else [hit(1000, 10), hit(1500, 20), hit(2000, 30)]
        return dict(hits=rows, numeric_baselines=[{} for _ in rows], windows=windows if windows is not None else [window], records=records or [])
    first = step()
    add('repeat-append-late-retract', {}, [first, copy.deepcopy(first), step(first['hits']+[hit(2500, 40)]),
        step(first['hits']+[hit(1200, 50)]), step([hit(1000, 10, 40)]), step([])])
    for field, value in [('end_ts_ms', 3500), ('end_ts_ms', 1400), ('start_ts_ms', 1100),
                         ('duration_ms', 500), ('target_actor_id', 'changed'), ('unknown_rule', 'changed')]:
        changed = copy.deepcopy(window)
        changed[field] = value
        add('window-' + field + '-' + str(value), {}, [first, step(windows=[changed]), first])
    future = dict(uid='future', ts_ms=2500, line_no=50, end_ts_ms=4000, target_character_key='attacker')
    past = dict(future, ts_ms=950)
    add('future-and-past-record', {}, [first, step(records=[future]), step(records=[past]), first])
    duplicate = copy.deepcopy(window)
    add('duplicate-identities', {}, [first, step(windows=[window, duplicate]), first])
    second = dict(window, uid='second', start_ts_ms=800, source_character_key='second')
    add('dependency-order', {}, [step(windows=[window, second]), step(windows=[second, window])])
    add('same-frame-and-unresolved-frontier', {}, [step([hit(1000, 10), hit(1000, 20)]),
        step([hit(1000, 10, rdps_unresolved_actor=True), hit(2000, 30)]), first])
    added = dict(ts_ms=2500, line_no=70, operationSeq=7, enabled=True)
    w = dict(window, enable_observations=[])
    add('future-observation', {}, [step(windows=[w]), step(windows=[dict(w, enable_observations=[added])]),
        step(windows=[dict(w, enable_observations=[dict(added, ts_ms=1000)])])])
    source = fixtures / 'damage-ledger.json'
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    seeds = json.loads(source.read_text(encoding='utf8'))
    ordinary = [row for row in seeds if '-single-' in row['name'] and 'error' not in row['expected']][:60]
    inks = [row for row in seeds if '-ink-connected-' in row['name'] and 'error' not in row['expected']][::15]
    for row in ordinary + inks:
        config = json.loads(row['config_json'])
        for index, item in enumerate(config['hits']):
            item.setdefault('ts_ms', 1000 + index*100)
            item.setdefault('line_no', index+1)
        base = {key: config[key] for key in ('roots', 'names') if key in config}
        steps = [config, copy.deepcopy(config)]
        add('existing-' + row['name'], base, steps)
        if 'trace' in config:
            lines = config['trace'].splitlines()
            chunks = []
            for limit in sorted({max(1, len(lines)//3), max(1, len(lines)*2//3), len(lines)}):
                chunk = copy.deepcopy(config)
                selected = [(hit, baseline) for hit, baseline in zip(config['hits'], config['numeric_baselines']) if hit['line_no'] <= limit]
                chunk.update(hits=[hit for hit, _ in selected], numeric_baselines=[baseline for _, baseline in selected],
                    records=[record for record in config['records'] if record.get('line_no', 0) <= limit], trace='\n'.join(lines[:limit]))
                chunks.append(chunk)
            chunks.append(copy.deepcopy(config))
            add('chunked-' + row['name'], base, chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies, fixture_dependencies={'damage-ledger.json': source_sha256}), indent=2), encoding='utf8')
    print('Live allocation fixtures:', len(cases))


if __name__ == '__main__':
    main()
