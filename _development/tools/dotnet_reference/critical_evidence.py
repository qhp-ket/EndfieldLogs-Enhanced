"""Freeze critical outcome evidence and report state-change diagnostics from the fixed Python reference."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/critical-evidence.json'
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
    context = importlib.import_module('parser_core.critical_context')
    report = importlib.import_module('parser_core.reporting.critical')
    cases = []
    prefix_type = 'Beyond.Gameplay.Core.'

    def add_profile(root):
        config = dict(operation='profile', root=root)
        cases.append(dict(name=f'{len(cases):03d}-profile', config_json=json.dumps(config), expected=canonical(context.critical_buff_profile(root))))

    for root in [None, [], 'missing', {}, {'attributeType': 'CriticalRate'},
                 {'attributeType': 'CriticalDamageIncrease'}, {'attributeType': 'Attack'},
                 {'$type': prefix_type+'DamageAction.DamageUnit', 'attributeType': 'CriticalRate'},
                 {'$type': prefix_type+'AttackCriticalRateProcessor'}, {'$type': prefix_type+'AttackerCriticalDamageProcessor'},
                 {'$type': prefix_type+'InstantModifyAttribute', 'modifier': {'attributeType': 'CriticalRate'}},
                 {'list': [{'attributeType': 'CriticalRate'}, {'attributeType': 'CriticalDamageIncrease'}]},
                 {'$type': prefix_type+'DamageAction+DamageUnit', 'attributeType': 'CriticalRate'}]:
        add_profile(root)

    base_hit = dict(character_key='a', source_actor_id='owner', ts_ms=1000, line_no=100, damage_element='physical',
                    critical_flag_observed=True, crit_flag=0, damage_calculation={'damageProcessors': []}, part_inst_id=0,
                    hit_value=100, raw_hit_value=100, overkill_damage=0, enemy_hp_after_observed=True, enemy_hp_before=1000)
    base_observation = dict(template='a', values={9: .25, 10: .5}, lines={9: 50, 10: 50}, times={9: 500, 10: 500})

    def add_build(name, hit=None, observation=base_observation, roots=None, windows=None):
        hit = {**base_hit, **(hit or {})}
        roots = roots or {}
        config = dict(operation='build', hit=hit, observation=observation, roots=roots, windows=windows or [])
        profiles = {key: context.critical_buff_profile(root) for key, root in roots.items()}
        expected = context.build_critical_context(hit, observation, profiles, windows or [])
        cases.append(dict(name=f'{len(cases):03d}-{name}', config_json=json.dumps(config), expected=canonical(expected)))

    for rate, bonus, flag, observed in itertools.product([-.1, 0, .25, 1, 1.1], [-.1, 0, .5], [0, 1], [False, True]):
        add_build('rates', dict(crit_flag=flag, critical_flag_observed=observed), {**base_observation, 'values': {9: rate, 10: bonus}})
    for hit in [dict(critical_flag_observed=False), dict(part_inst_id=1), dict(damage_calculation=None),
                dict(damage_calculation={}), dict(damage_calculation={'damageProcessors': None}), dict(enemy_hp_before=None),
                dict(enemy_hp_before=99), dict(enemy_hp_before=True), dict(enemy_hp_after_observed=False),
                dict(overkill_damage=10, raw_hit_value=110), dict(damage_element='lifedrain'),
                dict(damage_element='lifedrain', crit_flag=1), dict(_active_attacker_buff_ids=['missing']),
                dict(_active_target_buff_ids=['missing']), dict(enemy_hp_before=2**90), dict(enemy_hp_before=100.0)]:
        add_build('evidence', hit)
    for observation in [None, {}, {**base_observation, 'template': 'other'}, {**base_observation, 'values': {9: .2}}]:
        add_build('missing-snapshot', observation=observation)
    for parameter, operation, side, attr in itertools.product([None, {'useBlackboardKey': False, 'value': .1},
                {'useBlackboardKey': True, 'value': .1}, {'useBlackboardKey': False, 'value': True}],
                ['Addition', 'FinalMultiplier', 'Unknown'], ['Attacker', 'Defender', 'Unknown'], ['CriticalRate', 'Attack']):
        processor = dict(**{'$type': prefix_type+'InstantModifyAttribute'}, modifyTargetSide=side,
                         modifier=dict(modifyAttributeType='Specific', attributeType=attr, formulaItem=operation, param=parameter))
        add_build('processor', dict(damage_calculation={'damageProcessors': [processor]}))
    for processor in [None, {}, {'$type': prefix_type+'DamageScaleProcessor'},
                      {'$type': prefix_type+'AttackCriticalRateProcessor', 'addition': {'useBlackboardKey': False, 'value': .2}}]:
        for count in [1, 2]:
            add_build('multiple-processors', dict(damage_calculation={'damageProcessors': [processor] * count}))
    for change, boundary, snapshot in itertools.product([None, 49, 50, 51, 99, 100, 101], [False, True], [False, True]):
        window = dict(event_key='buff', target_actor_id='owner', line_no=change, end_line_no=None,
                      end_ts_ms=None, end_is_observation_boundary=boundary, snapshot_update=snapshot)
        add_build('state-lines', roots={'buff': {'attributeType': 'CriticalRate'}}, windows=[window])
    for end in [499, 500, 501, 1000, 1001]:
        add_build('state-clock', roots={'buff': {'attributeType': 'CriticalDamageIncrease'}},
                  windows=[dict(event_key='buff', target_actor_id='owner', end_ts_ms=end, snapshot_update=True)])
    add_build('conditional-active', dict(_active_attacker_buff_ids=['buff']), roots={'buff': {'$type': prefix_type+'AttackCriticalRateProcessor'}})

    for event_line, status, alias, raw_key in itertools.product([49, 51, 101], ['duplicate', 'observed'], [False, True], ['buff', '42']):
        roots = {'buff': {'attributeType': 'CriticalRate'}}
        records = [dict(event_key=raw_key, uid='original' if alias else 'window', target_actor_id='owner',
                        dynamic_bb_events=[dict(line_no=event_line, status=status)], enable_observations=[], repeated_creation_observations=[])]
        windows = [dict(event_key=raw_key, uid='window', uid_aliases=['original'] if alias else [], target_actor_id='owner', snapshot_update=True)]
        hits = [{**base_hit, 'critical_observation': base_observation}]
        config = dict(operation='attach', hits=hits, records=records, windows=windows, roots=roots, numbers={'42': 'buff'})
        state = copy.deepcopy(config)
        report._load_current_buff_roots = lambda: roots
        report._load_num_id_str_buff_map = lambda: config['numbers']
        report.attach_critical_context(SimpleNamespace(hits=state['hits'], buff_starts=state['records']), state['windows'])
        expected = dict(hits=state['hits'], windows=state['windows'])
        cases.append(dict(name=f'{len(cases):03d}-report-binding', config_json=json.dumps(config), expected=canonical(expected)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Critical evidence fixtures:', len(cases))


if __name__ == '__main__':
    main()
