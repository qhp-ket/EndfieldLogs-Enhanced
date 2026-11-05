"""固定 Qt 参考的 BUFF 展示区间、层数及名称；不计算战斗效果。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    root = args.reference.resolve()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    relatives = ['_internal/src/endfield_pcap/' + name for name in (
        'analysis/battle/buffs/states.py', 'analysis/battle/buffs/labels.py',
        'data/skill_names.py', 'data/assets/skill_names_zh.json')]
    dependencies = {}
    for relative in relatives:
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if digest != manifest['files'][relative]['sha256']:
            raise ValueError('固定 BUFF 展示参考已变化：' + relative)
        dependencies[relative] = digest
    sys.path.insert(0, str(root / '_internal/src'))
    from endfield_pcap.analysis.battle.buffs.states import buff_tracks, buff_state_text
    from endfield_pcap.analysis.battle.buffs import labels
    names = {'buff_localized': '本地化效果'}
    labels._manifest_names = lambda: names
    cases = []
    stamps = [-1, 0, 25, 50, 75, 100, 150, 200, 300, 1000]

    def event(start=0, duration=100, uid='a', **changes):
        return dict(event_key='buff_test', source_character_key='a', source_character_name='甲', source_actor_id='1',
                    target_character_key='b', target_actor_id='2', ts_ms_from_start=start, duration_ms=duration,
                    buff_uid=uid, stacking_type='Stack', **changes)

    def add(name, rows):
        episodes = []
        for key, start, end, states, evidence in buff_tracks(copy.deepcopy(rows)):
            episodes.append(dict(key=key, start=start, end=end, states=states, evidence=evidence,
                summary=buff_state_text(states), at=[buff_state_text(states, stamp) for stamp in stamps]))
        expected = dict(episodes=episodes, names=[labels.buff_display_name(row) for row in rows], sources=[labels.buff_source_text(row) for row in rows])
        cases.append(dict(name=name, config_json=json.dumps(dict(events=rows, names=names, stamps=stamps), ensure_ascii=True), expected=canonical(expected)))

    add('empty', [])
    add('alias-chain', [event(uid='a', buff_uid_aliases=['b']), event(25, uid='b', buff_uid_aliases=['c']), event(50, uid='c')])
    add('short-refresh-no-revival', [dict(event(duration=1000), stacking_type='Refresh'), dict(event(50, 25, 'b'), stacking_type='Unique')])
    add('disable-enable-gap', [event(buff_enable_observations=[dict(at_ms=25, line_no=1, enabled=False), dict(at_ms=75, enabled=True)])])
    add('disable-latest-refresh', [dict(event(duration=1000), stacking_type='Refresh'), dict(event(50, 25, 'b', buff_enable_observations=[dict(at_ms=50, enabled=False)]), stacking_type='Refresh')])
    add('equal-time-enable-line', [event(buff_enable_observations=[dict(at_ms=25, line_no=5, enabled=True), dict(at_ms=25, line_no=4, enabled=False)])])
    add('actor-separated', [event(), dict(event(), source_actor_id='another'), dict(event(), target_actor_id='another')])
    add('unknown-identities', [event(uid=None), event(25, uid=''), event(50, uid=0)])
    add('wide-limit', [event(stack_limit=2 ** 100), event(25, uid='b', stack_limit='1')])
    add('lifetime-known', [event(buff_lifetime=dict(expiry_ms_from_start=1000))])
    add('lifetime-boundary', [event(buff_lifetime={}, actual_end_ms_from_start=1000)])
    add('observed-boundary', [event(end_is_observation_boundary=True)])
    add('names', [dict(event(), **changes) for changes in [
        dict(buff_display_name='真实名称', buff_name='次选名称'), dict(buff_display_name='buff_test', buff_name='test'),
        dict(event_key='buff_localized'), dict(event_name='增伤/攻击提升'), dict(event_name='效果/详细'),
        dict(buff_name='internal_code_name', source_weapon_name='已知武器'), dict(buff_name='\ufffd损坏'),
        dict(source_character_key='chr_0001_test', source_character_name='记录角色', source_skill_key='unknown_skill'),
        dict(source_character_key='', source_character_name='', source_weapon_name='weapon_code'),
        dict(buff_name='\x1c名称\x1f'), dict(buff_name='ASCII Name'), dict(event_key='buff_test', buff_name='test'),
    ]])
    rng = random.Random(20261030)
    for index in range(80):
        policy = rng.choice(['Stack', 'Refresh', 'Unique', 'EnhanceAndRefresh', None])
        rows = []
        for sequence in range(8):
            row = event(rng.choice([0, 25, 50, 100, 150]), rng.choice([-5, 0, 25, 100, 200]), rng.choice(['a', 'b', 'c', None, '']))
            row.update(stacking_type=policy if index % 2 else rng.choice(['Stack', 'Refresh', None]), stack_limit=rng.choice([None, 0, 1, 2, 5]),
                       source_actor_id=rng.choice(['1', '1', '2']), buff_uid_aliases=rng.choice([[], ['a', 'b'], [None, 'c']]))
            if sequence % 3:
                row['buff_lifetime'] = dict(expiry_ms_from_start=rng.choice([None, 200, 1000]))
                row['actual_end_ms_from_start'] = 1200
            if sequence % 2:
                row['buff_enable_observations'] = [dict(at_ms=stamp, line_no=sequence, enabled=rng.choice([True, False])) for stamp in [25, 75, 150]]
            row['end_is_observation_boundary'] = sequence % 4 == 0
            rows.append(row)
        add('states-' + str(index), rows)
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/buff-display.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('BUFF display:', len(cases))


if __name__ == '__main__':
    main()
