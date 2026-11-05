"""Freeze report timeline, cast export and grouped skill statistics from fixed Python code."""
import argparse
import copy
from collections import defaultdict
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import random
import sys
from types import ModuleType, SimpleNamespace

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/report-timeline.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    stats = importlib.import_module('parser_core.reporting.skill_stats')
    timeline = importlib.import_module('parser_core.reporting.timeline')
    clock = importlib.import_module('parser_core.reporting.window')
    char = 'chr_0001_test'
    normal = char+'_normal_skill'
    ultimate = char+'_ultimate_skill'
    for module in [stats, timeline]:
        module._resolve_character_name = lambda key: 'name-'+key
        module._resolve_skill_name = lambda key: 'skill-'+key
        module._canonical_num_table_skill_id = lambda *args: None
    stats._canonical_packet_skill_id = lambda key: key
    cases = []

    def hit(time, skill=normal, value=10, target='enemy'):
        return dict(ts_ms=time, line_no=1, character_key=char, character_name='Test', target_enemy_key=target, target_enemy_name='Enemy',
                    skill_key=skill, skill_family_key=skill, skill_name='Skill', hit_value=value, rdps_contributions={char: float(value)},
                    critical_context={'version': 1, 'status': 'unavailable', 'reasons': ['missing_critical_attributes']})

    def cast(time, skill=normal, end=None, **extra):
        return dict(ts_ms=time, source_character_key=char, skill=skill, end_ts_ms=end, **extra)

    def add(name, changes=None):
        config = dict(hits=[hit(1000), hit(1100)], casts=[], records=[], windows=[], atb=[], roster=[char],
                      participants=[{'character_key': char}], start=1000, end=7000, duration=6000, timer=False, families={}, roots={})
        config.update(copy.deepcopy(changes or {}))
        state = copy.deepcopy(config)
        stats._resolve_skill_profile = lambda key: {'family_skill_key': config['families'][key]} if key in config['families'] else None
        timeline._load_current_buff_roots = lambda: config['roots']
        gains = defaultdict(list)
        for row in state['atb']:
            if row.get('character_key') and row.get('reason') == 'AddValue' and row.get('delta') is not None and row['delta'] > 0:
                gains[row['character_key']].append(row['ts_ms'])
        report_state = SimpleNamespace(hits=state['hits'], skill_casts=state['casts'], buff_starts=state['records'], atb_gain_ms_by_char=gains)
        stats._assign_skill_timeline_group_keys(report_state.hits)
        scale = config['duration']/max(config['end']-config['start'], 1) if config['timer'] else 1.0
        battle = clock.BattleTimeline(config['start'], config['end'], scale)
        events = timeline.build_hit_events(report_state, battle)
        keys = timeline.append_non_damage_casts(report_state, battle, state['participants'], events)
        exported = timeline.export_casts(report_state, battle, keys)
        timeline.append_buff_events(report_state, battle, state['windows'], events)
        events.sort(key=lambda row: (row['ts_ms_from_start'], row['lane_type'], row['event_name']))
        atb = [{**{key: value for key, value in row.items() if key != 'ts_ms'}, 'ts_ms_from_start': battle.offset_ms_unclamped(row['ts_ms'])}
               for row in state['atb'] if config['start']-10_000 <= row['ts_ms'] <= config['end']]
        expected = dict(hits=state['hits'], events=events, skills=stats._build_role_skill_stats_from_timeline_groups(state['hits'], state['roster']),
                        casts=exported, atb=atb)
        cases.append(dict(name=f'{len(cases):03d}-{name}', config_json=json.dumps(config), expected=canonical(expected)))

    add('base')
    for skill, gap in itertools.product([normal, ultimate, char+'_ult_attack'], [1199, 1200, 1201, 4999, 5000, 5001]):
        add('group-gap', dict(hits=[hit(1000, skill), hit(1000+gap, skill), hit(999, skill, target='other')]))
    for delta, end, source in itertools.product([-12001, -12000, -1, 0, 50, 51], [None, 1200], [None, 'summon']):
        add('cast-match', dict(casts=[cast(1000+delta, end=end, skill_source=source)]))
    for suffix in ['_projhit', '_abilityrange', '_abilityentity', '_indicator', '_bomb', '_field', '_sheep', '_absorb', '_aura', '_marker', '']:
        add('cast-child', dict(casts=[cast(1000, skill=normal+suffix, end=1500)], families={normal+suffix: normal}))
    for time in [-9001, -9000, 999, 1000, 6999, 7000, 7001]:
        add('cast-export-bounds', dict(casts=[cast(time, skill=ultimate, end=time+500)]))
    for gap in [2999, 3000, 3001]:
        add('non-damage-debounce', dict(casts=[cast(1000, ultimate), cast(1000+gap, ultimate)]))
    for delta, reason in itertools.product([-1, 0, 1499, 1500, 1501], ['AddValue', 'Other']):
        add('energy-nearest-predecessor', dict(casts=[cast(1000), cast(1200, normal+'_a2')],
            atb=[dict(ts_ms=1200+delta, character_key=char, delta=1.0, reason=reason)]))
    for timer, duration in itertools.product([False, True], [1, 333, 5000]):
        add('clock-scale', dict(timer=timer, duration=duration, casts=[cast(900, end=1500)], atb=[dict(ts_ms=999, character_key=char, delta=1.0, reason='AddValue')]))
    for start, end, expiry in itertools.product([500, 1000, 7001], [1500, 7000, 8000], [None, 1300]):
        buff = dict(uid='buff', start_ts_ms=start, end_ts_ms=end, event_key='buff', event_name='Buff', source_character_key=char,
                    source_character_name='Test', target_character_key=char, target_character_name='Test', effects=[dict(zone='dmg_inc', rate=.2, element='all')])
        record = dict(uid='buff', event_key='buff', ts_ms=start, end_ts_ms=expiry, raw_duration_ms=2000)
        add('buff-visible-and-lifetime', dict(windows=[buff], records=[record], timer=True, duration=3000))
    add('buff-stacking-resource', dict(windows=[dict(uid='b', start_ts_ms=1000, end_ts_ms=7000, event_key='b', event_name='B',
            source_character_key=char, source_character_name='Test', target_character_key=char, target_character_name='Test',
            enable_observations=[dict(ts_ms=1500, line_no=2, enabled=False)], snapshot_update=True, end_is_observation_boundary=True)],
            roots={'b': {'stackingSettings': {'stackingType': 'Stack'}}}))
    add('unresolved-runtime-skills', dict(casts=[cast(1000, 'skill_123'), cast(2000, char+'_skill_123')]))
    add('missing-skill-key', dict(hits=[{**hit(1000), 'skill_key': None, 'skill_family_key': None}]))
    rng = random.Random(29)
    for _ in range(50):
        rows = [hit(rng.randrange(900, 8000), rng.choice([normal, ultimate]), rng.randrange(10000), rng.choice(['a', 'b'])) for _ in range(rng.randrange(1, 20))]
        add('unsorted-groups', dict(hits=rows, casts=[cast(rng.randrange(900, 7000), rng.choice([normal, ultimate]), end=7000) for _ in range(8)]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Report timeline fixtures:', len(cases))


if __name__ == '__main__':
    main()
