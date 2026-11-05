"""Freeze report observation binding and participant projections from the fixed Python source."""
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/report-projection.json'
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
    evidence = importlib.import_module('parser_core.reporting.evidence')
    poise = importlib.import_module('parser_core.reporting.poise')
    lifecycle = importlib.import_module('parser_core.effects.lifecycle')
    totals = importlib.import_module('parser_core.reporting.totals')
    participants = importlib.import_module('parser_core.reporting.participants')
    labels = {'a': '阿尔法', 'b': '贝塔', 'c': 'Gamma', 'supp': '辅助', 'emoji': '😀', 'private': '\ue000'}
    totals._resolve_character_name = lambda key: labels.get(key)
    totals._resolve_skill_name = lambda key: key
    cases = []

    def add_sources(name, changes=None):
        config = dict(operation='sources', hits=[dict(ts_ms=100, line_no=5, skill_key='skill', skill_family_key='family',
                      template_int_id=42, original_template_int_id=84)],
                      records=[dict(ts_ms=100, line_no=3, uid='i', target_actor_id='owner', event_key='skill')],
                      casts=[dict(ts_ms=100, line_no=2, end_ts_ms=200, end_line_no=10, owner_id='owner', skill_inst_id='i', skill='skill')],
                      dynamic=[dict(ts_ms=100, line_no=4, instance_id='i', owner_id='owner', skill_key='skill', value=.125)],
                      refresh=[dict(snapshot_status='old', snapshot=dict(status='conflicting_dynamic_operation'))],
                      poise=[], last_seen={'i': 300}, atb=[])
        config.update(copy.deepcopy(changes or {}))
        state = copy.deepcopy(config)
        for row in state['refresh']:
            if isinstance(row.get('snapshot'), dict):
                row['snapshot_status'] = row['snapshot']['status']
        poise._apply_poise_damage_events_to_hits(state['hits'], state['poise'])
        evidence.bind_dynamic_observations(state['hits'], state['records'], state['casts'], state['dynamic'])
        lifecycle._extend_buff_records_from_packet_modifiers(state['records'], state['last_seen'])
        expected = {key: state[key] for key in ['hits', 'records', 'casts', 'dynamic', 'refresh', 'poise', 'atb', 'last_seen']}
        cases.append(dict(name=f'{len(cases):03d}-{name}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(expected)))

    add_sources('ordinary-binding')
    for time, line in itertools.product([99, 100, 101, 199, 200, 201], [0, 2, 3, 4, 9, 10, 11]):
        add_sources('lifetime', dict(dynamic=[dict(ts_ms=time, line_no=line, instance_id='i', owner_id='owner', skill_key='skill')]))
    for end, end_line, snap, snap_line in [(100, 4, None, None), (200, 0, 100, 4), (None, None, 100, 4), (100, None, None, None)]:
        record = dict(ts_ms=100, line_no=3, uid='i', target_actor_id='owner', event_key='skill',
                      end_ts_ms=end, end_line_no=end_line, snapshot_end_ts_ms=snap, snapshot_end_line_no=snap_line)
        add_sources('snapshot-lifetime', dict(records=[record]))
    base_record = dict(ts_ms=0, line_no=1, uid='i', target_actor_id='owner', event_key='skill')
    base_cast = dict(ts_ms=0, line_no=1, end_ts_ms=200, end_line_no=10, owner_id='owner', skill_inst_id='i', skill='skill')
    for record_count, cast_count in itertools.product(range(3), range(3)):
        add_sources('ambiguous-or-missing', dict(records=[base_record] * record_count, casts=[base_cast] * cast_count))
    for field, values in [('owner_id', [None, '', 'other']), ('instance_id', [None, '', 'other']), ('skill_key', [None, '', 'other'])]:
        for value in values:
            event = dict(ts_ms=100, line_no=4, instance_id='i', owner_id='owner', skill_key='skill')
            event[field] = value
            add_sources('identity', dict(dynamic=[event]))
    add_sources('open-cast', dict(casts=[{**base_cast, 'end_ts_ms': None}]))
    add_sources('stale-binding-cleared', dict(hits=[dict(ts_ms=100, skill_key='other', dynamic_bb_observations=[dict(value=1)])],
                records=[{**base_record, 'dynamic_bb_events': [dict(value=2)]}], dynamic=[]))
    for source, numeric, original, time in itertools.product(['skill', 'family', 'other'], [None, 42], [None, 84], [99, 100, 101]):
        event = dict(ts_ms=time, source=source, source_int=numeric, orig_source_int=original, value=.1, current_value=17)
        add_sources('poise-exact-match', dict(poise=[event, {**event, 'value': .2}]))

    def add_participants(name, config):
        config = dict(dict(operation='participants', records=[], hits=[], roster=[], totals={}, allocated={}, loadouts={}, duration_ms=1000,
                           rebuild=True), **config)
        state = copy.deepcopy(config)
        if state['rebuild']:
            projected, _, roster, _, _ = totals._rebuild_hit_totals(state['hits'], state['records'])
        else:
            projected, roster = state['totals'], state['roster']
            for row in state['records']:
                key = row.get('source_character_key')
                if not key:
                    continue
                if key not in roster:
                    roster.append(key)
                participant = projected.setdefault(key, dict(character_key=key, total_damage=0, max_hit=0, crit_hits=0, hit_count=0))
                participant['character_name'] = labels.get(key) or key
        result, roster_projection = participants.build_participants(SimpleNamespace(roster_order=roster, participant_totals=projected),
                                                                   state['loadouts'], state['allocated'], state['duration_ms'])
        expected = dict(totals=dict(projected), roster=roster, participants=result, roster_projection=roster_projection)
        cases.append(dict(name=f'{len(cases):03d}-{name}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(expected)))

    def hit(time, char='a', skill='s', damage=10, target='enemy', critical=0, name=None):
        return dict(ts_ms=time, character_key=char, character_name=name, target_enemy_key=target,
                    skill_key=skill, skill_name=skill, hit_value=damage, crit_flag=critical)

    for gap in [0, 119, 120, 121]:
        add_participants('visual-group-boundary', dict(hits=[hit(0), hit(gap), hit(gap*2)], allocated={'a': 30.0}))
    add_participants('interleaved-targets', dict(hits=[hit(0), hit(50, target='second'), hit(100), hit(220), hit(341)], allocated={}))
    add_participants('support-and-loadout', dict(hits=[hit(0)], records=[dict(source_character_key='supp', target_character_key='c')],
                     allocated={'a': 5.0, 'supp': 5.0}, loadouts={'a': {}}))
    add_participants('zero-damage-support', dict(hits=[hit(0)], records=[dict(source_character_key='supp')], allocated={'a': 5.0, 'supp': 5.0}))
    add_participants('unicode-tie', dict(hits=[hit(0, char='private'), hit(0, char='emoji')]))
    add_participants('preserve-ingestion-counter', dict(rebuild=False, roster=['a'], hits=[hit(0, damage=1)],
                     totals={'a': dict(character_key='a', character_name='Existing', total_damage=100, max_hit=50, hit_count=3, crit_hits=1)},
                     records=[dict(source_character_key='supp')], allocated={'a': 99.0, 'supp': 1.0}))
    rng = random.Random(20261028)
    for index in range(100):
        rows = [hit(rng.randrange(1000), rng.choice(['a', 'b', 'c']), rng.choice(['s', 't']), rng.randrange(0, 10**8),
                    rng.choice(['one', 'two']), rng.choice([0, 1, 2]), rng.choice([None, 'Name'])) for _ in range(rng.randrange(25))]
        add_participants('ordered-counters', dict(hits=rows, duration_ms=rng.choice([1, 3, 333, 2001, 90_000]),
                         allocated={key: rng.random()*10**6 for key in rng.sample(['a', 'b', 'c'], rng.randrange(4))}))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Report projection fixtures:', len(cases))


if __name__ == '__main__':
    main()
