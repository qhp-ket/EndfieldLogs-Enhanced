"""Freeze allocation explanations, baseline phases and observed resistance from the fixed Python tree."""
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
    parser.add_argument('--part', choices=['debug', 'baseline', 'resistance', 'multipliers', 'contributors', 'arts', 'hit'], required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(__file__).resolve().parents[3] / f'_internal/dotnet/Specs/Fixtures/allocation-{args.part}.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed allocation reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    debug = importlib.import_module('parser_core.allocation.debug')
    baseline = importlib.import_module('parser_core.allocation.baseline')
    resistance = importlib.import_module('parser_core.allocation.resistance')
    context = importlib.import_module('parser_core.allocation.context')
    attack = importlib.import_module('parser_core.allocation.attack_model')
    selection = importlib.import_module('parser_core.allocation.stack_selection')
    rules = importlib.import_module('parser_core.effects.stacking_rules')
    identity = importlib.import_module('parser_core.effects.window_identity')
    multipliers = importlib.import_module('parser_core.allocation.multipliers')
    shares = importlib.import_module('parser_core.allocation.shares')
    contributors = importlib.import_module('parser_core.allocation.contributors')
    arts = importlib.import_module('parser_core.allocation.arts_strength')
    damage_types = importlib.import_module('parser_core.effects.damage_types')
    allocator = importlib.import_module('parser_core.allocation.hit')
    explanation = importlib.import_module('parser_core.allocation.explanation')
    if damage_types._BUFF_SKILL_FILTER or damage_types._BUFF_EFFECT_SKILL_FILTER:
        raise ValueError('Fixed reference skill filter tables changed')
    cases = []
    current = {}
    debug._resolve_character_name = lambda key: current.get('names', {}).get(key, key) if key else None
    explanation._resolve_character_name = debug._resolve_character_name
    explanation._collect_buff_labels = lambda record: record.get('test_labels', [])
    attack._load_skill_action_damage_units = lambda _: {}
    for module in (selection, rules, identity, resistance):
        module._load_current_buff_roots = lambda: current.get('roots', {})
    rules._load_local_buff_semantic_entries = lambda: {}
    rules._load_weapon_buff_stack_limits = lambda: {}
    base = dict(character_key='chr_a', target_enemy_key='enemy', hit_value=100, ts_ms=1000, line_no=10,
        damage_element='fire', damage_school='spell', source_actor_id='a1', target_actor_id='e1')

    def add(label, operation, **changes):
        config = dict(operation=operation, hit=base, windows=[], records=None, by_uid=None, by_actor=None,
            numeric_baseline={}, self={}, self_factors={}, external={}, captured={}, names={'chr_a': '甲', 'chr_b': '乙'}, debug=True)
        config.update(changes)
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        current.clear()
        current.update(owned)
        try:
            if operation.startswith('debug-'):
                kind = operation[6:]
                if kind == 'round':
                    result = debug._round4(owned['value'])
                elif kind == 'applicable':
                    result = debug._rdps_debug_record_applicable_effect(window=owned['window'], effect=owned['effect'],
                        scope=owned['scope'], rdps_credit=owned.get('credit'))
                elif kind == 'baseline':
                    result = debug._rdps_debug_record_baseline_self(hit=owned['hit'], **owned['parameters'])
                elif kind == 'static':
                    result = debug._rdps_debug_record_static_self(hit=owned['hit'], entry=owned['entry'])
                elif kind == 'dpd':
                    result = debug._rdps_debug_record_dpd_self_residual(hit=owned['hit'], zone=owned['zone'], rate=owned['rate'])
                elif kind == 'arts':
                    result = debug._rdps_debug_record_arts_effect_provenance(effect_window=owned['window'], effect=owned['effect'],
                        source_key=owned['source'], rate=owned['rate'], provenance=owned.get('provenance'), scope=owned['scope'])
                elif kind == 'rows':
                    result = debug._rdps_contribution_rows(owned['contributions'], sort_by_value=owned['sort'])
                elif kind == 'zones':
                    result = debug._sort_rdps_debug_zones(owned['rows'])
                else:
                    raise ValueError(operation)
            elif operation == 'allocate':
                hit, windows = copy.deepcopy(owned['hit']), copy.deepcopy(owned['windows'])
                if owned['numeric_baseline']:
                    hit.setdefault('baseline', {}).update({int(key): value for key, value in owned['numeric_baseline'].items()})
                allocation = allocator._allocate_rdps_for_hit(hit, windows, include_debug=owned['debug'],
                    condition_buff_records=owned['records'], condition_records_by_target=owned.get('by_target'),
                    effect_window_indices=owned.get('indices'), condition_records_by_uid=owned['by_uid'],
                    condition_records_by_actor=owned['by_actor'], buff_records_by_uid=owned.get('buff_records'))
                result = dict(allocation=allocation, hit={key: value for key, value in hit.items() if key != 'baseline'}, windows=windows)
            elif operation == 'arts-attribution':
                windows = copy.deepcopy(owned['windows'])
                sources = arts._arts_strength_effect_contributors(effect_window=owned['window'], effect=owned['effect'], buff_windows=windows)
                result = dict(sources=sources, windows=windows)
            else:
                hit = copy.deepcopy(owned['hit'])
                if owned['numeric_baseline']:
                    hit.setdefault('baseline', {}).update({int(key): value for key, value in owned['numeric_baseline'].items()})
                state = context.HitAllocation(hit, copy.deepcopy(owned['windows']), owned['debug'], None,
                    owned['records'], None, owned.get('indices'), owned['by_uid'], owned['by_actor'])
                context.prepare_allocation(state)
                state.self_by_zone.update(owned['self'])
                state.self_factor_by_zone.update(owned['self_factors'])
                state.external_by_zone.update(owned['external'])
                state.captured_by_attr_type.update({int(key): value for key, value in owned['captured'].items()})
                if operation in ('resistance', 'baseline-connected', 'collect'):
                    selection.select_stack_effects(state)
                if operation == 'collect':
                    resistance.resolve_resistance_baseline(state)
                    contributors.collect_effect_contributors(state)
                    result = dict(self=state.self_by_zone, self_factors=state.self_factor_by_zone,
                        captured=state.captured_by_attr_type, external=state.external_by_zone,
                        contributors=state.contributors_by_zone, ignored=state.ignored_effects,
                        invalid=state.invalid_numeric_allocation, windows=state.buff_windows)
                    if owned.get('complete_phases'):
                        baseline.attach_observed_baseline(state)
                        baseline.resolve_attack_baseline(state)
                        baseline.check_remaining_baselines(state)
                        multipliers.compute_zone_multipliers(state)
                        allocation = shares.allocate_log_marginal(state.attacker_key, state.hit_value, m_values=state.m_values,
                            external_by_zone=state.external_by_zone, external_sum_by_zone=state.external_sum_by_zone,
                            include_debug=state.include_debug)
                        result.update(invalid=state.invalid_numeric_allocation, multipliers=state.m_values,
                            sums=state.external_sum_by_zone, product=allocation.product_external,
                            attacker_share=allocation.attacker_share, pool=allocation.external_pool, contributions=allocation.contributions)
                elif operation == 'multipliers':
                    state.resistance_numerator = owned.get('numerator')
                    state.attack_baseline_error = owned.get('attack_error')
                    state.invalid_numeric_allocation = owned.get('invalid', False)
                    multipliers.compute_zone_multipliers(state)
                    allocation = shares.allocate_log_marginal(state.attacker_key, state.hit_value, m_values=state.m_values,
                        external_by_zone=state.external_by_zone, external_sum_by_zone=state.external_sum_by_zone,
                        include_debug=state.include_debug)
                    result = dict(multipliers=state.m_values, sums=state.external_sum_by_zone, self=state.self_by_zone,
                        self_factors=state.self_factor_by_zone, external=state.external_by_zone, ignored=state.ignored_effects,
                        invalid=state.invalid_numeric_allocation, product=allocation.product_external,
                        attacker_share=allocation.attacker_share, pool=allocation.external_pool, contributions=allocation.contributions)
                elif operation == 'resistance':
                    resistance.resolve_resistance_baseline(state)
                    result = dict(effective=state.effective_resistance, numerator=state.resistance_numerator,
                        source=state.resistance_source, windows=state.buff_windows, effects=state.effects_at_hit,
                        zones=sorted(state.unresolved_stack_zones), ignored=state.ignored_effects)
                else:
                    if operation in ('observed', 'baseline-connected'):
                        baseline.attach_observed_baseline(state)
                    if operation in ('attack', 'baseline-connected'):
                        baseline.resolve_attack_baseline(state)
                    if operation in ('remaining', 'baseline-connected'):
                        baseline.check_remaining_baselines(state)
                    result = dict(self=dict(state.self_by_zone), contributors=dict(state.contributors_by_zone),
                        ignored=state.ignored_effects, invalid=state.invalid_numeric_allocation,
                        attack_error=getattr(state, 'attack_baseline_error', None))
                result['hit'] = {key: value for key, value in state.hit.items() if key != 'baseline'}
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            result = dict(error=type(exc).__name__)
        cases.append(dict(name=f'{len(cases):05d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    if args.part == 'debug':
        for value in [None, False, True, 0, -0., 1.23445, 2.675, 1.23455, -1.23455, 1e-300, 1e300,
                float('inf'), float('-inf'), float('nan'), '1.23445', 'nan', 'bad', [], {}, 10**400]:
            add('round', 'debug-round', value=value)
        for zone, element, rate, scope in itertools.product(['atk', 'res', 'arts_strength', 'unknown', None],
                [None, 'fire', 'all'], [0, .123456, '0.2', None], ['self', 'external']):
            effect = dict(zone=zone, element=element, rate=rate, condition={'type': 'all', 'conditions': []},
                rdps_whitelist_keys=['x'], external_rdps_allowed=True, keyword_origin={'source': ['proof']},
                recipient_side='defender', converted_attribute={'attr': 98})
            window = dict(source_character_key='chr_a', raw_source_character_key='chr_b', uid='u1', uid_aliases=['u1', 'u2'],
                start_ts_ms=1, end_ts_ms=2, raw_source='actor', target_character_key='enemy')
            add('applicable', 'debug-applicable', window=window, effect=effect, scope=scope, credit=.33335)
        for key, name, source_name in itertools.product([None, '', 'chr_a', 'unknown'], [None, '', '名称'], [None, '', '显式来源']):
            add('name-fallback', 'debug-applicable', window=dict(source_character_key=key, source_character_name=name,
                raw_source_character_key=key, raw_source_character_name=source_name, uid_aliases='abc'), effect={}, scope='external')
        for attribute, zone in itertools.product([2, 9, 32, 51, 52, 70, 94, 999, 10**30], ['atk', 'dmg_inc', 'unknown']):
            add('baseline', 'debug-baseline', parameters=dict(attr_type=attribute, zone=zone, element='fire', rate=.123456,
                final_value=.3, captured=.176544))
        for entry in [{}, dict(zone='res', rate=10), dict(zone='dmg_inc', rate='0.123456', label='技能', note={'a': [1]},
                source_type='weapon', source_name='武器'), dict(zone='unknown', rate='bad')]:
            add('static', 'debug-static', entry=entry)
        for zone in ['atk', 'dmg_inc', 'res', 'unknown']:
            add('dpd', 'debug-dpd', zone=zone, rate=.123456)
        for provenance in [None, {}, dict(effect_source_character_key='chr_b', arts_strength_points=120.123456,
                arts_strength_self_points=100, arts_strength_external_points=20.123456, arts_strength_whitelist_keys=['arts'])]:
            add('arts', 'debug-arts', window=dict(source_character_key='chr_b'), effect=dict(zone='amp', rdps_whitelist_keys=['amp']),
                source='chr_a', rate=.123456, scope='external', provenance=provenance)
        for sort in [False, True]:
            add('rows', 'debug-rows', contributions={'chr_b': 10., 'chr_a': 10., 'zero': 0., 'negative': -1., '\ue000': 3., '\U00010000': 3.}, sort=sort)
        add('zones', 'debug-zones', rows=[dict(zone=zone, ordinal=index) for index, zone in enumerate(
            ['unknown', 'res', 'atk', 'arts_strength', 'prod_dmg_inc', None, 'atk', '\ue000', '\U00010000'])])
    elif args.part == 'baseline':
        for attr, value, mask, debug_enabled in itertools.product([2, 9, 10, 17, 28, 32, 33, 50, 51, 52, 65, 70, 71, 999],
                [None, -1, 0, .2, '0.2', 'bad', True, float('inf')], [None, 0, 256, 8192], [False, True]):
            add('observed', 'observed', hit=base | dict(baseline={str(attr): value}, damage_decorate_mask=mask), debug=debug_enabled)
        for final, captured in itertools.product([0., .2, .5], [-.1, 0., .2, .3, .6]):
            add('captured', 'observed', hit=base | dict(baseline={'32': final}, damage_decorate_mask=256), captured={'32': captured})
        entry = dict(zone='dmg_inc', attr_type=32, rate=.2, element='all', evidence_kind='other')
        for numeric, text, attr in itertools.product([None, 0., .2, 'bad'], [None, 0., .3, 'bad'], [32, 32., '32']):
            add('typed-baselines', 'observed', hit=base | dict(baseline={'32': text}, damage_decorate_mask=256,
                static_multiplier_entries=[entry | dict(attr_type=attr)]), numeric_baseline={'32': numeric})
        for entries in [[None, False, 1, {}], [entry], [entry | dict(evidence_kind='official_EquipTable_attribute')],
                [entry | dict(zone='atk', attr_type=2)], [entry | dict(rate='bad')], [entry | dict(attr_type=[])]]:
            for independent in [False, True]:
                calculation = dict(source='current_typed_damage_unit', simpleCalculation=False,
                    atkCalculation={'$type': 'Beyond.Gameplay.Core.DefiniteValueCalculation'}) if independent else {}
                add('static', 'observed', hit=base | dict(static_multiplier_entries=entries, damage_decorate_mask=256,
                    damage_calculation=calculation))
        for flat, attack_base, external in itertools.product([None, -1, 0, 20, 'bad', float('inf'), 1e308],
                [None, -1, 0, 100, 1e-300], [False, True]):
            add('flat-attack', 'attack', hit=base | dict(static_flat_attack=flat, base_attack_for_percent=attack_base),
                external={'atk': [['chr_b', .2, None]]} if external else {})
        def affine(addition, multiplier):
            return dict(source='current_typed_damage_unit', simpleCalculation=False, sourceProof={'resourceId': 'owner_buff'},
                atkCalculation={'$type': 'Beyond.Gameplay.Core.MultiplyAttributeCalculation', 'attributeType': 'Atk',
                    'valueSource': 'AttackerOrHealer', 'addition': addition, 'multiplier': multiplier})
        for addition, coefficient, ability, attack_base in itertools.product([None, -10, 0, 40, 'bad', 1e308],
                [None, -1, 0, 2, 1e308], [None, 0, 1.5], [None, 100, 1e308]):
            add('affine-constant', 'attack', hit=base | dict(damage_calculation=affine(dict(useBlackboardKey=False, value=addition),
                dict(useBlackboardKey=False, value=coefficient)), base_attack_for_percent=attack_base, attack_ability_factor=ability),
                external={'atk': [['chr_b', .2, None]]})
        owner = dict(uid='owner', event_key='owner_buff', ts_ms=900, line_no=1, bb_values={'m': 2, 'a': 40})
        params = affine(dict(useBlackboardKey=True, blackboardKey='a'), dict(useBlackboardKey=True, blackboardKey='m'))
        for records in [None, [], [owner], [owner, owner], [owner | dict(uid='other')], [owner | dict(event_key='other')],
                [owner | dict(ts_ms=1001)], [owner | dict(ts_ms=1000, line_no=11)], [owner | dict(ts_ms=1000, line_no=10)],
                [owner | dict(end_ts_ms=1000, end_line_no=10)], [owner | dict(end_ts_ms=1000, end_line_no=11)],
                [owner | dict(snapshot_end_ts_ms=1000, snapshot_end_line_no=10)], [owner | dict(snapshot_end_ts_ms=1000, snapshot_end_line_no=11)]]:
            for by_uid in [None, {}, {'owner': [owner]}]:
                add('affine-owner', 'attack', hit=base | dict(damage_calculation=params, event_inst_id='owner',
                    base_attack_for_percent=100, attack_ability_factor=1.5), records=records, by_uid=by_uid)
        for anomaly, points in itertools.product([False, True], [None, -1, 0, 120, '120', 'bad', float('inf')]):
            add('arts', 'remaining', hit=base | dict(damage_decorate_mask=0x4000 if anomaly else 0,
                static_arts_strength_entries=[dict(zone='arts_strength', rate=points, source_name='装备')]))
        for bucket, self_rate, external in itertools.product([None, 1., 1.2, 1.203, 1.20301, 'bad', float('inf'), float('nan')],
                [0., .2], [[], [['b', .1, None], ['c', .1, None]], [['b', 1e16, None], ['c', 1., None], ['d', -1e16, None]]]):
            add('residual', 'remaining', hit=base | dict(dpd_raw={'atk_zones': [1, bucket, 1, 1, 1]}),
                self={'dmg_inc': self_rate}, external={'dmg_inc': external})
        add('all-baselines', 'baseline-connected', hit=base | dict(baseline={'32': .3}, damage_decorate_mask=0x4100,
            static_flat_attack=20, base_attack_for_percent=100, static_arts_strength_entries=[dict(zone='arts_strength', rate=120)]), captured={'32': .1})
    elif args.part == 'resistance':
        parameter = dict(zone='res', element='fire', parameter_keys=['res'], external_rdps_allowed=True,
            rdps_whitelist_keys=['proof'], parameter_snapshots=[dict(ts_ms=900, line_no=2, operation_seq=1,
                status='attribute_parameters_observed', session_id='session', bb_values={'res': -10})])
        window = dict(uid='u1', event_key='buff', target_actor_id='e1', target_character_key='enemy', source_character_key='chr_b',
            start_ts_ms=900, start_line_no=1, end_ts_ms=1100, end_line_no=20, dynamic_effects=[parameter])
        hit = base | dict(target_resistance_points={'fire': 20}, target_stats_snapshot_ts_ms=800,
            target_stats_snapshot_line_no=1, packet_attribute_report_present=True)
        for snapshot, line, now, report in itertools.product([None, False, 0, 800, 900, 1000, 1100, '800', 800.],
                [None, False, 0, 1, 10, '1'], [899, 900, 1000, 1100, 1101], [None, False, True, 1]):
            add('snapshot-gates', 'resistance', hit=hit | dict(target_stats_snapshot_ts_ms=snapshot,
                target_stats_snapshot_line_no=line, ts_ms=now, packet_attribute_report_present=report), windows=[window])
        for changes in [dict(packet_attr_details={'defender': ['98:15']}), dict(packet_attr_details={'defender': ['98:bad']}),
                dict(packet_attribute_report_unresolved=True), dict(rdps_unresolved_target_binding=True), dict(target_actor_id=''),
                dict(target_resistance_points={}), dict(target_resistance_points={'fire': 'bad'}), dict(packet_seq_id=0),
                dict(packet_seq_id=1, packet_session_id='wrong'), dict(packet_seq_id=1, packet_session_id='session')]:
            add('packet-gates', 'resistance', hit=hit | changes, windows=[window])
        for changes in [dict(target_actor_id='other'), dict(target_character_key='other'), dict(requires_enable_observation=True),
                dict(dynamic_effects=[parameter | dict(parameter_snapshots=[])]), dict(dynamic_effects=[parameter | dict(element='physical')]),
                dict(dynamic_effects=[parameter | dict(parameter_snapshots=[dict(parameter['parameter_snapshots'][0], bb_values={'res': 10})])])]:
            add('window-gates', 'resistance', hit=hit, windows=[window | changes])
        root = dict(attributeModifier={'attributeModifiers': [dict(attributeType='FireResistance')]})
        record = dict(uid='other', event_key='unmodeled', target_actor_id='e1', ts_ms=850, line_no=1, end_ts_ms=1200)
        for records, by_actor in itertools.product([None, [], [record], [record | dict(target_actor_id='other')],
                [record | dict(uid='u1', ts_ms=900, line_no=1)], [record | dict(end_ts_ms=800)],
                [record | dict(ts_ms=1100)]], [None, {}, {'e1': [record]}]):
            add('unmodeled', 'resistance', hit=hit, windows=[window], records=records, by_actor=by_actor, roots={'unmodeled': root})
        for rate in [-0., -1e-300, -10, -1e308, float('-inf'), float('nan')]:
            add('refresh-value', 'resistance', hit=hit, windows=[window | dict(dynamic_effects=[parameter | dict(
                parameter_snapshots=[dict(parameter['parameter_snapshots'][0], bb_values={'res': rate})])])])
        for indices in [None, [], [0], [1], [1, 0]]:
            add('selected-windows', 'resistance', hit=hit, windows=[window, window | dict(uid='u2')], indices=indices)
    elif args.part == 'multipliers':
        for zone, self_value, rate, debug_enabled in itertools.product(['atk', 'dmg_inc', 'amp', 'fragile', 'vuln_taken',
                'res', 'combo', 'arts_strength', 'prod_dmg_inc', 'prod_vuln_taken'], [-100., -1., -.5, 0., .2, 100.],
                [-1., 0., .2, 10., 100., 1e308], [False, True]):
            add('zone-model', 'multipliers', self={zone: self_value}, external={zone: [['chr_b', rate, {}]]}, numerator=90., debug=debug_enabled)
        for rates in [[.1, .2], [.2, .1], [1e16, 1., -1e16], [1e308, 1e308], [float('nan')], [float('inf')], [-.2, .3]]:
            for zone in ['dmg_inc', 'arts_strength', 'prod_dmg_inc']:
                for mask in [0, 0x4000, 0x40000008]:
                    add('rates-and-factors', 'multipliers', hit=base | dict(damage_decorate_mask=mask),
                        external={zone: [[f'chr_{index}', value, {}] for index, value in enumerate(rates)]})
        for invalid, captured, factor in itertools.product([False, True], [0., float('nan'), float('inf')], [1., float('inf')]):
            add('invalid', 'multipliers', invalid=invalid, captured={'32': captured}, self_factors={'dmg_inc': factor},
                self={'dmg_inc': .1}, external={'dmg_inc': [['chr_b', .2, {}]]})
        for numerator in [None, -1., 0., 10., 10.000000001, 90., float('nan'), float('inf')]:
            add('res-counterfactual', 'multipliers', numerator=numerator, external={'res': [['chr_b', 10., {}]]})
        for error in [None, 'missing_damage_base_addition']:
            add('attack-blocked', 'multipliers', attack_error=error, external={'atk': [['chr_b', .2, {}]], 'dmg_inc': [['chr_c', .1, {}]]})
        for order in itertools.permutations(['atk', 'dmg_inc', 'amp']):
            add('zone-order', 'multipliers', hit=base | dict(hit_value=123456.789), self={'atk': .7, 'dmg_inc': .2},
                external={zone: [['chr_b', .1, {}], ['chr_c', .2, {}], ['chr_b', .3, {}]] for zone in order})
        for hit_value in [-100., 0., 100., 1e300]:
            add('hit-value', 'multipliers', hit=base | dict(hit_value=hit_value), external={'atk': [['chr_b', .2, {}]], 'amp': [['chr_a', .5, {}]]})
        for huge in [1e150, 1e160, 1e300, 1e308]:
            add('combined-overflow', 'multipliers', external={'atk': [['chr_b', huge, {}]], 'amp': [['chr_c', huge, {}]]})
    elif args.part == 'contributors':
        window = dict(uid='u1', event_key='buff', source_character_key='chr_b', target_character_key='chr_a',
            target_actor_id='a1', start_ts_ms=900, start_line_no=1, end_ts_ms=1100, end_line_no=20)
        for zone, owner, source, rate, debug_enabled in itertools.product(['atk', 'dmg_inc', 'amp', 'combo', 'crit', 'arts_strength',
                'fragile', 'vuln_taken', 'res', 'prod_dmg_inc', 'prod_vuln_taken', 'speedup'],
                ['chr_a', 'enemy', 'other'], ['chr_a', 'chr_b', ''], [-.1, 0., .2, 'bad'], [False, True]):
            add('recipient', 'collect', windows=[window | dict(target_character_key=owner, source_character_key=source,
                target_actor_id='e1' if owner == 'enemy' else 'a1', zone_effects=[dict(zone=zone, element='all', rate=rate)])], debug=debug_enabled)
        for side, allow, attribute, mask in itertools.product(['attacker', 'defender', 'other', None], [None, False, True],
                [None, 32, 32., '32', False], [None, 0, 256]):
            add('explicit-side-and-mask', 'collect', hit=base | dict(damage_decorate_mask=mask), windows=[window | dict(zone_effects=[
                dict(zone='dmg_inc', rate=.2, element='all', recipient_side=side, external_rdps_allowed=allow, attr_type=attribute)])])
        for calculation in [{}, None, dict(source='current_typed_damage_unit', simpleCalculation=False,
                atkCalculation={'$type': 'Beyond.Gameplay.Core.DefiniteValueCalculation'}),
                dict(source='current_typed_damage_unit', simpleCalculation=True)]:
            add('attack-dependency', 'collect', hit=base | dict(damage_calculation=calculation), windows=[window | dict(zone_effects=[dict(zone='atk', rate=.2)])])
        for changes in [dict(start_ts_ms=1001), dict(end_ts_ms=999), dict(start_ts_ms=1000, start_line_no=11),
                dict(start_ts_ms=1000, event_key='skill'), dict(skill_family_key='other'), dict(target_actor_id='other'),
                dict(requires_enable_observation=True), dict(snapshot_update=True, start_ts_ms=1000), dict(uid_aliases=['alias'])]:
            for seen in [False, True]:
                add('window-identity', 'collect', hit=base | dict(skill_key='skill', line_no=0 if changes.get('snapshot_update') else 10,
                    packet_modifier_seen=seen, packet_modifier_uids={'attacker': ['u1']}),
                    windows=[window | dict(zone_effects=[dict(zone='dmg_inc', rate=.2)]) | changes])
        for element, condition in itertools.product(['all', 'fire', 'physical', 'spell', 'ether'], [None,
                dict(type='damage_decorate_mask', check='HasAny', mask=256), dict(type='damage_decorate_mask', check='HasAny', mask=512),
                dict(type='unknown'), dict(type='target_hp_ratio', comparator='less_equal', value=.5)]):
            add('element-conditions', 'collect', hit=base | dict(damage_decorate_mask=256), windows=[window | dict(zone_effects=[
                dict(zone='dmg_inc', rate=.2, element=element, condition=condition)])])
        defender = window | dict(target_character_key='enemy', target_actor_id='e1', zone_effects=[dict(zone='vuln_taken', rate=.2, element='all')])
        for uids, allowed, seen in itertools.product([[], ['u1'], ['u2'], ['alias']], [[], ['32:x'], ['70:x']], [False, True]):
            add('defender-guards', 'collect', hit=base | dict(packet_modifier_seen=seen, packet_modifier_uids={'defender': uids},
                packet_attr_details={'defender': allowed}), windows=[defender, defender | dict(uid='u2', uid_aliases=['alias'])])
        for actor, uid in itertools.product(['e1', 'other', '', None], [[], ['u1']]):
            add('defender-actor', 'collect', hit=base | dict(target_actor_id=actor, packet_modifier_uids={'defender': uid}), windows=[defender])
        for policy in ['Unique', 'Unlimited', 'HighPriority']:
            add('stack-policy', 'collect', windows=[window | dict(zone_effects=[dict(zone='dmg_inc', rate=.2)]),
                window | dict(uid='u2', zone_effects=[dict(zone='dmg_inc', rate=.3)])],
                roots={'buff': dict(stackingSettings=dict(stackingType=policy, maxStackCnt=1, useMaxStackCntKey=False))})
        for anomaly in [False, True]:
            for debug_enabled in [False, True]:
                windows = [window | dict(zone_effects=[dict(zone='dmg_inc', rate=.2, attr_type=32)]),
                    window | dict(uid='u2', source_character_key='chr_a', zone_effects=[dict(zone='atk', rate=.3)]),
                    defender, window | dict(uid='u3', zone_effects=[dict(zone='arts_strength', rate=100)])]
                add('connected-accounting', 'collect', hit=base | dict(hit_value=1234.5, baseline={'32': .5},
                    damage_decorate_mask=0x4100 if anomaly else 256, static_flat_attack=20, base_attack_for_percent=100),
                    windows=windows, complete_phases=True, debug=debug_enabled)
        for anomaly, debug_enabled in itertools.product([False, True], [False, True]):
            windows = [window | dict(event_key='skill_bonus', zone_effects=[dict(zone='dmg_inc', rate=.2, attr_type=32)]),
                window | dict(uid='u2', event_key='own_attack', source_character_key='chr_a', zone_effects=[dict(zone='atk', rate=.3)]),
                defender | dict(event_key='enemy_vulnerability'),
                window | dict(uid='u3', event_key='arts_support', zone_effects=[dict(zone='arts_strength', rate=100)])]
            add('connected-independent-effects', 'collect', hit=base | dict(hit_value=1234.5, baseline={'32': .5},
                damage_decorate_mask=0x4100 if anomaly else 256, static_flat_attack=20, base_attack_for_percent=100),
                windows=windows, complete_phases=True, debug=debug_enabled)
    elif args.part == 'arts':
        window = dict(source_character_key='chr_b', event_key='debuff', start_ts_ms=1000, start_line_no=10,
            source_static_arts_strength=100)
        candidate = dict(uid='u1', source_character_key='chr_a', target_character_key='chr_b', start_ts_ms=900,
            start_line_no=1, end_ts_ms=1100, zone_effects=[dict(zone='arts_strength', rate=100, rdps_whitelist_keys=['arts'])])
        for provenance, self_points, rate in itertools.product([None, False, True, 1], [0, 100, -1, float('nan')], [0., .2, 10.]):
            add('provenance', 'arts-attribution', window=window | dict(source_static_arts_strength=self_points),
                effect=dict(rate=rate, arts_strength_provenance=provenance), windows=[candidate])
        for points, allowed, provider in itertools.product([0., -10., 100., float('inf'), float('nan')], [None, False, True],
                ['chr_a', 'chr_b', '']):
            add('provider', 'arts-attribution', window=window, effect=dict(rate=.2, arts_strength_provenance=True),
                windows=[candidate | dict(source_character_key=provider, zone_effects=[dict(zone='arts_strength', rate=points,
                    external_rdps_allowed=allowed, rdps_whitelist_keys=['z', 'a', 'z'])])])
        for changes in [dict(target_character_key='other'), dict(start_ts_ms=1001), dict(end_ts_ms=999),
                dict(start_ts_ms=1000, start_line_no=11), dict(start_ts_ms=1000, start_line_no=10),
                dict(requires_enable_observation=True), dict(zone_effects=[dict(zone='atk', rate=100)])]:
            add('application-boundary', 'arts-attribution', window=window, effect=dict(rate=.2, arts_strength_provenance=True), windows=[candidate | changes])
        for providers in [['chr_a', 'chr_c'], ['chr_a', 'chr_a'], ['chr_b', 'chr_a'], ['chr_c', 'chr_a']]:
            add('multiple-providers', 'arts-attribution', window=window, effect=dict(rate=.3, arts_strength_provenance=True),
                windows=[candidate | dict(uid=str(index), source_character_key=provider,
                    zone_effects=[dict(zone='arts_strength', rate=100 * (index + 1), rdps_whitelist_keys=[f'proof{index}'])])
                    for index, provider in enumerate(providers)])
    else:
        source = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/allocation-contributors.json'
        for item in json.loads(source.read_text(encoding='utf8')):
            config = json.loads(item['config_json'])
            config.pop('operation')
            add('complete-' + item['name'], 'allocate', **config)
        record = dict(uid='u1', event_key='buff', ts_ms=900, line_no=1, source_character_key='chr_b', source_character_name='乙',
            target_character_key='chr_a', target_character_name='甲', bb_values={'rate': .2}, bb_keys=['z', 'a', 'a'], test_labels=['增伤', '增幅'])
        for records, line in itertools.product([[], [record], [record, record], [record | dict(end_ts_ms=1000, end_line_no=10)],
                [record | dict(snapshot_end_ts_ms=1000, snapshot_end_line_no=11)]], [0, 10]):
            add('modifier-details', 'allocate', hit=base | dict(line_no=line, packet_modifier_uids={'attacker': ['u1'], 'defender': ['missing']}),
                buff_records={'u1': records})
        for shares, debug_enabled in itertools.product([{'chr_a': 70., 'chr_b': 30.}, {}, {'chr_a': 70, 'chr_b': 30},
                {'chr_b': 30, 'chr_c': 20.}, {'chr_a': 100., 'zero': 0., 'negative': -1.}], [False, True]):
            add('recorded-ink', 'allocate', hit=base | dict(_ink_allocation=shares, ink_provenance={'status': 'observed', 'source_hits': [1, 2]}), debug=debug_enabled)
        window = dict(uid='u1', event_key='external', source_character_key='chr_b', target_character_key='chr_a',
            target_actor_id='a1', start_ts_ms=900, start_line_no=1, end_ts_ms=1100)
        for debug_enabled in [False, True]:
            add('resistance-explanation', 'allocate', hit=base | dict(packet_attr_details={'defender': ['98:20']}),
                windows=[window | dict(target_character_key='enemy', target_actor_id='e1', zone_effects=[dict(zone='res', element='fire', rate=10)])], debug=debug_enabled)
            add('product-explanation', 'allocate', windows=[window | dict(zone_effects=[dict(zone='prod_dmg_inc', element='all', rate=.2)]),
                window | dict(uid='self', event_key='self', source_character_key='chr_a', zone_effects=[dict(zone='prod_dmg_inc', element='all', rate=.1)])], debug=debug_enabled)
            add('mixed-anomaly-explanation', 'allocate', hit=base | dict(damage_decorate_mask=0x40000008,
                static_arts_strength_entries=[dict(zone='arts_strength', rate=120)]),
                windows=[window | dict(zone_effects=[dict(zone='arts_strength', rate=100, element='all')])], debug=debug_enabled)
            add('exact-ink-integers', 'allocate', hit=base | dict(_ink_allocation={'chr_a': 70, 'chr_b': 10**400, 'chr_c': 10**400 + 1},
                ink_provenance={'status': 'observed'}), debug=debug_enabled)
            add('ink-leading-integer-sum', 'allocate', hit=base | dict(_ink_allocation={'chr_a': 70, 'chr_b': 10**100, 'chr_c': -10**100, 'chr_d': .5},
                ink_provenance={'status': 'observed'}), debug=debug_enabled)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    inputs = {'allocation-contributors': hashlib.sha256(source.read_bytes()).hexdigest()} if args.part == 'hit' else {}
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies, inputs=inputs), indent=2), encoding='utf8')
    print(f'Allocation {args.part} fixtures:', len(cases))


if __name__ == '__main__':
    main()
