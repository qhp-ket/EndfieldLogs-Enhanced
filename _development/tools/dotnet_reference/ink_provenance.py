"""Freeze the recorded-ink state machine from the verified Python source snapshot."""
import argparse
import copy
import gzip
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import random
import struct
import sys
from types import ModuleType
import zipfile


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
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/ink-provenance.json'
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
    ink = importlib.import_module('parser_core.ink_provenance')
    fields = importlib.import_module('parser_core.ingestion.fields')
    def action(index, kind, **values):
        return dict(serverActionIndex=index, isEnable=True, **{'$type': 'Beyond.Gameplay.Core.' + kind + '.Data'}, **values)
    def operand(key):
        return dict(useBlackboardKey=True, blackboardKey=key)
    root = {'actions': [action(45, 'SaveDamageContext', saveTo='ink_damage', valueType='RealValue'),
        action(46, 'SimpleCalcBBAction', key='ink_damage2', operation='Multiply', value1=operand('ink_damage'), value2=operand('ink_damage_rate')),
        action(47, 'SimpleCalcBBAction', key='EntityBB_ink_damage', operation='Add', value1=operand('EntityBB_ink_damage'), value2=operand('ink_damage2')),
        action(14, 'LaunchProjectile'), action(15, 'ModifyDynamicBlackboard', key='EntityBB_ink_damage', operation='Assign', value={'value': 0})]}
    cases = []
    def add(name, operation, **config):
        config = dict(operation=operation, **config)
        config.setdefault('roots', {ink.BUFF: root})
        # JSON is the actual compatibility boundary; calculate the reference after that roundtrip.
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        try:
            if operation == 'profile':
                result = ink._profile(owned.get('root'))
            elif operation == 'weights':
                result = ink._record_weights(owned['source'], owned['increment'])
            elif operation == 'apply':
                summary = ink.apply_ink_provenance(owned['text'], owned['hits'], owned['records'], root_lookup=owned['roots'], extract_fields=fields._extract_fields)
                result = dict(hits=owned['hits'], summary=summary)
            else:
                stream = ink._ink_provenance_ingestion(root_lookup=owned['roots'], extract_fields=fields._extract_fields)
                next(stream)
                result = []
                for step in owned['steps']:
                    if step.get('reset'):
                        stream.close()
                        stream = ink._ink_provenance_ingestion(root_lookup=owned['roots'], extract_fields=fields._extract_fields)
                        next(stream)
                    summary = stream.send((step['lines'], step['hits'], step['records']))
                    result.append(copy.deepcopy(dict(hits=step['hits'], summary=summary)))
                stream.close()
        except (ValueError, TypeError, OverflowError, KeyError, AttributeError, ZeroDivisionError) as error:
            result = {'error': type(error).__name__}
        cases.append(dict(name=f'{len(cases):04d}-{name}', config_json=json.dumps(config, ensure_ascii=True, separators=(',', ':')), expected=canonical(result)))

    for value in [None, {}, root, {'nested': root}, {'list': [root]}, {'serverActionIndex': 0, 'isEnable': False, 'children': root}]:
        add('profile', 'profile', root=value)
    for index, field, value in itertools.product(range(5), ['isEnable', 'serverActionIndex', '$type', 'key', 'operation', 'value', 'value1', 'value2'],
                                                [None, False, 0, 1, 'wrong', {}, {'useBlackboardKey': 1, 'blackboardKey': 'ink_damage'}]):
        changed = copy.deepcopy(root)
        changed['actions'][index][field] = value
        add('profile-change', 'profile', root=changed)
    for index in range(5):
        changed = copy.deepcopy(root)
        changed['actions'].append(copy.deepcopy(changed['actions'][index]))
        add('profile-duplicate', 'profile', root=changed)

    source = dict(character_key='attacker', packet_final_value=120, rdps_contributions={'attacker': 100, 'support': 20})
    for increment, shares, raw in itertools.product([0, -1, .000001, 12, 72], [{}, {'attacker': 120}, {'attacker': 100, 'support': 20},
            {'attacker': 100, 'support': 10, ink.OWNER: 10}, {'attacker': 0, 'support': 120}, {'attacker': 200, 'negative': -20},
            {'attacker': 2**70, 'support': 2**69}, {'attacker': 100., 'a': float('inf')}], [0, 120, -120, None]):
        add('weights', 'weights', source=source | dict(rdps_contributions=shares, packet_final_value=raw), increment=increment)
    for nested in [None, {}, {'attacker': 120}]:
        add('weights-nested', 'weights', source=source | {'_ink_allocation': nested}, increment=12)

    class Trace:
        def __init__(self):
            self.lines = ['[10:00:00.000] CONTEXT']
            self.hits = []
            self.records = [dict(event_key=ink.BUFF, uid='7001', source_character_key=ink.OWNER, source_actor_id='4001', target_actor_id='3001',
                line_no=1, packet_creation_contexts=[dict(session_id='test', operation_seq=1)])]
        def line(self, body):
            self.lines.append('[10:00:00.000] ' + body)
            return len(self.lines)
        def source(self, seq=100, value=120, shares=None, tick=1000, session='test'):
            hit = dict(line_no=self.line('SOURCE'), seq=len(self.hits) + 1, character_key='attacker', packet_session_id=session, packet_seq_id=seq,
                client_tick_ms=tick, target_actor_id='3001', packet_final_value=value, rdps_contributions=shares if shares is not None else {'attacker': 100, 'support': 20})
            self.hits.append(hit)
            return hit
        def dynamic(self, seq, action, value, tick=1000, session='test', **change):
            identity = dict(schemaVersion=1, sessionId=session, operationSeq=seq, ownerType='1', ownerId='3001', environmentInstId='7001',
                templateType='Buff', actionId=action, clientTickMs=str(tick), triggerType=0, actionType=7,
                actionRuntimeCase='modify_dynamic_blackboard_action', operationPayloadCase='trigger_action_op_data') | change
            return self.line(f'BB_MODIFY_DYNAMIC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={ink.BUFF} actionId={action} value={value!r} identity=' + json.dumps(identity, separators=(',', ':')))
        def accumulate(self, seq=102, previous=0, increment=12, final=None, tick=1000, action=47):
            return self.line(f'BB_SIMPLE_CALC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={ink.BUFF} actionId={action} '
                f'key=EntityBB_ink_damage valueA={previous} valueB={increment} final={previous+increment if final is None else final}')
        def release(self, seq=130, projectile='8001', legacy=False):
            if legacy:
                self.dynamic(seq - 1, 13, 0)
                self.line(f'ACTOR_MAP id={projectile} template={ink.OWNER} source=launch_projectile skill=None')
                self.line(f'SKILL_CAST_START seq={seq+1} startMs=1000 inst=8002 ownerId={projectile} skill={ink.EXPLOSION}')
            else:
                self.line('INK_RELEASE ' + json.dumps(dict(schema_version=1, template_key=ink.BUFF, action_id=14, session_id='test', operation_seq=seq,
                    buff_uid='7001', owner_id='3001', source_actor_id='4001', projectile_id=projectile, client_tick_ms=1000)))
            self.dynamic(seq + 2, 15, 0)
        def explosion(self, value=12, **change):
            hit = dict(line_no=self.line('EXPLOSION'), seq=len(self.hits) + 1, character_key=ink.OWNER, target_actor_id='3001', source_actor_id='4001',
                packet_session_id='test', packet_seq_id=140, event_owner_id='8001', event_inst_id='8002', client_tick_ms=1000, skill_key=ink.EXPLOSION,
                packet_final_value=value, hit_value=value, rdps_contributions={ink.OWNER: value}, damage_calculation={'atkCalculation': {'value': operand('EntityBB_ink_damage')}}) | change
            self.hits.append(hit)
            return hit
        def freeze(self, name, chunks=None, roots=None, separator='\n'):
            if chunks is None:
                config = dict(text=separator.join(self.lines), hits=self.hits, records=self.records)
                # Allow deliberate missing/unverified profile cases.
                if roots is not None:
                    config['roots'] = roots
                add(name, 'apply', **config)
            else:
                steps = []
                start = 0
                for stop in [*chunks, len(self.lines)]:
                    steps.append(dict(lines=list(enumerate(self.lines[start:stop], start + 1)), hits=[hit for hit in self.hits if hit['line_no'] <= stop], records=self.records))
                    start = stop
                add(name, 'stream', steps=steps)
    rng = random.Random(20261028)
    for legacy, effective, records_count in itertools.product([False, True], [None, 0, 6, 12], [1, 2, 5]):
        trace = Trace()
        total = 0
        for i in range(records_count):
            raw = [120, 300, 180, 500, 200][i]
            baseline = [100, 200, 100, 250, 200][i]
            increment = [12, 60, 18, 50, 20][i]
            trace.source(100 + i*5, raw, {'attacker': baseline, 'support': raw-baseline})
            trace.dynamic(101 + i*5, 45, raw)
            trace.accumulate(102 + i*5, total, increment)
            total += increment
        trace.release(130, legacy=legacy)
        trace.explosion(total, hit_value=total if effective is None else effective)
        trace.freeze('records-and-overkill')
        trace.freeze('chunk-records', chunks=[2, 4, len(trace.lines)-1])
    for _ in range(80):
        trace = Trace()
        raw = rng.uniform(.01, 20000)
        baseline = raw / rng.uniform(1, 5)
        increment = raw * rng.uniform(.01, 2)
        trace.source(value=raw, shares={'attacker': baseline, 'support': raw-baseline})
        trace.dynamic(101, 45, raw)
        trace.accumulate(increment=increment)
        trace.release()
        trace.explosion(increment)
        trace.freeze('numeric-weights')
    for fault in ['missing', 'ambiguous', 'tick', 'session', 'rounded', 'nested', 'unknown-attribution']:
        trace = Trace()
        if fault != 'missing':
            hit = trace.source(value=120.000004 if fault == 'rounded' else 120, tick=999 if fault == 'tick' else 1000, session='other' if fault == 'session' else 'test')
            if fault == 'nested': hit['_ink_allocation'] = {'attacker': 120}
            if fault == 'unknown-attribution': hit['rdps_unresolved_effect_conditions'] = True
        if fault == 'ambiguous': trace.source()
        trace.dynamic(101, 45, 120)
        trace.accumulate()
        trace.release()
        trace.explosion()
        trace.freeze('source-' + fault)
    for field, value in itertools.product(['packet_session_id', 'target_actor_id', 'source_actor_id', 'event_owner_id', 'event_inst_id', 'packet_seq_id', 'damage_calculation'],
                                         [None, '', 'other', 0, 130, 131]):
        trace = Trace()
        trace.source()
        trace.dynamic(101, 45, 120)
        trace.accumulate()
        trace.release(legacy=field == 'event_inst_id')
        trace.explosion(**{field: value})
        trace.freeze('explosion-context')
    for field, values in [('event_key', ['other']), ('uid', ['other']), ('source_character_key', ['other']), ('source_actor_id', [None, '']),
            ('target_actor_id', [None, '']), ('rdps_live_identity_conflict', [True]), ('end_line_no', [1, 3, 99]),
            ('packet_creation_contexts', [[], [{'session_id': None}], [{'session_id': 'a'}, {'session_id': 'b'}], [{'session_id': 'test'}, {'session_id': 'test'}]])]:
        for value in values:
            trace = Trace()
            trace.records[0][field] = value
            trace.source(); trace.dynamic(101, 45, 120); trace.accumulate(); trace.release(); trace.explosion()
            trace.freeze('record-binding')
    for field, value in itertools.product(['schemaVersion', 'sessionId', 'operationSeq', 'ownerType', 'ownerId', 'environmentInstId', 'templateType', 'actionId', 'clientTickMs',
                                         'triggerType', 'actionType', 'actionRuntimeCase', 'operationPayloadCase'], [None, False, True, 'wrong', 999]):
        trace = Trace()
        trace.source(); trace.dynamic(101, 45, 120, **{field: value}); trace.accumulate(); trace.release(); trace.explosion()
        trace.freeze('operation-identity')
    for previous, increment, final in itertools.product([0, 12, 30, -1, float('nan')], [0, 12, -1, float('inf')], [12, 42, -1, float('inf')]):
        trace = Trace()
        trace.source(); trace.dynamic(101, 45, 120); trace.accumulate(previous=previous, increment=increment, final=final); trace.release(); trace.explosion(final)
        trace.freeze('accumulator')
    for mode in ['duplicate', 'conflict', 'out-of-order', 'missing-identity', 'invalid-json', 'wrong-session', 'kill-bonus', 'duplicate-release', 'consume-twice', 'missing-release', 'profile', 'reset-inflight']:
        trace = Trace()
        trace.source(); trace.dynamic(101, 45, 120); trace.accumulate()
        if mode == 'duplicate': trace.accumulate()
        if mode == 'conflict': trace.accumulate(increment=13)
        if mode == 'out-of-order': trace.accumulate(seq=99)
        if mode == 'missing-identity': trace.line(f'BB_SIMPLE_CALC inst=7001 ownerId=3001 skill={ink.BUFF} actionId=47')
        if mode == 'invalid-json': trace.line(f'BB_MODIFY_DYNAMIC seq=110 tick=1000 inst=7001 ownerId=3001 skill={ink.BUFF} actionId=45 value=120 identity={{')
        if mode == 'wrong-session': trace.line(f'BB_SIMPLE_CALC seq=110 tick=1000 inst=7001 ownerId=3001 skill={ink.BUFF} actionId=47 packetSessionId=wrong')
        if mode == 'kill-bonus': trace.accumulate(seq=110, previous=12, increment=3, action=66)
        if mode != 'missing-release': trace.release()
        if mode == 'duplicate-release': trace.release(seq=135)
        if mode == 'reset-inflight':
            trace.source(seq=150, value=200, shares={'attacker': 200}); trace.dynamic(151, 45, 200); trace.accumulate(152, 0, 20); trace.release(160, '9001')
        trace.explosion(15 if mode == 'kill-bonus' else 12, packet_seq_id=170)
        if mode == 'consume-twice': trace.explosion(packet_seq_id=180)
        if mode == 'reset-inflight': trace.explosion(20, packet_seq_id=180, event_owner_id='9001')
        trace.freeze(mode, roots={} if mode == 'profile' else None)
        for boundary in range(1, len(trace.lines)):
            trace.freeze('chunk-' + mode, chunks=[boundary])
    trace = Trace()
    trace.source(); trace.dynamic(101, 45, 120); trace.accumulate(); trace.release(); trace.explosion()
    for separator in ['\r\n', '\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029']:
        trace.freeze('line-boundary', separator=separator)
    trace.freeze('no-hits', chunks=[])
    add('no-explosion', 'apply', text='unrelated', hits=[], records=[])
    steps = [dict(lines=list(enumerate(trace.lines, 1)), hits=trace.hits, records=trace.records),
             dict(reset=True, lines=list(enumerate(trace.lines, 1)), hits=trace.hits, records=trace.records)]
    add('explicit-reset', 'stream', steps=steps)
    if args.bundled:
        relative = '_internal/data/runtime-data.zip'
        digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed runtime archive changed')
        dependencies[relative] = digest
        with zipfile.ZipFile(args.reference / relative) as archive:
            bundled = json.loads(gzip.decompress(archive.read('data/local_static/buff/typed_roots.json.gz')))['entries'][ink.BUFF]['root']
        add('bundled-profile', 'profile', root=bundled)
        add('bundled-recording', 'apply', roots={ink.BUFF: bundled}, text='\n'.join(trace.lines), hits=trace.hits, records=trace.records)
        add('bundled-chunking', 'stream', roots={ink.BUFF: bundled}, steps=steps)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Ink provenance fixtures:', len(cases))


if __name__ == '__main__':
    main()
