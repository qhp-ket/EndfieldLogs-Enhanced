"""Freeze full BUFF descriptions, effect summaries and packet-boundary segments from the fixed reference."""
import argparse
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
from types import ModuleType

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--window-fixture', type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures'
    output = args.output or fixtures / 'report-buffs.json'
    seed_path = args.window_fixture or fixtures / 'report-effect-windows.json'
    seed = json.loads(seed_path.read_text(encoding='utf8'))
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed report BUFF reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    report = importlib.import_module('parser_core.reporting.buffs')
    names = ['catalog.buff_templates', 'effects.packet_mapping', 'catalog.packet_semantics', 'effects.approval',
             'effects.semantic_conditions', 'effects.conditions', 'effects.specifications', 'effects.classification',
             'effects.typed_actions', 'effects.stacking_rules', 'effects.lifecycle', 'effects.windows', 'effects.imbue', 'effects.registry']
    modules = {name: importlib.import_module('parser_core.' + name) for name in names}
    current = {}
    for module in modules.values():
        module._load_current_buff_roots = lambda: current['roots']
        module._load_local_buff_semantic_entries = lambda: current['semantics']
        module._buff_classifier_hint = lambda key: current['classifier'].get(key)
        module._load_num_id_str_buff_map = lambda: current['numbers']
    templates = modules['catalog.buff_templates']
    approval = modules['effects.approval']
    mapping = modules['effects.packet_mapping']
    packet = modules['catalog.packet_semantics']
    modules['effects.semantic_conditions']._load_damage_zone_config = lambda: current['zones']
    approval._load_rdps_semantics_registry = lambda: current['registry']
    approval._load_num_id_str_skill_map = lambda: current['skills']
    mapping._load_packet_numeric_buff_map = lambda: current['mappings']
    mapping._load_mechanism_registry_by_buff_id = lambda: current['mechanisms']

    def canonical_mappings():
        groups = {}
        for row in current['mappings'].values():
            if row.get('canonical_buff_id'):
                groups.setdefault(str(row['canonical_buff_id']), []).append(row)
        return {key: packet._merge_packet_buff_mapping_rows(rows) for key, rows in groups.items()}

    mapping._load_packet_canonical_buff_map = canonical_mappings
    shared = json.loads(seed['resources_json'])
    current.update(shared)
    cases = []

    def add(kind, label, config):
        state = copy.deepcopy(config)
        current.clear()
        current.update(shared)
        current.update({key: value for key, value in state.items() if key in shared})
        packet._RDPS_VERIFIED_INDEX = None
        modules['effects.conditions']._decoded_damage_modifier_condition_rows.cache_clear()
        modules['effects.typed_actions']._enhanced_action_child_effect_specs.cache_clear()
        try:
            if kind == 'summaries':
                result = report._effect_summary_rows(state['effects'])
            elif kind == 'segments':
                result = report._effect_segments_for_event(start_ts_ms=state['start'], end_ts_ms=state['end'],
                                                           zone_effects=state['static'], dynamic_effects=state['dynamic'])
            else:
                events = report._build_buff_events(state['records'], state['windows'], battle_start_ms=state['start'], battle_end_ms=state['end'])
                result = dict(records=state['records'], events=events)
        except (TypeError, ValueError, OverflowError, KeyError, AttributeError) as error:
            result = dict(error=type(error).__name__)
        cases.append(dict(name=f'{len(cases):04d}-{label}', kind=kind, config_json=json.dumps(config), expected=canonical(result)))

    with tempfile.TemporaryDirectory() as folder:
        templates._repo_root = lambda: Path(folder)
        for test in seed['cases']:
            config = json.loads(test['config_json'])
            config.update(start=1000, end=config.pop('last_hit_ms'))
            config['windows'] = [dict(uid=row.get('uid'), event_key=row.get('event_key'), source_character_key=row.get('source_character_key'),
                                      target_character_key=row.get('target_character_key') or row.get('target_enemy_key'), start_ts_ms=row.get('ts_ms'))
                                 for index, row in enumerate(config['records']) if index % 2 == 0]
            for field in ['hits', 'arts', 'active_suits', 'active_weapons']:
                config.pop(field, None)
            add('events', test['name'], config)

    def segments(label, dynamic=None, static=None, start=1000, end=2000):
        add('segments', label, dict(start=start, end=end, static=static or [], dynamic=dynamic or []))

    segments('static-negative-midnight', static=[dict(zone='res', rate=15)], start=-1, end=86400001)
    keyword = dict(zone='dmg_inc', element='all', base_rate=.1, keyword_session_id='session', keyword_rate_snapshots=[])
    states = [dict(ts_ms=1000, line_no=2, operation_seq=1, session_id='session', status='observed', rate_after=.2),
              dict(ts_ms=1000, line_no=3, operation_seq=2, session_id='session', status='unknown', rate_after=.3),
              dict(ts_ms=1500, line_no=4, operation_seq=3, session_id='session', status='observed', rate_after=.4),
              dict(ts_ms=1700, line_no=5, operation_seq=2, session_id='session', status='observed', rate_after=.5),
              dict(ts_ms=1900, line_no=6, operation_seq=9, session_id='other', status='observed', rate_after=.8),
              dict(ts_ms=2001, line_no=7, operation_seq=10, session_id='session', status='observed', rate_after=.9)]
    for length in range(len(states) + 1):
        effect = dict(keyword, keyword_rate_snapshots=states[:length])
        segments('keyword-boundaries', [effect])
        add('summaries', 'keyword-history', dict(effects=[effect]))
    for order in itertools.permutations(states[:3]):
        segments('keyword-input-order', [dict(keyword, keyword_rate_snapshots=order)])
    for status, values in itertools.product(['attribute_parameters_observed', 'unknown'], [{}, {'a': 0}, {'a': -10}, {'a': 5}, {'a': '-5'}, {'a': None}]):
        effect = dict(zone='res', element='physical', parameter_keys=['a'], parameter_snapshots=[
            dict(ts_ms=1000, operation_seq=1, status=status, bb_values=values),
            dict(ts_ms=1000, operation_seq=2, status='unknown', bb_values={}),
            dict(ts_ms=2000, operation_seq=3, status='attribute_parameters_observed', bb_values={'a': -20})])
        segments('resistance-refresh', [effect])
        add('summaries', 'refresh-summary', dict(effects=[effect]))
    for delay, add_rate, tick, maximum, points in itertools.product([0, .5, 1, 2], [0, .2], [0, .1], [0, .5], [[], [[900, .1], [1500, .3]], [[2100, .4], [2200, .5]]]):
        effect = dict(zone='amp', base_rate=.1, delayed_add_rate=add_rate, delay_sec=delay, tick_rate=tick, max_rate=maximum, observed_points=points)
        segments('dynamic-modes', [effect])
        add('summaries', 'dynamic-summary', dict(effects=[effect, effect]))
    rng = random.Random(44021)
    rates = [None, 0, -0., .02675, 2.675, -1, 1e-7, 1e9, 'invalid'] + [rng.uniform(-1e6, 1e6) for _ in range(80)]
    for zone, rate in itertools.product(['res', 'dmg_inc', 'custom'], rates):
        add('summaries', 'rates', dict(effects=[dict(zone=zone, rate=rate)]))
    for kind, compare, ratio in itertools.product(['target_hp_ratio_lte', 'target_hp_compare'], ['LT', 'LE', 'GT', 'GE', 'EQ', 'NE', 'UNKNOWN'], [True, False]):
        add('summaries', 'hp-condition', dict(effects=[dict(zone='amp', rate=.2, condition=dict(type=kind, compare=compare, is_ratio=ratio, threshold=.5))]))
    add('summaries', 'damage-condition', dict(effects=[dict(zone='dmg_inc', rate=.1, condition=dict(type='damage_type_in', elements=['fire', '', None, 'physical']))]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(resources_json=seed['resources_json'], cases=cases), ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        seed_sha256=hashlib.sha256(seed_path.read_bytes()).hexdigest(), dependencies=dependencies), indent=2), encoding='utf8')
    print('Report BUFF detail fixtures:', len(cases))


if __name__ == '__main__':
    main()
