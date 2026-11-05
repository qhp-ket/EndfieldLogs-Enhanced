"""Build packet display projection cases from the immutable Python reference."""
import argparse
import copy
import gzip
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundled', action='store_true')
    parser.add_argument('--labels', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures' / ('buff-labels.json' if args.labels else 'packet-effect-display.json')
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed packet display reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    prefix = '_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    packet = importlib.import_module('parser_core.effects.packet_mapping')
    semantics = importlib.import_module('parser_core.catalog.packet_semantics')
    enhanced = importlib.import_module('parser_core.effects.typed_actions')
    labels = importlib.import_module('parser_core.effects.labels')
    semantic = importlib.import_module('parser_core.effects.semantic_conditions')
    classification = importlib.import_module('parser_core.effects.classification')
    approval = importlib.import_module('parser_core.effects.approval')
    conditions = importlib.import_module('parser_core.effects.conditions')
    templates = importlib.import_module('parser_core.catalog.buff_templates')
    shared = dict(mappings={}, mechanisms={}, numbers={}, semantics={}, details={}, roots={}, registry={}, zones={}, classifier={})
    current = {}
    packet._load_packet_numeric_buff_map = lambda: current.get('mappings', {})
    packet._load_mechanism_registry_by_buff_id = lambda: current.get('mechanisms', {})
    packet._load_num_id_str_buff_map = lambda: current.get('numbers', {})

    def canonical():
        groups = {}
        for row in current.get('mappings', {}).values():
            if row.get('canonical_buff_id'):
                groups.setdefault(str(row['canonical_buff_id']), []).append(row)
        return {key: semantics._merge_packet_buff_mapping_rows(rows) for key, rows in groups.items()}
    packet._load_packet_canonical_buff_map = canonical
    enhanced._load_local_buff_semantic_entries = lambda: current.get('semantics', {})
    classification._load_local_buff_semantic_entries = enhanced._load_local_buff_semantic_entries
    classification._buff_classifier_hint = lambda key: current.get('classifier', {}).get(key)
    semantic._load_current_buff_roots = lambda: current.get('roots', {})
    semantic._load_damage_zone_config = lambda: current.get('zones', {})
    conditions._load_current_buff_roots = semantic._load_current_buff_roots
    approval._load_current_buff_roots = semantic._load_current_buff_roots
    approval._load_rdps_semantics_registry = lambda: current.get('registry', {})
    approval._load_num_id_str_buff_map = lambda: current.get('numbers', {})
    approval._load_num_id_str_skill_map = lambda: {}
    cases = []

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        return value

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        common_paths = {}
        def add(label, record=None, **resources):
            config = dict(record=record or {}, **resources)
            current.clear()
            current.update(shared)
            current.update(copy.deepcopy(resources))
            before = encode(config)
            detail_paths = {} if 'details' in resources else common_paths
            if 'details' in resources or not common_paths:
                for index, (key, payload) in enumerate(current.get('details', {}).items()):
                    path = root / f'{len(cases) if "details" in resources else "shared"}-{index}.json'
                    path.write_text(json.dumps(payload), encoding='utf8')
                    detail_paths[key] = path
            enhanced._buff_decoded_detail_path = detail_paths.get
            enhanced._enhanced_action_child_effect_specs.cache_clear()
            record = copy.deepcopy(config['record'])
            result = {}
            conditions._decoded_damage_modifier_condition_rows.cache_clear()
            operations = [('labels', labels._collect_buff_labels)] if args.labels else [('static', packet._packet_numeric_effects),
                                   ('dynamic', packet._packet_numeric_dynamic_effects),
                                   ('stack', packet._packet_mapping_stack_limit)]
            for key, operation in operations:
                try:
                    result[key] = operation(record)
                except (TypeError, ValueError, OverflowError, AttributeError) as error:
                    result[key] = dict(error=type(error).__name__)
            if args.labels:
                value = result['labels']
                result = value if isinstance(value, dict) and 'error' in value else dict(record=record, labels=value)
            if encode(config) != before or not args.labels and encode(record) != encode(config['record']):
                raise AssertionError('Packet display reference changed source evidence')
            cases.append(dict(name=f'{label}/{len(cases)}', config_json=json.dumps(config, ensure_ascii=True), expected=encode(result)))

        if args.bundled:
            archive = '_internal/data/runtime-data.zip'
            pinned(archive)
            with zipfile.ZipFile(args.reference / archive) as bundle:
                def resource(relative):
                    path = '_internal/' + relative
                    return json.loads(pinned(path)) if path in metadata['files'] else json.loads(bundle.read(relative))
                shared['mappings'] = resource('data/packet_semantics/buff_numeric_map.json')['mappings']
                shared['mechanisms'] = resource('data/packet_semantics/mechanism_registry.json')['by_buff_id']
                shared['semantics'] = resource('data/local_semantics/buff/details.json')['entries']
                if args.labels:
                    shared['classifier'] = resource('data/local_semantics/classifier_hints.json')['buffHints']
                    typed_roots = json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))['entries']
                    shared['registry'] = resource('data/packet_semantics/rdps_semantics_registry.json')
                    zone_path = root / 'data/local_static/damage_zone_config.json'
                    zone_path.parent.mkdir(parents=True)
                    zone_path.write_text(json.dumps(resource('data/local_static/damage_zone_config.json')), encoding='utf8')
                    templates._repo_root = lambda: root
                    templates._load_damage_zone_config.cache_clear()
                    shared['zones'] = templates._load_damage_zone_config()
                for name in bundle.namelist():
                    if name.startswith('data/akedata/buff/items/') and name.endswith('.json'):
                        shared['details'][Path(name).stem] = json.loads(bundle.read(name))
            def bb_keys(node):
                if isinstance(node, dict):
                    for field, value in node.items():
                        if (field.endswith('_bb_key') or field in {'bb_key', 'prefer_runtime_rate_key', 'blackboardKey'}) and value:
                            yield str(value)
                        elif field.endswith('_bb_keys') and isinstance(value, list):
                            yield from (str(key) for key in value)
                        else: yield from bb_keys(value)
                elif isinstance(node, list):
                    for value in node: yield from bb_keys(value)
            for key, mapping in shared['mappings'].items():
                for bb in [{}, {key: .2 for key in bb_keys(mapping)}]:
                    add('bundled-map', dict(event_key=mapping.get('canonical_buff_id', key), raw_event_key=key, bb_values=bb))
            # Exact reverse-parent traversal, including duplicate, missing and mismatched child actions.
            for key, details in shared['details'].items():
                children = set()
                def walk(node):
                    if isinstance(node, dict):
                        if 'EnhancedAction+Data' in str(node.get('$type') or '') and node.get('asChildBuff'):
                            child = (node.get('childBuffId') or {}).get('value')
                            if child: children.add(child)
                        for value in node.values(): walk(value)
                    elif isinstance(node, list):
                        for value in node: walk(value)
                walk(details)
                for child in sorted(children):
                    add('bundled-enhanced', dict(event_key=child, bb_values=dict(rate=.3)))
            if args.labels:
                for key, entry in typed_roots.items():
                    observed = set()
                    def keys(node):
                        if isinstance(node, dict):
                            if node.get('useBlackboardKey') is True and isinstance(node.get('blackboardKey'), str):
                                observed.add(node['blackboardKey'])
                            for value in node.values(): keys(value)
                        elif isinstance(node, list):
                            for value in node: keys(value)
                    keys(entry['root'])
                    for enemy in [False,True]:
                        add('bundled-label', dict(event_key=key, source_character_key='chr_test', target_enemy_key='enemy' if enemy else None,
                            bb_values={key:.2 for key in observed}, bb_keys=sorted(observed)), roots={key:entry['root']})
        else:
            static = dict(zone='amp', element='fire', bb_key='rate', prefer_runtime_rate_key='fallback', rate=.6)
            dynamic = dict(zone='amp', element='all', base_bb_keys=['alias', 'base'], base_bb_key='base', base_rate=.1,
                           tick_bb_keys=['tick', 'tick2'], tick_rate=.03, tick_multiplier=2,
                           add_bb_key='add', delayed_add_rate=.4, delay_bb_key='delay', delay_sec=2,
                           max_bb_key='max', max_rate=1, dynamic_key='display')
            values = [None, False, True, -1, -0., 0, .2, 1, '0.2', ' 1_0 ', 'bad', [], {},
                      float('nan'), float('inf'), -float('inf'), 10**400]
            for allowed in [None, False, True, 'constant', 'STATIC_LITERAL', 'runtime']:
                hint = dict(effects=[static], dynamic_effects=[dynamic])
                if isinstance(allowed, str): hint['value_source'] = allowed
                else: hint['allow_static_rate'] = allowed
                for field in ['rate', 'fallback', 'base', 'alias', 'tick', 'tick2', 'add', 'delay', 'max']:
                    for value in values:
                        add('runtime-operand', dict(event_key='buff', packet_mapping=hint, bb_values={field: value}))
            for left, right in itertools.product([None, 0, -.2, .2, .3, True], repeat=2):
                add('alias-order', dict(packet_mapping=dict(dynamic_effects=[dynamic]), bb_values=dict(alias=left, base=right, tick=left, tick2=right)))
            for zone, element in itertools.product(['atk', 'res', 'dmg_inc', 'amp', 'combo', 'vuln_taken', 'fragile', 'crit', '', None],
                                                    ['all', '', None, 'crystal', 'Fire', False]):
                add('zone-element', dict(packet_mapping=dict(allow_static_rates=True, effects=[dict(static, zone=zone, element=element)],
                      dynamic_effects=[dict(dynamic, zone=zone, element=element)])))
            for key in ['physical_res_down', 'physical_vulnerable_dmg_increase', 'phy_resist_down', 'PHY_RESIST_DOWN', 'other', '']:
                add('damage-condition', dict(packet_mapping=dict(effects=[dict(static, bb_key=key)]), bb_values={key:.2, 'fallback':.3}))
            for value in [[], ['base'], ['alias', 'base'], ['', None, False, 0, 'base'], 'base', {'base':1}, 4]:
                for field in ['base_bb_keys', 'tick_bb_keys']:
                    spec=dict(dynamic); spec[field]=value
                    add('key-shape', dict(packet_mapping=dict(dynamic_effects=[spec]), bb_values=dict(base=.2, tick=.1)))
            for value in values:
                add('multiplier', dict(packet_mapping=dict(dynamic_effects=[dict(dynamic,tick_multiplier=value)]), bb_values=dict(tick=.1)))
                for field in ['max_stack', 'stack_limit', 'maxStack', 'stackLimit']:
                    add('stack-value', dict(packet_mapping=dict(stack_limit=7), bb_values={field:value}))
            for value in [None, [], {}, [None], [None,static], 'invalid', 1]:
                add('spec-shape', dict(packet_mapping=dict(effects=value,dynamic_effects=value), bb_values=dict(rate=.2,base=.3)))
            for value in [[], {}, False, None, 1, ['rate'], 'rate']:
                add('blackboard-shape', dict(packet_mapping=dict(effects=[static], dynamic_effects=[dynamic]), bb_values=value))
            maps = {'10':dict(canonical_buff_id='buff',effects=[static]),
                    '11':dict(canonical_buff_id='buff',effects=[static,dict(static,zone='crit')],stack_limit=4)}
            for key in ['10','11','buff','12',None]:
                add('mapping-resolution', dict(event_key=key,bb_values=dict(rate=.2)),mappings=maps)
            for explicit in [{}, [], None, dict(effects=[])]:
                add('explicit-mapping',dict(event_key='10',packet_mapping=explicit,bb_values=dict(rate=.2)),mappings=maps)
            for rows in [[dict(effects=[static],stack_limit=2)],[],[dict(effects=[static]),dict(effects=[static])]]:
                add('mechanism-resolution', dict(event_key='12',bb_values=dict(rate=.2)),numbers={'12':'buff'},mechanisms={'buff':rows})
            action = {'$type':'Beyond.Gameplay.Core.EnhancedAction+Data','asChildBuff':True,'childBuffId':{'value':'child'},
                      'subType':'Crystal','rate':{'blackboardKey':'enhanced'}}
            for subtype, enabled, child in itertools.product(['Crystal','cryst','fire','pulse','natural','physical','spell','all','unknown',''],[False,True],['child','other']):
                changed=dict(action,subType=subtype,asChildBuff=enabled,childBuffId=dict(value=child))
                add('enhanced-child',dict(event_key='child',bb_values=dict(enhanced=.2,rate=.3)),
                    semantics={'p':dict(referencedBuffIds=['child'])},details={'p':dict(actions=[changed,changed])})
            for hint in [{},dict(effects=[]),dict(effects=None)]:
                add('enhanced-vs-explicit',dict(event_key='child',packet_mapping=hint,bb_values=dict(rate=.3)),
                    semantics={'z':dict(referencedBuffIds=['child']),'a':dict(referencedBuffIds=['child']),'missing':dict(referencedBuffIds=['child'])},
                    details={'a':dict(nodes=[action]),'z':dict(nodes=[action,dict(action,subType='fire')])})
            if args.labels:
                cases.clear()
                names=['buff','buff_physical_no_guard','buff_physical_knockdown','buff_physical_airborne','buff_physical_crushed',
                    'buff_common_cryst_triggered_physical_break','buff_common_conduct_triggered','buff_common_natural_fire_triggered_wrapper',
                    'buff_common_natural_natural_triggered','buff_common_corrupt_do','buff_fire_fire_triggered','buff_common_fire_fire_triggered',
                    'buff_common_pulse_pulse_triggered_do','buff_frozen','buff_common_affixes_combo_trigger','buff_chr_0015_lifeng_purify',
                    'buff_chr_0015_lifeng_normal_skill_debuff','buff_chr_0015_lifeng_normal_skill_debuff_icon','buff_chr_0029_pograni_talent2',
                    'buff_equipsuit_atk_02_aruadetect','buff_common_vfx_test','buff_common_affixes_slow','buff_chr_0011_seraph_atk_buff',
                    'buff_wpn_sword_0016_team','buff_vulnerable','buff_enhance_fire','buff_spellup','buff_criticalrate','buff_combo_damage']
                bb_keys=['atk_up','physical_res_down','phy_resist_down','physical_vulnerable_dmg_increase','ratio_speed','ratio_speedreduction',
                    'crit_up','critical_rate','crit_dmg','critical_damage_inc','fire_up','dmg_up','normal_atk_up_valid','fire_taken_up',
                    'def_down_damage','def_decrease','additional_def_decrease','fire_vul','rate_vulnerable','enhance_fire','taken_up_fire',
                    'damage_taken_up_pulse','fire_resistance_decrease','fire_resistance_down','ignore_fire_resist','combo_damageup',
                    'atk_scale','extra_atk_scale','burning_atk_scale','rate','duration','atk_up_add','pd_up','spell_up','noise']
                for name,enemy,source in itertools.product(names,[False,True],['chr_test','chr_0029_pograni']):
                    add('anomaly-and-keys',dict(event_key=name,source_character_key=source,target_enemy_key='enemy' if enemy else None,
                        bb_keys=bb_keys,bb_values={key:.2 for key in bb_keys}))
                for key,enemy in itertools.product(bb_keys,[False,True]):
                    add('individual-key',dict(event_key='buff',target_enemy_key='enemy' if enemy else None,bb_keys=[key]))
                for attr,key,value in itertools.product([2,9,10,17,28,32,33,50,51,52,53,54,55,65,66,67,68,70,71,75,80,85,86,87,999],
                        ['','dmg_up','physical_res_down','def_decrease','DEF_DECREASE'],[.2,None]):
                    add('attribute-label',dict(event_key='buff',bb_values=dict(physical_res_down=value),attr_mods=[dict(attr_type=attr,bb_key=key)]))
                for value in [None,False,True,-1,2,2.8,'2','2.8','bad',float('nan'),float('inf'),10**400]:
                    add('attribute-coercion',dict(event_key='buff',attr_types=[value]))
                for role,attrs in itertools.product(['wrapper','effect','utility'],[[],[dict(attr_type=2)]]):
                    add('wrapper-label',dict(event_key='buff',packet_mapping=dict(role=role),bb_keys=['atk_up'],attr_mods=attrs))
                modifier=dict(enableSide='Attacker',condition=dict(onlyExecuteWhenSourceIsMainChar=False,onlyExecuteWhenSourceIsGuard=False,actionData=[]),
                    damageProcessors=[{'$type':'Beyond.Gameplay.Core.DamageScaleProcessor','side':'Attacker','zoneName':'NormalCalcZone',
                    'addition':dict(useBlackboardKey=True,blackboardKey='dmg_up')}])
                zones={'NormalCalcZone':{}}
                for name in ['buff','buff_common_vfx_test','buff_common_affixes_slow']:
                    for modifier_zone,side in itertools.product(['NormalCalcZone','unknown'],['Attacker','Defender']):
                        changed=copy.deepcopy(modifier); changed['damageProcessors'][0].update(zoneName=modifier_zone,side=side)
                        add('semantic-label',dict(event_key=name,bb_values=dict(dmg_up=.2),bb_keys=['dmg_up'],
                            packet_mapping=dict(effects=[dict(zone='amp',bb_key='dmg_up')])),roots={name:dict(damageModifier=[changed])},zones=zones)
        fixture = dict(resources_json=json.dumps(shared,ensure_ascii=True),cases=cases)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(fixture,ensure_ascii=True,separators=(',',':')),encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'],cases=len(cases),dependencies=dependencies),indent=2),encoding='utf8')
        print('BUFF label fixtures:' if args.labels else 'Packet display fixtures:',len(cases))


if __name__ == '__main__': main()
