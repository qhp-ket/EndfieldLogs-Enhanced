"""Freeze proven clock-only projection and semantic membership guards from the fixed source."""
import argparse
import copy
from datetime import date, datetime
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/live-clock.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed live clock reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    clock = importlib.import_module('parser_core.realtime.live_summary').clock_summary
    offset = int(datetime(2026, 10, 29).astimezone().utcoffset().total_seconds() / 60)
    cases = []
    previous = dict(battle=dict(time_source='game_timer', official_timer_start_seen=True, official_timer_end_seen=False,
        timer_window_valid=True, duration_ms=1000, total_damage=120, roster=[]),
        participants=[dict(character_key='a', character_name='Alpha', total_damage=100, total_rd=60., dps=100., rdps=60., max_rd=20.),
                      dict(character_key='b', character_name='Beta', total_damage=20, total_rd=60., dps=20., rdps=60., max_rd=30.),
                      dict(character_key='zero', character_name='Zero', total_damage=0., total_rd=0., dps=0., rdps=0.)],
        quality_summary=dict(status='provisional', evidence='preserve'))
    state = dict(official_timer_start_ms=1000, reference_date='2026-10-29')

    def add(label, before=None, changes=None, timer='[00:00:02.500] LIVE_TIMER_TICK elapsedMs=1500\n'):
        source = copy.deepcopy(before if before is not None else previous)
        captured = dict(state, **(changes or {}))
        actual_state = dict(captured, reference_date=date.fromisoformat(captured['reference_date']))
        result = clock(source, actual_state, timer)
        cases.append(dict(name=f'{len(cases):04d}-{label}', kind='clock', config_json=json.dumps(dict(previous=source, state=captured,
            timer=timer, offset_minutes=offset)), expected=canonical(result)))

    for elapsed in [999, 1000, 1500, 3333, 86400001]:
        add('elapsed', timer=f'[00:00:02.500] LIVE_TIMER_TICK elapsedMs={elapsed}\n')
    add('missing-timer', timer=None)
    add('missing-start', changes=dict(official_timer_start_ms=None))
    for key, value in [('time_source', 'fallback'), ('official_timer_start_seen', False), ('official_timer_end_seen', True),
                       ('timer_window_valid', None), ('duration_ms', 0)]:
        changed = copy.deepcopy(previous)
        changed['battle'][key] = value
        add('unproven-' + key, before=changed)
    for key in ['hits', 'buff_starts', 'unresolved_hits', 'unresolved_buff_actions', 'skill_casts', 'dynamic_bb_events']:
        for stamp in [None, 1999, 2000, 2001]:
            add('membership-' + key, changes={key: [dict(ts_ms=stamp)]})
    rng = random.Random(20261029)
    for index in range(50):
        changed = copy.deepcopy(previous)
        changed['battle']['duration_ms'] = rng.choice([1, 499, 500, 501, 1000, 3333])
        changed['participants'] = [dict(character_key=str(i), character_name=name, total_damage=rng.randrange(100),
            total_rd=rng.uniform(0, 1e6), dps=0., rdps=0.) for i, name in enumerate(['\ue000', '😀', 'Alpha'])]
        add('rates-and-order', before=changed, timer=f'[00:00:02.500] LIVE_TIMER_TICK elapsedMs={changed["battle"]["duration_ms"]+index}\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Live clock fixtures:', len(cases))


if __name__ == '__main__':
    main()
