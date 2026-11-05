"""Freeze official timing, lifecycle membership and report coordinates from the fixed Python source."""
import argparse
import copy
from collections import Counter
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/report-lifecycle.json'
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
    timing = importlib.import_module('parser_core.reporting.timing')
    window = importlib.import_module('parser_core.reporting.window')
    timing._resolve_dungeon_context = lambda value: ('mapped-' + value, '关卡 ' + value)
    fields = ['game_timer_start_ms', 'game_timer_end_ms', 'game_timer_elapsed_ms', 'game_timer_window_elapsed_ms',
              'official_timer_start_ms', 'official_timer_end_ms', 'official_timer_elapsed_ms', 'live_timer_elapsed_ms',
              'packet_timer_elapsed_ms', 'first_hit_hint_ms', 'last_hit_hint_ms', 'first_party_action_ms',
              'dungeon_context_id', 'dungeon_context']
    flags = dict(timer_start_seen=False, timer_end_seen=False, timer_window_valid=True,
                 challenge_pass_confirmed=False, official_pass_confirmed=False, completion_source='')
    cases = []

    def hit(time, line, character='chr_0001_test', enemy='eny_test', value=10):
        return dict(ts_ms=time, line_no=line, character_key=character, character_name=character,
                    target_enemy_key=enemy, hit_value=value, crit_flag=0, skill_key='skill_test')

    base_hits = [hit(900, 2, 'other', 'enemy'), hit(1000, 4), hit(1100, 6), hit(1200, 8)]
    records = [dict(uid='expired', ts_ms=0, end_ts_ms=500, target_enemy_key='eny_test'),
               dict(uid='explicit', ts_ms=0, end_ts_ms=1000, target_enemy_key='eny_test'),
               dict(uid='duration', ts_ms=900, raw_duration_ms=100, target_enemy_key='eny_test'),
               dict(uid='packet', ts_ms=0, packet_modifier_last_seen_ts_ms=1001, target_enemy_key='eny_test'),
               dict(uid='unknown', ts_ms=0, target_enemy_key='eny_test'),
               dict(uid='party', ts_ms=0, target_character_key='chr_0001_test'),
               dict(uid='future', ts_ms=5000, target_enemy_key='eny_test')]

    def add(name, hits=None, buffs=None, text='', changes=None, observed=None, line_count=None):
        timer = {key: None for key in fields}
        timer.update(flags)
        timer.update(changes or {})
        config = dict(hits=copy.deepcopy(base_hits if hits is None else hits),
                      records=copy.deepcopy(records if buffs is None else buffs), timing=timer, text=text,
                      observed_times=observed, line_count=line_count, offsets=[-1, 0, 999, 1000, 1001, 1100, 1200, 1500])
        state = SimpleNamespace(**copy.deepcopy(timer), hits=copy.deepcopy(config['hits']), buff_starts=copy.deepcopy(config['records']),
                                timer_observed_times={} if observed is None else {int(key): value for key, value in observed.items()},
                                enemy_counter=Counter(row['target_enemy_key'] for row in config['hits']),
                                participant_totals={}, roster_order=[], roster_seen=set())
        before_hits = state.hits
        evidence, elapsed, scope = timing.apply_official_timing(state, text,
            SimpleNamespace(timer_lines=None, line_count=line_count) if line_count is not None else None)
        chosen = window.select_hit_window(state, evidence, scope) if state.hits else None
        scale = (max(state.game_timer_elapsed_ms if state.game_timer_elapsed_ms is not None else chosen.end_ms-chosen.start_ms, 1)
                 / max(chosen.end_ms-chosen.start_ms, 1) if chosen and chosen.has_game_timer else 1.0)
        result = dict(timing={key: getattr(state, key) for key in fields+list(flags)}, hits=state.hits, records=state.buff_starts,
                      official_evidence=evidence, observed_elapsed=elapsed,
                      window=vars(chosen) if chosen else None,
                      duration_ms=max(state.game_timer_elapsed_ms if state.game_timer_elapsed_ms is not None
                                      else chosen.end_ms-chosen.start_ms if chosen else 0, 1),
                      timeline_scale=scale,
                      offsets=[window.BattleTimeline(chosen.start_ms, chosen.end_ms, scale).offset_ms_unclamped(value)
                               for value in config['offsets']] if chosen else [],
                      rebuild_totals=bool(chosen and state.hits is not before_hits and state.participant_totals))
        cases.append(dict(name=f'{len(cases):03d}-{name}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    add('fallback')
    add('empty', hits=[])
    add('nonparty', hits=[hit(800, 1, 'other', 'enemy'), hit(900, 2, 'other', 'enemy')])
    for first, last, action in itertools.product([None, 0, 1000, 1300], [None, 1100, 86_399_999], [None, 950]):
        add('fallback-hints', changes=dict(first_hit_hint_ms=first, last_hit_hint_ms=last, first_party_action_ms=action))
    for start, end, elapsed in itertools.product([None, 0, 1000, 2000], [None, 1100], [None, 0, 100, 2000]):
        add('compatible-timer', changes=dict(game_timer_start_ms=start, game_timer_end_ms=end,
                                           game_timer_elapsed_ms=elapsed, game_timer_window_elapsed_ms=elapsed))
    add('rollover', hits=[hit(86_399_900, 1), hit(100, 2)], changes=dict(first_hit_hint_ms=86_399_900, last_hit_hint_ms=100))
    start = '[00:00:00.800] OFFICIAL_TIMER_START gameId=test source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=1'
    finish = '[00:00:01.300] OFFICIAL_TIMER_END gameId=test source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=300'
    for complete, pass_time, observed, live in itertools.product([False, True], ['300', '0', '-1', '1_000', '１２３'], [False, True], [None, 250]):
        lines = ['', start, '', 'hit', '', 'hit', '', 'hit', finish.replace('passTime=300', 'passTime='+pass_time) if complete else '']
        text = '\n'.join(lines)
        observations = {'2': 800, '9': 1300} if observed else {}
        add('official', text=text, observed=observations, changes=dict(live_timer_elapsed_ms=live))
    for marker in ['GAME_INST_LEAVE gameId=test', 'GAME_INST_RESTART gameId=other', 'GAME_TIMER_RESET',
                   'GAME_TIMER_RESET source=CAPTURE_SESSION_START']:
        add('boundary', text='\n'.join(['', start, '', '', marker, '', '', '', finish]), observed={'2': 800, '5': 1050, '9': 1300})
    add('official-line-not-clock', hits=[hit(50_000, 4), hit(100, 8)], text='\n'.join(['', start, '', '', '', '', '', '', finish]), observed={'2': 800, '9': 1300})
    add('ongoing-index', text='\n'.join(['', start]), line_count=100, observed={'2': 800})
    add('scoped-empty', text='\n'.join(['', '', '', '', '', '', '', '', start]), observed={'9': 1300})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Report lifecycle fixtures:', len(cases))


if __name__ == '__main__':
    main()
