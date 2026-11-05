"""Freeze packet classification and complete allocation preflight from the fixed Python reference."""
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
    if type(value) is int:
        return {'int': str(value)}
    if type(value) is float:
        return {'f64': struct.pack('>d', value).hex()}
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixtures / 'allocation-preflight.json'
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
    load = lambda name: importlib.import_module('parser_core.' + name)
    preflight, mapping, registry = load('allocation.preflight'), load('effects.packet_mapping'), load('effects.registry')
    templates, semantic, approval = load('catalog.buff_templates'), load('effects.semantic_conditions'), load('effects.approval')
    conditions, packet, specifications, lifecycle = (load(name) for name in ('effects.conditions', 'catalog.packet_semantics', 'effects.specifications', 'effects.lifecycle'))
    current = {}
    roots = lambda: current.get('roots', {})
    for module in (registry, semantic, conditions, approval, specifications, lifecycle):
        module._load_current_buff_roots = roots
    semantic._load_damage_zone_config = lambda: current.get('zones', {})
    approval._load_rdps_semantics_registry = lambda: current.get('registry', {})
    approval._load_num_id_str_buff_map = lambda: current.get('numbers', {})
    approval._load_num_id_str_skill_map = lambda: {}
    mapping._load_num_id_str_buff_map = approval._load_num_id_str_buff_map
    mapping._load_packet_numeric_buff_map = lambda: current.get('mappings', {})
    def canonical_mappings():
        groups = {}
        for row in current.get('mappings', {}).values():
            if row.get('canonical_buff_id'):
                groups.setdefault(str(row['canonical_buff_id']), []).append(row)
        return {key: packet._merge_packet_buff_mapping_rows(rows) for key, rows in groups.items()}
    mapping._load_packet_canonical_buff_map = canonical_mappings
    mapping._load_mechanism_registry_by_buff_id = lambda: current.get('mechanisms', {})
    cases = []
    def add(operation='gate', **config):
        config = dict(operation=operation, **config)
        current.clear()
        current.update(copy.deepcopy(config))
        packet._RDPS_VERIFIED_INDEX = None
        templates._BUFF_ACTION_TYPES_INDEX = None
        conditions._decoded_damage_modifier_condition_rows.cache_clear()
        records = copy.deepcopy(config.get('records', []))
        try:
            if operation == 'classify':
                result = mapping._classify_packet_buff_record(copy.deepcopy(config['record']))
            elif operation == 'overlap':
                result = preflight._record_overlaps_window(config['record'], battle_start_ms=config['start'], battle_end_ms=config['end'])
            else:
                result = dict(summary=preflight._build_rdps_preflight(records, config.get('windows', []), hits=config.get('hits'),
                    unresolved_hits=config.get('unresolved_hits'), unresolved_buff_actions=config.get('unresolved_actions'),
                    battle_start_ms=config.get('start', 1000), battle_end_ms=config.get('end', 2000)), records=records)
        except (ValueError, TypeError, OverflowError, AttributeError, KeyError) as error:
            result = {'error': type(error).__name__}
        cases.append(dict(name=f'{len(cases):04d}-{operation}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    for raw, owner, keys, packet_mapping in itertools.product(['123', '²', '１２', 'buff_static', None, 0], ['', 'chr_a', 'eny_b'],
            [[], ['duration'], ['dodgeSkillId'], [''], ['Atk_Up', 'resist'], ['mystery'], ['phy_dmg_up', 'final_phy_dmg_up', 'shatter_dmg', 'consumed_layer']], [None, {}, {'role': 'effect', 'reason': 'observed'}]):
        add('classify', record=dict(raw_event_key=raw, owner_raw=owner, source_character_key='chr_a' if owner == 'eny_b' else None,
            bb_keys=keys, bb_values={key: 1 for key in keys}, packet_mapping=packet_mapping))
    for timestamp, observed_end, duration, snapshot in itertools.product([500, 1000, 2000, 2001], [None, 999, 1000, 1500, 999.5, '1500'],
            [None, 0, 500, 499.5, -1], [None, 999, 1000]):
        add('overlap', start=1000, end=2000, record=dict(ts_ms=timestamp, end_ts_ms=observed_end, raw_duration_ms=duration, snapshot_end_ts_ms=snapshot))
    add()
    hit = dict(seq=1, line_no=10, damage_element='fire', damage_element_source='official_action_unit', damage_school='arts', target_enemy_key='eny_b', packet_hit_value=0)
    for field in ['damage_element', 'damage_element_source', 'damage_school', 'target_enemy_key', 'packet_hit_value']:
        for value in [None, '', 0]:
            add(hits=[dict(hit, **{field: value})])
    add(hits=[hit])
    flags = ['rdps_unresolved_effect_conditions', 'rdps_unresolved_whitelist_effect', 'rdps_unresolved_static_multiplier_sources',
        'rdps_unresolved_target_binding', 'rdps_unresolved_attacker_binding', 'rdps_unresolved_dpd_residual']
    for bits in itertools.product([False, True], repeat=len(flags)):
        add(hits=[dict(hit, **dict(zip(flags, bits)), dpd_raw=dict(atk_zones=[1, None], def_zones=[1]))])
    for flags in [[], ['rdps_invalid_dynamic_evaluation'], ['rdps_unresolved_stack_evidence', 'rdps_unresolved_enable_evidence', 'rdps_snapshot_order_unresolved']]:
        add(windows=[dict(uid='u', event_key='buff', **{flag: True for flag in flags})])
    for timestamp in [999, 1000, 2000, 2001]:
        add(unresolved_hits=[dict(ts_ms=timestamp, reason='unresolved', custom=['retained'])],
            unresolved_actions=[dict(ts_ms=timestamp, reason='action'), dict(ts_ms=timestamp, uid_observation_only=True)])
    add(unresolved_actions=[dict(ts_ms=1500, reason='many', uid=str(index)) for index in range(300)])
    inputs = {}
    for filename in ['effect-specifications.json', 'dynamic-effect-specifications.json']:
        path = fixtures / filename
        inputs[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in json.loads(path.read_text(encoding='utf8')):
            config = json.loads(row['config_json'])
            record = config.pop('record')
            config.pop('operation', None)
            record.setdefault('ts_ms', 1500)
            add(records=[record], **config)
            record.setdefault('raw_duration_ms', 1000)
            record.setdefault('uid', 'observed')
            add(records=[record], windows=[dict(uid=record['uid'], uid_aliases=['alias'])], **config)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies, inputs=inputs), indent=2), encoding='utf8')
    print('Allocation preflight fixtures:', len(cases))


if __name__ == '__main__':
    main()
