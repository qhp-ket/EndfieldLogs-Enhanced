"""Freeze packet guard identity and exact target BUFF matching from the fixed allocation reference."""
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/packet-allocation.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed packet allocation reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    packet = importlib.import_module('parser_core.allocation.packet_evidence')
    identity = importlib.import_module('parser_core.effects.window_identity')
    if packet._BUFF_SKILL_FILTER:
        raise ValueError('Fixed skill filter contract requires migration')
    cases = []

    def add(kind, label, **config):
        # JSON transports named NaN, not its originating IEEE payload or sign.
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        try:
            if kind == 'allowed':
                result = sorted(packet._packet_attr_allowed_effects(owned['tokens']))
            elif kind == 'bucket':
                result = packet._dpd_bucket_value_for_zone(owned['zone'], owned['raw'])
            elif kind == 'uids':
                result = dict(aliases=sorted(identity._window_uid_aliases(owned['window'])),
                    matches=packet._window_matches_packet_uids(owned['window'], set(owned['uids'])))
            elif kind == 'row':
                result = identity._effect_row_signature(owned['effect'])
            elif kind == 'guard':
                result = packet._packet_modifier_guard_signature(owned['effect'])
            elif kind == 'condition':
                result = identity._effect_condition_signature(owned['effect'])
            elif kind == 'round':
                result = round(owned['value'], owned['places'])
            elif kind == 'active':
                result = sorted(packet._active_target_buff_ids_for_hit(owned['hit'], owned['records'], side=owned['side']))
            else:
                matches = packet._matched_packet_defender_effect_signatures(hit=owned['hit'], buff_windows=owned['windows'],
                    defender_modifier_uids=set(owned['uids']))
                result = dict(signatures=list(matches), windows=owned['windows'])
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            result = dict(error=type(exc).__name__)
        cases.append(dict(name=f'{len(cases):05d}-{kind}-{label}', kind=kind,
            config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    for token in list(range(-2, 100)) + ['32:abc', ' 32 :x', '٣٢:x', '3_2:x', '32.0', 'True', True, None, [], {}, 'bad']:
        add('allowed', 'attribute', tokens=[token, '50:x', '50:y'])
    for zone, values in itertools.product(['dmg_inc', 'amp', 'combo', 'vuln_taken', 'fragile', 'atk', 'unknown'],
            [None, [], [1], [1, 2, 3, 4, 5, 6], [0, 'nan', 0, 'inf', False, True],
             [0, None, 0, 'bad', {}, []], [0, 10**500], '0123456']):
        add('bucket', 'shape', zone=zone, raw=dict(atk_zones=values, def_zones=values))
    for uid, aliases, uids in itertools.product([None, '', 'a', 1, False],
            [None, [], ['a', 'b', 'a', None, '', False, 0, 1], 'abc'], [[], ['a'], ['1'], ['missing']]):
        add('uids', 'aliases', window=dict(uid=uid, uid_aliases=aliases), uids=uids)
    for condition in [None, {}, [], dict(b=1, a=2), {'中文': ['\n', '\u0001', '"', '\\', '𐀀', '\ue000', -0., 1e-7, 1e16]},
            {'z': {'b': 1, 'a': [True, None, 1.25, float('inf'), float('nan')]}, '\ue000': 1, '𐀀': 2}]:
        add('condition', 'sorted-json', effect=dict(condition=condition))
    for value in [[['b'], ['a']], [[1], [2]], [[{}]], [None], [1, True, 0.5, -2], [10**500, 10**500 + 1],
            [1, 'a'], [None, None], [{}, {}]]:
        add('row', 'whitelist-types', effect=dict(rate=.2, rdps_whitelist_keys=value))
    for value in [[], ['fire'], {}, {'a': 1}, 1]:
        add('row', 'element-type', effect=dict(rate=.2, element=value))
        add('guard', 'element-type', effect=dict(rate=.2, element=value, bb_key='value'))
    for value in [2**53 - 1, 2**53 + 1, 2**53 + 3, 2**100 + 2**47 + 1, -(2**100 + 2**47 + 1)]:
        add('row', 'exact-integer-float', effect=dict(rate=value))
    for rate, zone, element in itertools.product([None, 0, -0., .1234565, .1234575, '0.25', True, 'bad', float('nan'), float('inf')],
            ['vuln_taken', None], [None, 'all', 'fire']):
        add('row', 'static', effect=dict(rate=rate, zone=zone, element=element))
        add('guard', 'static', effect=dict(rate=rate, zone=zone, element=element))
    for field, value in itertools.product(['bb_key', 'add_bb_key', 'delay_bb_key', 'tick_bb_key', 'max_bb_key', 'attr_type', 'condition'],
            [None, '', 0, False, 'x', '32', 32, 32.5, [], {}, {'type': 'unknown'}]):
        effect = dict(rate=.1234565, zone='vuln_taken', element='physical')
        effect[field] = value
        add('guard', 'key', effect=effect)
    for field, value in itertools.product(['base_rate', 'tick_rate', 'max_rate', 'delayed_add_rate', 'delay_sec', 'recipient_side',
            'external_rdps_allowed', 'rdps_whitelist_keys'], [None, 0, .1234565, .1234575, '0.2', 'invalid', True, ['b', 'a', 'a']]):
        effect = dict(zone='vuln_taken', base_rate=.1)
        effect[field] = value
        add('row', 'dynamic', effect=effect)
    for value, places in itertools.product([0., -0., .0000005, .1234565, .1234575, 2.675, 1.2345, -1.2345,
            float.fromhex('0x1.fffffffffffffp+1023'), float.fromhex('0x0.0000000000001p-1022'), float('inf'), float('nan')],
            [-400, -309, -308, -1, 0, 2, 4, 6, 308, 323, 324, 400]):
        add('round', 'boundary', value=value, places=places)
    rng = random.Random(20261028)
    for _ in range(500):
        value = struct.unpack('>d', rng.randbytes(8))[0]
        add('round', 'binary64', value=value, places=rng.choice([-309, -308, -10, -1, 0, 2, 4, 6, 15, 300, 323, 324]))
    base_hit = dict(character_key='chr_a', target_enemy_key='enemy', source_actor_id='a1', target_actor_id='e1',
        ts_ms=1000, line_no=10, skill_key='skill', packet_seq_id=50, packet_modifier_uids=dict(attacker=[], defender=[]))
    base_record = dict(target_enemy_key='enemy', target_actor_id='e1', uid='u1', ts_ms=900, line_no=1,
        event_key='buff', raw_event_key='123', raw_duration_ms=500)
    for side, actor, uid, end, end_line, duration, mode in itertools.product(['defender', 'attacker'],
            ['e1', '', 'other'], [False, True], [None, 999, 1000, 1001], [0, 9, 10, 11], [None, 0, 100, 101, 500],
            [None, 'Infinity']):
        hit = copy.deepcopy(base_hit)
        record = dict(base_record, target_actor_id=actor, end_ts_ms=end, end_line_no=end_line, raw_duration_ms=duration, lifetime_mode=mode)
        if side == 'attacker':
            record.update(target_enemy_key='', target_character_key='chr_a')
            if actor == 'e1':
                record['target_actor_id'] = 'a1'
        if uid:
            hit['packet_modifier_uids'][side] = ['u1']
        add('active', 'lifetime-identity', hit=hit, records=[record], side=side)
    for field, value in itertools.product(['ts_ms', 'line_no', 'snapshot_end_ts_ms', 'snapshot_end_line_no',
            'target_enemy_key', 'target_actor_id', 'event_key', 'raw_event_key'], [None, 0, 9, 10, 11, 999, 1000, 1001, '1000', False]):
        record = dict(base_record)
        record[field] = value
        add('active', 'record-boundary', hit=base_hit, records=[record], side='defender')
    window = dict(uid='u1', uid_aliases=['u2'], target_character_key='enemy', start_ts_ms=900, end_ts_ms=1100,
        start_line_no=1, event_key='buff', zone_effects=[dict(zone='vuln_taken', rate=.2), dict(zone='atk', rate=.3)])
    for field, value, uids in itertools.product(['target_character_key', 'start_ts_ms', 'end_ts_ms', 'start_line_no',
            'end_line_no', 'event_key', 'skill_family_key'], [None, '', 0, 1, 9, 10, 11, 999, 1000, 1001, 'skill', 'buff'],
            [[], ['u1'], ['u2'], ['unknown']]):
        row = dict(window)
        row[field] = value
        add('matches', 'window-boundary', hit=base_hit, windows=[row], uids=uids)
    for flag, observations, seq in itertools.product([False, True],
            [[], [dict(ts_ms=900, line_no=1, operationSeq=49, enabled=False)],
             [dict(ts_ms=1000, line_no=11, operationSeq=51, enabled=True)],
             [dict(ts_ms=900, line_no=1, operationSeq=49, enabled=True)]], [None, 48, 49, 50, 51]):
        add('matches', 'enable-observation', hit=dict(base_hit, packet_seq_id=seq),
            windows=[dict(window, requires_enable_observation=flag, enable_observations=observations)], uids=['u1'])
    for start, end, start_line, end_line, hit_line in itertools.product([999, 1000, 1001], [999, 1000, 1001],
            [0, 9, 10, 11], [0, 9, 10, 11], [0, 9, 10, 11]):
        add('matches', 'exact-order', hit=dict(base_hit, line_no=hit_line),
            windows=[dict(window, start_ts_ms=start, end_ts_ms=end, start_line_no=start_line, end_line_no=end_line)], uids=['u1'])
    add('matches', 'duplicate-guard', hit=base_hit, windows=[dict(window, zone_effects=[
        dict(zone='vuln_taken', rate=.1, bb_key='v'), dict(zone='vuln_taken', rate=.5, bb_key='v')]), window], uids=['u1'])
    add('matches', 'unhashable-guard', hit=base_hit, windows=[dict(window, zone_effects=[
        dict(zone='vuln_taken', rate=.2, recipient_side=['invalid'])])], uids=['u1'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Packet allocation fixtures:', len(cases))


if __name__ == '__main__':
    main()
