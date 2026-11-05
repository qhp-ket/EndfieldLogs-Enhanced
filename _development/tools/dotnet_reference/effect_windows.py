"""Compare exact hit-time effect evaluation, including persistent quality flags."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
from types import ModuleType


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    target = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/effect-windows.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed effect evaluation reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    evaluation = importlib.import_module('parser_core.effects.evaluation')

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        return value

    cases = []
    state_keys = {'_enable_state_unobserved_at_hit', '_effect_state_unresolved_at_hit', '_buff_enabled_at_hit',
        'rdps_snapshot_order_unresolved', 'rdps_unresolved_enable_evidence', 'rdps_invalid_dynamic_evaluation'}
    def point(ts=1500, line=30, seq=None, session=None):
        return dict(hit_ts_ms=ts, line_no=line, packet_seq_id=seq, packet_session_id=session)
    positions = [point(ts, line) for ts, line in itertools.product([999, 1000, 1500, 2000, 2001], [None, 0, 9, 10, 39, 40])]
    packet_positions = [point(ts, line, seq, session) for ts, line, seq, session in
        itertools.product([1000, 1500, 2000], [None, 30], [None, 0, 7, 8, 99, 2**65], [None, 's', 'other'])]
    base = dict(start_ts_ms=1000, end_ts_ms=2000, start_line_no=10, end_line_no=40,
        zone_effects=[dict(zone='amp', element='all', rate=.2)])

    def add(window, samples=None, label='window'):
        current = copy.deepcopy(window)
        samples = copy.deepcopy(positions if samples is None else samples)
        steps = []
        unchanged = encode({key:value for key,value in window.items() if key not in state_keys})
        for position in samples:
            result = evaluation._window_effects_at_ts(current, **position)
            if encode({key:value for key,value in current.items() if key not in state_keys}) != unchanged:
                raise AssertionError('Reference modified source evidence')
            steps.append(encode(dict(effects=result, state={key:value for key,value in current.items() if key in state_keys})))
        cases.append(dict(name=f'{label}/{len(cases)}', window_json=json.dumps(window, ensure_ascii=True), positions=samples, expected=steps))

    add(base)
    add({})
    for changes in [dict(start_ts_ms=None), dict(end_ts_ms=None), dict(start_line_no=0), dict(end_line_no=None),
            dict(snapshot_update=True), dict(snapshot_end_ts_ms=1500), dict(rdps_conflicting_enable_state=True),
            dict(requires_enable_observation=True), dict(_buff_enabled_at_hit=False, _effect_state_unresolved_at_hit=True),
            dict(rdps_invalid_dynamic_evaluation=True, rdps_snapshot_order_unresolved=True)]:
        add(dict(base, **changes))
    enabled = dict(ts_ms=1100, line_no=20, operationSeq=7, enabled=True)
    disabled = dict(ts_ms=1300, line_no=30, operationSeq=8, enabled=False)
    for observations in [[enabled], [disabled], [enabled, disabled], [disabled, enabled],
            [enabled, dict(enabled, line_no=21, enabled=False)],
            [enabled, dict(enabled, line_no=21)], [dict(enabled, ts_ms=1800), disabled]]:
        for required in (False, True):
            add(dict(base, enable_observations=observations, requires_enable_observation=required), packet_positions, 'enable')
    dynamic = dict(zone='amp', element='all', base_rate=.3, condition=dict(type='always'),
        external_rdps_allowed=True, rdps_whitelist_keys=['approved'])
    for rate in [None, 0, -1, .1, 1, False, True, '0.2', 'nan', float('nan'), float('inf'), -0.0]:
        add(dict(base, dynamic_effects=[dict(dynamic, base_rate=rate)]), label='dynamic-base')
    for field, values in dict(tick_rate=[None, 0, .1, '0.2', float('nan')], delayed_add_rate=[None, 0, .2], element=[None, '', 'fire']).items():
        for value in values:
            add(dict(base, dynamic_effects=[dict(dynamic, **{field:value})]), label='dynamic-field')
    for points, source in itertools.product([[], [[1000, .2], [1500, .5]], [[1500, .5], [1000, .2]],
            [[1501, .5]], [[999, -.1], [1500, 0]], [[1000, float('nan')]],
            [[1000, .1], [1100, .2], [1200, .3]], [None, [1000], [1000, .2, .3], [1500, .4]]],
            [None, 'guessed', 'typed_runtime_dynamic_action']):
        add(dict(base, dynamic_effects=[dict(dynamic, observed_points=points, observed_points_source=source)]), label='dynamic-points')
    keyword = dict(dynamic, keyword_session_id='s', keyword_rate_snapshots=[])
    observed = dict(ts_ms=1100, line_no=20, operation_seq=7, session_id='s', status='observed', rate_after=.5)
    for snapshots in [[], [observed], [dict(observed, status='conflict')], [dict(observed, rate_after=None)],
            [dict(observed, rate_after=-.1)], [dict(observed, session_id='other')],
            [dict(observed, operation_seq=8, line_no=30, rate_after=.8), observed],
            [observed, dict(observed, line_no=21, rate_after=.7)]]:
        add(dict(base, dynamic_effects=[dict(keyword, keyword_rate_snapshots=snapshots)]), packet_positions, 'keyword')
    for rate in (None, -.1, 0, .1):
        add(dict(base, dynamic_effects=[dict(keyword, base_rate=rate)]), packet_positions, 'keyword-base')
    parameter = dict(zone='res', element='fire', external_rdps_allowed=True, rdps_whitelist_keys=['approved'], parameter_keys=['a','b','c'], parameter_snapshots=[])
    snapshot = dict(ts_ms=1100, line_no=20, operation_seq=7, session_id='s', status='attribute_parameters_observed',
        bb_values=dict(a=-.1,b=-.2,c=-.3))
    for snapshots in [[], [snapshot], [dict(snapshot, status='invalid')], [dict(snapshot, session_id='other')],
            [dict(snapshot, session_id=None, identity=dict(sessionId='s'))],
            [dict(snapshot, operation_seq=8, line_no=30, bb_values=dict(a=-.2,b=-.3,c=-.4)), snapshot]]:
        add(dict(base, dynamic_effects=[dict(parameter, parameter_snapshots=snapshots)]), packet_positions, 'parameter')
    for values in [{}, dict(a=None,b=-.2,c=-.3), dict(a=.1,b=-.2,c=-.3), dict(a=False,b=0,c=0),
            dict(a=-0.0,b=0,c=0), dict(a=-1e308,b=-1e308,c=0), dict(a='-.1',b='-.2',c='-.3'),
            dict(a=-1e16,b=-1,c=-1), dict(a=-.1,b=-.1,c=-.1)]:
        add(dict(base, dynamic_effects=[dict(parameter, parameter_snapshots=[dict(snapshot, bb_values=values)])]), packet_positions, 'parameter-values')
    for specifications in [[dynamic, keyword], [keyword, dynamic], [dynamic, parameter],
            [dict(dynamic, base_rate=0), dynamic], [dynamic, dict(dynamic, tick_rate=1)],
            [dict(keyword, keyword_rate_snapshots=[observed]), dict(parameter, parameter_snapshots=[snapshot])]]:
        add(dict(base, dynamic_effects=specifications), packet_positions, 'atomic-effects')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    target.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        steps=sum(len(case['positions']) for case in cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Effect window fixtures:', len(cases), 'steps:', sum(len(case['positions']) for case in cases))


if __name__ == '__main__':
    main()
