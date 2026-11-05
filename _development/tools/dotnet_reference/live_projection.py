"""Freeze native overlay/full-summary projections from the fixed computation reference."""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import random
import sys
from types import ModuleType

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/live-projection.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed live projection reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    unified = importlib.import_module('parser_core.unified')
    summary = importlib.import_module('parser_core.realtime.live_summary')
    cases = []

    def add(label, report, maxima=None):
        for kind, function in [('overlay', unified.overlay_snapshot_from_report), ('summary', summary.summary_from_report)]:
            config = dict(report=copy.deepcopy(report))
            kwargs = {}
            if maxima is not None:
                config['maxima'] = maxima
                kwargs['rdps_max' if kind == 'overlay' else 'maxima'] = maxima
            result = function(report, **kwargs)
            cases.append(dict(name=f'{len(cases):04d}-{label}-{kind}', kind=kind,
                config_json=json.dumps(config), expected=canonical(result)))

    def base(duration=1000):
        return dict(battle=dict(duration_ms=duration, total_damage=60, total_dps=60.0,
            roster=[], time_source='game_timer', timer_integrity_ok=True, timer_integrity_reasons=[],
            timer_window_valid=True, timer_start_inferred=False, private_evidence='excluded'),
            participants=[dict(character_key='a', character_name='Alpha', total_damage=60, total_rd=40.0, rdps=40.0)],
            timeline_events=[dict(rdps_contributions=[dict(character_key='a', value=12.3456)])],
            rdps_preflight=dict(ok=True, blocker_count=0, blockers=[]),
            rdps_damage_basis=dict(rdps_preflight_ok=True, rdps_strict_ok=True, rdps_conservation_ok=True,
                hit_count=1, unresolved_damage_actor_count=0, missing_packet_hit_count=0, hit_conservation_mismatch_count=0))

    for duration in [0, 1, 499, 500, 501, 1000, 3333, 90000]:
        add('duration', base(duration))
    add('direct-maxima', base(), dict(a=7.125, support=300))
    report = base()
    report['participants'] += [dict(character_key='a', character_name='Duplicate', total_rd=19.0), dict(character_key='')]
    add('duplicate-key', report)
    report = base()
    del report['participants'][0]['total_rd']
    report['participants'][0]['rdps'] = 17.5
    report['loadout'] = [dict(slot=2, character_key='z'), dict(slot=1, character_key='support', character_name='Support'),
                         dict(slot=0, character_key='a'), dict(slot=3, character_key='support')]
    add('legacy-rate-and-roster', report)
    report = base()
    report['loadout'] = [dict(slot=1, character_key='\ue000'), dict(slot=1, character_key='😀')]
    add('unicode-sort', report)
    for key in ['rdps_preflight', 'rdps_damage_basis', 'timeline_events', 'participants']:
        report = base()
        del report[key]
        add('missing-' + key, report)
    rng = random.Random(20261029)
    for index in range(100):
        report = base(rng.choice([1, 500, 501, 3333, 90000]))
        keys = ['a', 'b', 'support']
        report['participants'] = [dict(character_key=key, character_name=key, total_rd=rng.uniform(0, 1e9),
            total_damage=rng.randrange(10**9), max_hit=rng.randrange(10**6)) for key in keys[:rng.randrange(4)]]
        report['loadout'] = [dict(character_key=key, slot=slot) for slot, key in enumerate(keys, 1)]
        report['timeline_events'] = [dict(rdps_contributions=[dict(character_key=key, value=rng.uniform(-100, 1e5))
            for key in keys]) for _ in range(rng.randrange(8))]
        if index % 3 == 0:
            report['rdps_preflight'].update(ok=False, blocker_count=1, blockers=[dict(code='synthetic')])
        add('mixed-roster', report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Live projection fixtures:', len(cases))


if __name__ == '__main__':
    main()
