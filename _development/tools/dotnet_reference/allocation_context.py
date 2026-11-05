"""Freeze the real per-hit allocation preparation phase from the immutable Python reference."""
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
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixtures / 'allocation-context.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed allocation context reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    context = importlib.import_module('parser_core.allocation.context')
    attack = importlib.import_module('parser_core.allocation.attack_model')
    base = dict(character_key='chr_a', target_enemy_key='enemy', source_actor_id='a1', target_actor_id='e1',
        ts_ms=1000, line_no=10, skill_key='skill', hit_value=100, damage_element='fire', damage_school='spell')
    window = dict(uid='u1', target_character_key='enemy', start_ts_ms=900, end_ts_ms=1100, start_line_no=1,
        event_key='buff', zone_effects=[dict(zone='vuln_taken', rate=.2)])
    record = dict(uid='u1', target_enemy_key='enemy', target_actor_id='e1', ts_ms=900, line_no=1,
        raw_duration_ms=500, event_key='buff')
    cases = []

    def add(label, hit=None, windows=None, records=None, by_target=None, indices=None, units=None, debug=False):
        config = dict(hit=base | (hit or {}), windows=windows or [], records=records, by_target=by_target,
            indices=indices, units=units or {}, debug=debug)
        owned = json.loads(json.dumps(config, ensure_ascii=True))
        attack._load_skill_action_damage_units = lambda skill: owned['units']
        state = context.HitAllocation(hit=owned['hit'], buff_windows=owned['windows'], include_debug=debug,
            buff_records_by_uid=None, condition_buff_records=owned['records'], condition_records_by_target=owned['by_target'],
            effect_window_indices=owned['indices'], condition_records_by_uid=None, condition_records_by_actor=None)
        try:
            context.prepare_allocation(state)
            result = {key: getattr(state, key) for key in ['hit', 'buff_windows', 'attacker_key', 'target_enemy_key', 'hit_value',
                'hit_ts_ms', 'damage_element', 'damage_school', 'arts_strength_damage_hit', 'attack_kind', 'calculation',
                'packet_modifier_uids', 'packet_attr_details', 'hit_line_no', 'resistance_attr_type', 'resistance_rows',
                'effective_resistance', 'resistance_numerator', 'resistance_source']}
            result.update(attacker_modifier_uids=sorted(state.attacker_modifier_uids), defender_modifier_uids=sorted(state.defender_modifier_uids),
                defender_allowed_effects=sorted(state.defender_allowed_effects), window_indices=list(state.window_indices),
                matched_packet_defender_effect_signatures=list(state.matched_packet_defender_effect_signatures),
                active_target_buff_ids=sorted(state.active_target_buff_ids))
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            result = dict(error=type(exc).__name__)
        cases.append(dict(name=f'{len(cases):05d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    for element, rows, conflict in itertools.product([None, 'physical', 'fire', 'natural', 'cryst', 'pulse', 'ether', 'unknown'],
            [[], ['98:20'], ['98:20,20'], ['98:20', '98:20'], ['98:20,21'], ['98:bad'], ['98:'], ['98'],
             ['98:nan'], ['98:inf'], ['98:-10'], ['98:1000'], ['98:0'], ['98:20', '94:30'], ['094:10'], ['94:10'],
             ['95:10'], ['96:10'], ['97:10'], ['99:10']], [False, True]):
        add('resistance', dict(damage_element=element, packet_attr_details=dict(defender=rows), packet_attr_conflict=conflict))
    for mask, previous, source in itertools.product([None, 0, 256, 0x4000, 0x40004000, True, '16', -1, 1 << 64],
            [False, True], [None, 'caller_supplied_classification', 'stale']):
        add('runtime-anomaly', dict(damage_decorate_mask=mask, arts_strength_damage_observed=previous, arts_strength_damage_source=source))
    for mask, source in itertools.product([None, 0, 256, 0x4000, 0x40004000, True, '16', -1, 1 << 64],
            [None, 'current_typed_skill_or_buff_exact_unit_generation_only', 'stale']):
        add('template-anomaly', dict(static_damage_decorate_mask=mask, static_damage_decorate_mask_source=source))
    for modifiers, attrs, actor in itertools.product([None, [], 'invalid', {}, dict(attacker=[0, False, None, 'a', ''], defender=['u1', 'u1', '']),
            dict(attacker='abc', defender='u1')], [None, [], 'invalid', {}, dict(defender=['32:x', '98:10'])], [None, 'a1']):
        add('packet-shapes', dict(packet_modifier_uids=modifiers, packet_attr_details=attrs, source_actor_id=actor), records=[record])
    for seen, indices, debug in itertools.product([False, True], [None, [], [0], [1], [1, 0]], [False, True]):
        hit = dict(packet_modifier_seen=seen, packet_modifier_uids=dict(defender=['u1']))
        add('selection', hit, windows=[window, dict(window, uid='u2', requires_enable_observation=True)],
            records=[record], indices=indices, debug=debug)
    attacker = dict(record, target_enemy_key='', target_character_key='chr_a', target_actor_id='a1', event_key='self')
    for by_target in [None, {}, {'enemy': [record]}, {'chr_a': [attacker]}, {'enemy': [record], 'chr_a': [attacker]}]:
        add('indexed-conditions', records=[record, attacker], by_target=by_target)
    reference_inputs = fixtures / 'attack-dependence.json'
    for source in json.loads(reference_inputs.read_text(encoding='utf8')):
        config = json.loads(source['config_json'])
        add('attack-' + source['name'], hit=config['hit'], units=config['units'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies, inputs={'attack-dependence': hashlib.sha256(reference_inputs.read_bytes()).hexdigest()}), indent=2), encoding='utf8')
    print('Allocation context fixtures:', len(cases))


if __name__ == '__main__':
    main()
