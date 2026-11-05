"""Compare reviewed effect rates, validation evidence and typed structural classification."""
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
    parser.add_argument('--specifications', action='store_true')
    parser.add_argument('--dynamic-specifications', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    if args.specifications and args.dynamic_specifications:
        parser.error('Select static or dynamic specifications')
    filename = ('dynamic-effect-specifications.json' if args.dynamic_specifications else
                'effect-specifications.json' if args.specifications else 'effect-registry.json')
    output_path = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures' / filename
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed effect registry reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    rules = importlib.import_module('parser_core.effects.registry')
    templates = importlib.import_module('parser_core.catalog.buff_templates')
    semantic = importlib.import_module('parser_core.effects.semantic_conditions')
    approval = importlib.import_module('parser_core.effects.approval')
    conditions = importlib.import_module('parser_core.effects.conditions')
    packet = importlib.import_module('parser_core.catalog.packet_semantics')
    specifications = importlib.import_module('parser_core.effects.specifications')
    current = {}
    rules._load_current_buff_roots = lambda: current.get('roots', {})
    semantic._load_current_buff_roots = rules._load_current_buff_roots
    conditions._load_current_buff_roots = rules._load_current_buff_roots
    semantic._load_damage_zone_config = lambda: current.get('zones', {})
    approval._load_rdps_semantics_registry = lambda: current.get('registry', {})
    approval._load_current_buff_roots = rules._load_current_buff_roots
    approval._load_num_id_str_buff_map = lambda: current.get('numbers', {})
    approval._load_num_id_str_skill_map = lambda: {}
    packet._RDPS_VERIFIED_INDEX = None
    templates._BUFF_ACTION_TYPES_INDEX = None
    specifications._load_current_buff_roots = rules._load_current_buff_roots
    mapping = importlib.import_module('parser_core.effects.packet_mapping')
    mapping._load_num_id_str_buff_map = approval._load_num_id_str_buff_map
    mapping._load_packet_numeric_buff_map = lambda: current.get('mappings', {})
    def canonical_mappings():
        groups = {}
        for row in current.get('mappings', {}).values():
            if row.get('canonical_buff_id'):
                groups.setdefault(str(row['canonical_buff_id']), []).append(row)
        return {key:packet._merge_packet_buff_mapping_rows(rows) for key,rows in groups.items()}
    mapping._load_packet_canonical_buff_map = canonical_mappings
    mapping._load_mechanism_registry_by_buff_id = lambda: current.get('mechanisms', {})
    cases = []

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        return value

    def add(kind, **config):
        current.clear()
        current.update(copy.deepcopy(config))
        before = encode(current)
        record = copy.deepcopy(current.get('record', {}))
        entry = current.get('entry', {})
        conditions._decoded_damage_modifier_condition_rows.cache_clear()
        try:
            if kind == 'rate': result = rules._rdps_registry_effect_runtime_rate(current['spec'], record)
            elif kind == 'zones': result = rules._rdps_registry_zone_effects(record, entry)
            elif kind == 'validate': result = rules._rdps_registry_validation_error(entry, record)
            elif kind == 'ignored': result = sorted(rules._rdps_registry_ignored_bb_keys(entry))
            elif kind == 'unknown': result = rules._rdps_registry_unrecognized_effect_bb_keys(entry, record)
            elif kind == 'classify': result = rules._classify_non_rdps_entry(record)
            elif kind == 'semantic': result = semantic._collect_semantic_condition_zone_effects(record)
            elif kind == 'specification': result = specifications._collect_zone_effects(record)
            elif kind == 'dynamic-specification': result = specifications._extract_dynamic_effect_specs(record)
            elif kind == 'condition': result = semantic._semantic_damage_effect_condition('buff', current['effect'], defaults={}, bb_values=current.get('bb_values', {}))
            elif kind == 'damage-zone': result = semantic._semantic_damage_effect_zone(current['effect'])
            elif kind == 'zone-config':
                with tempfile.TemporaryDirectory() as folder:
                    templates._repo_root = lambda: Path(folder)
                    if current.get('payload') is not None:
                        path = Path(folder) / 'data/local_static/damage_zone_config.json'
                        path.parent.mkdir(parents=True)
                        path.write_text(json.dumps(current['payload']), encoding='utf8')
                    templates._load_damage_zone_config.cache_clear()
                    result = templates._load_damage_zone_config()
            else: raise ValueError(kind)
            if kind in {'rate', 'zones', 'validate', 'semantic', 'specification', 'dynamic-specification'}: result = dict(record=record, result=result)
        except (TypeError, ValueError, OverflowError, AttributeError) as error:
            result = dict(error=type(error).__name__)
        if encode(current) != before:
            raise AssertionError('Reference mutated source config')
        cases.append(dict(name=f'{kind}/{len(cases)}', kind=kind,
                          config_json=json.dumps(config, ensure_ascii=True), expected=encode(result)))

    def rates(spec, records):
        entry = dict(effects=[spec])
        for record in records:
            add('rate', spec=spec, record=record)
            add('zones', entry=entry, record=record)
            add('validate', entry=entry, record=record)

    values = [None, False, True, -1, -0.0, 0, 1, .2, '0.2', ' 1_0 ', 'invalid', [], {},
              float('nan'), float('inf'), -float('inf'), 10**400]
    spec = dict(zone='amp', element='fire', bb_key='rate', bb_keys=['alias', 'rate', 'alias'],
                expose_bb_key=True, condition=dict(type='all', conditions=[dict(type='damage_element', elements=['fire'])]))
    rates(spec, [dict(bb_values=dict(rate=rate)) for rate in values])
    for left, right in itertools.product([None, .2, '0.2', .3, -1, True], repeat=2):
        rates(spec, [dict(bb_values=dict(rate=left, alias=right))])
    for keys in [[], ['rate'], ['alias', 'rate'], ['rate', 'alias'], [0, False, None, '', 'rate'], 'rate', {'rate': 1}]:
        rates(dict(spec, bb_keys=keys), [dict(bb_values=dict(rate=.2, alias=.2)), dict(bb_values=dict(alias=.3))])
    for source, rate, zone, element in itertools.product(['constant', 'STATIC_LITERAL', 'runtime', None], [None, .2, -1, False, '1'], ['atk', 'crit', 'combo', 'other'], ['all', '', 'spell', 'Fire']):
        rates(dict(value_source=source, rate=rate, zone=zone, element=element), [{}])
    formula = dict(zone='atk', formula='atk_add_plus_mult_consume_half_for_other_targets',
                   add_bb_key='add', mult_bb_key='mult', consume_bb_key='layers')
    for source, target, factor in itertools.product(['self', None], ['self', 'other', None], [.5, None, -1, 0, '0.3', float('inf')]):
        rates(dict(formula, other_target_multiplier=factor), [dict(source_character_key=source, target_character_key=target,
                     bb_values=dict(add=.13, mult=.07, layers=3))])
    for key, value in itertools.product(['add', 'mult', 'layers'], values):
        bb = dict(add=.1, mult=.2, layers=3)
        bb[key] = value
        rates(formula, [dict(bb_values=bb, source_character_key='self', target_character_key='other')])
    rates(dict(formula, bb_key='rate'), [dict(bb_values=dict(rate=.7, add=.1, mult=.2, layers=3)),
          dict(bb_values=dict(rate=-1, add=.1, mult=.2, layers=3)), dict(bb_values=dict(add=1e308, mult=1e308, layers=3))])
    for entry in [{}, dict(allowed_bb_keys=['*']), dict(allowed_bb_keys=['']), dict(effects=[spec], ignored_bb_keys=['ignored'], self_bb_keys=['self']),
                  dict(effects=[dict(bb_key='r', bb_keys=['alias'], required_bb_keys=['needed'], add_bb_key='add', max_bb_key='max', delay_bb_key='delay')])]:
        add('ignored', entry=entry)
        for record in [{}, dict(bb_keys=['duration', 'r', 'ignored']), dict(bb_values=dict(rate=.2, alias=.2)),
                       dict(attr_mods=[dict(bb_key='self'), dict(bb_key='unknown')]), dict(bb_keys=['\ue000', '\U00010000', 'MAX_STACK', 0, None])]:
            add('unknown', entry=entry, record=record)
            add('validate', entry=entry, record=record)
    for dynamic, guard, error in itertools.product([False, True], [None, ['rate'], ['*'], []], [None, 'semantic', 'dynamic', 'both']):
        entry = dict(effects=[spec], dynamic=dynamic, allowed_bb_keys=guard)
        record = dict(bb_values=dict(rate=.2), rdps_invalid_runtime_rate=True, rdps_conflicting_runtime_rate=True)
        if error in {'semantic', 'both'}: record['rdps_unresolved_semantic_condition'] = [dict(reason='unobserved')]
        if error in {'dynamic', 'both'}: record['rdps_unresolved_dynamic_effect'] = True
        add('validate', entry=entry, record=record)
    for effects in [[], [None], [False], [spec, None], [dict(spec, zone='invalid')], [dict(spec, condition=None)]]:
        for dynamic in [False, True]:
            entry = dict(effects=effects, dynamic=dynamic)
            add('zones', entry=entry, record=dict(bb_values=dict(rate=.2)))
            add('validate', entry=entry, record=dict(bb_values=dict(rate=.2)))

    root = dict(type='ignored', attributeModifier=dict(attributeModifiers=[]), damageModifier=[])
    def classify(root, **record):
        add('classify', roots={'buff': root}, record=dict(event_key='buff', **record))
    for attribute in [None, [], {}, [None], [dict(attributeType='MaxHp')], [dict(attributeType='Atk')],
                      [dict(attributeType='PhysicalDamageTakenScalar', modifyAttributeType='Specific')]]:
        for target, enemy in itertools.product(['chr_test', 'enemy', None], [None, 'enemy']):
            classify(dict(root, attributeModifier=dict(attributeModifiers=attribute)), target_character_key=target, target_enemy_key=enemy)
    for name in ['Beyond.Gameplay.Core.BuffData', 'Custom', 'Beyond.Gameplay.Core.ModifyDynamicBlackboard+Data',
                 'Beyond.Gameplay.Core.DamageScaleProcessor', 'Beyond.Gameplay.Core.DamageActionData',
                 'Beyond.Gameplay.Core.InstantModifyAttribute', 'Beyond.Gameplay.Core.CreateBuffAction+Data']:
        for field in ['node', 'globalModifier', 'healModifier', 'poiseModifier', 'shieldConfigs']:
            classify(dict(root, **{'$type': 'Beyond.Gameplay.Core.BuffData', field: {'$type': name}}), target_character_key='chr_test')
    defensive = dict(attributeModifier=dict(attributeModifiers=[dict(attributeType='FireDamageTakenScalar', modifyAttributeType='Specific')]),
                     damageModifier=[dict(enableSide='Defender', damageProcessors=[{'$type': 'X.DamageScaleProcessor', 'side': 'Defender', 'zoneName': 'ProdCalcZone'}])])
    for changes in [{}, dict(enableSide='Attacker'), dict(damageProcessors=[]), dict(damageProcessors=[None]),
                    dict(damageProcessors=[{'$type': 'DamageScaleProcessor', 'side': 'Defender', 'zoneName': 'Other'}])]:
        adjusted = dict(defensive, damageModifier=[dict(defensive['damageModifier'][0], **changes)])
        classify(adjusted, target_character_key='chr_test')
        classify(adjusted, target_character_key='enemy', target_enemy_key='enemy')
    add('classify', roots={'buff': root}, record=dict(event_key='missing', raw_event_key='buff'))
    add('classify', roots={'buff': None}, record=dict(event_key='buff'))

    zone_config = dict(NormalCalcZone={}, ProdCalcZone={})
    empty_conditions = dict(onlyExecuteWhenSourceIsMainChar=False, onlyExecuteWhenSourceIsGuard=False, actionData=[])
    processor = {'$type': 'Beyond.Gameplay.Core.DamageScaleProcessor', 'side': 'Attacker', 'zoneName': 'NormalCalcZone',
                 'addition': dict(useBlackboardKey=True, blackboardKey='rate')}
    modifier = dict(enableSide='Attacker', condition=empty_conditions, damageProcessors=[processor])
    typed_root = dict(damageModifier=[modifier], attributeModifier=dict(isConvertedAttribute=False, attributeModifiers=[]))

    def semantic_case(root, bb=None, entry=None, **extra):
        record = dict(event_key='buff', bb_values=bb or {}, **extra)
        add('semantic', roots={'buff': root}, zones=zone_config, registry=dict(verified_effects={'buff': entry} if entry is not None else {}), record=record)

    for root in [None, {}, dict(damageModifier=None), dict(damageModifier=[None]), dict(damageModifier=[{}]), typed_root]:
        semantic_case(root)
    for side, zone, key, enabled, rate in itertools.product(['Attacker', 'Defender', None], ['NormalCalcZone', 'ProdCalcZone', 'Missing'],
             ['rate', ''], [True, False, None], [.2, -1, None]):
        item = dict(processor, side=side, zoneName=zone, addition=dict(useBlackboardKey=enabled, blackboardKey=key, value=rate))
        semantic_case(dict(typed_root, damageModifier=[dict(modifier, damageProcessors=[item])]), dict(rate=rate))
    checks = [dict(isEnable=False, **{'$type': 'unknown'}), dict(isEnable=True, **{'$type': 'unknown'}),
              dict(isEnable=True, **{'$type': 'CheckDamageType', 'damageType': 'Fire'}),
              dict(isEnable=True, **{'$type': 'CheckDamageType', 'damageType': 'Physical'}),
              dict(isEnable=True, **{'$type': 'CheckHp', 'hpOwner': dict(targetSource='Target'), 'compareType': 'LE',
                   'isRatio': True, 'value': dict(useBlackboardKey=True, blackboardKey='hp')})]
    for actions, side, scope in itertools.product([[], *[[item] for item in checks], [checks[1], checks[3]], [checks[2], checks[3]]],
                                                ['Attacker', 'Defender'], [None, 'fire', 'spell', 'physical', 'all']):
        root = dict(typed_root, damageModifier=[dict(modifier, enableSide=side, condition=dict(empty_conditions, actionData=actions))])
        entry = dict(effects=[dict(zone='dmg_inc', element=scope, bb_key='rate')]) if scope else None
        semantic_case(root, dict(rate=.2, hp=.5), entry=entry,
                      rdps_unresolved_semantic_condition=['old'], rdps_unapproved_typed_branches=['old'])
        for group in [0, '0', None, False, -1, 'bad', 999999999999999999999999999999999999]:
            add('condition', roots={'buff': root}, effect=dict(groupIndex=group, enableSide=side), bb_values=dict(hp=.5))
    attribute_names = ['Atk', 'NormalAttackDamageIncrease', 'UltimateSkillDamageIncrease', 'NormalSkillDamageIncrease', 'ComboSkillDamageIncrease',
        'FireDamageIncrease', 'PhysicalDamageIncrease', 'PulseDamageIncrease', 'CrystDamageIncrease', 'NaturalDamageIncrease',
        'PulseEnhancedDmgIncrease', 'FireEnhancedDmgIncrease', 'CrystEnhancedDmgIncrease', 'NaturalEnhancedDmgIncrease',
        'PhysicalAndSpellInflictionEnhance', 'PhysicalVulnerableDmgIncrease', 'FireVulnerableDmgIncrease', 'NaturalVulnerableDmgIncrease', 'Unknown']
    for name, converted, formula, value in itertools.product(attribute_names, [True, False, None], ['BaseAddition', 'BaseMultiplier', None], [.2, -1, None]):
        attr = dict(attributeType=name, formulaItem=formula, modifyAttributeType='Specific', param=dict(useBlackboardKey=False, value=value))
        semantic_case(dict(damageModifier=[], attributeModifier=dict(isConvertedAttribute=converted, attributeModifiers=[attr])))
    instant = {'$type': 'Beyond.Gameplay.Core.InstantModifyAttribute', 'modifyTargetSide': 'Defender',
               'modifier': dict(attributeType='FireResistance', formulaItem='BaseAddition', modifyAttributeType='Specific', param=dict(useBlackboardKey=True, blackboardKey='res'))}
    for value in [None, -20, 20, False, 0]:
        semantic_case(dict(typed_root, damageModifier=[dict(modifier, damageProcessors=[instant])]), dict(res=value))
    for zone, side, processor_type in itertools.product(['NormalCalcZone', 'ProdCalcZone', 'Other', None], ['Attacker', 'Defender', None], ['DamageScaleProcessor', 'Other']):
        add('damage-zone', zones=zone_config, effect=dict(processorType=processor_type, zoneName=zone, side=side))
    binding = importlib.import_module('parser_core.catalog.resources')._NATIVE_DAMAGE_SEMANTICS_BINDING
    zone_payload = dict(schemaVersion=1, source='official_unity_typetree_damage_zone_config', decoder=binding,
                        zones=[dict(name='NormalCalcZone', isMultiplyZone=0, serverIndex=0), dict(name='ProdCalcZone', isMultiplyZone=1, serverIndex=1)])
    for payload in [None, {}, [], False, zone_payload, dict(zone_payload, schemaVersion=2), dict(zone_payload, decoder={}),
                    dict(zone_payload, zones=[]), dict(zone_payload, zones=[dict(name='bad', isMultiplyZone=True, serverIndex=0)])]:
        add('zone-config', payload=payload)

    if args.specifications:
        cases.clear()
        def specification(root=typed_root, entry=None, **record):
            add('specification', roots={'buff':root} if root is not None else {}, zones=zone_config,
                registry=dict(verified_effects={'buff':entry} if entry is not None else {}), record=dict(event_key='buff',**record))
        for value, element, dynamic in itertools.product([None,False,True,-1,0,-0.0,.2,'0.2',float('nan'),float('inf')],
                                                       ['all','fire','spell','physical'], [False,True]):
            specification(entry=dict(effects=[dict(zone='dmg_inc',element=element,bb_key='rate')],dynamic=dynamic),
                          bb_values=dict(rate=value),rdps_unresolved_semantic_condition=['old'])
        for root, entry in itertools.product([None,{},dict(damageModifier=[]),dict(typed_root,damageModifier=[]),typed_root],
                [None,{},dict(effects=[dict(zone='amp',bb_key='rate')]),dict(effects=[dict(zone='dmg_inc',bb_key='rate')])]):
            specification(root,entry,bb_values=dict(rate=.2))
            specification(root,entry,bb_values=dict(rate=.2),rdps_live_identity_conflict=True)
        for elements, restriction in itertools.product([['fire','pulse'],['all','fire'],['fire','fire'],['spell','physical'],['all','all']],
                [None,dict(type='always'),dict(type='damage_type_in',elements=['fire'])]):
            effects=[dict(zone='dmg_inc',element=element,bb_key='rate',**({'condition':restriction} if restriction is not None else {})) for element in elements]
            specification(entry=dict(effects=effects),bb_values=dict(rate=.2))
        for keys, bb in itertools.product([['rate'],['alias'],['alias','rate']],
                [dict(rate=.2),dict(alias=.2),dict(rate=.2,alias=.2),dict(rate=.2,alias=.3)]):
            specification(entry=dict(effects=[dict(zone='dmg_inc',bb_key=keys[0],bb_keys=keys)]),bb_values=bb)
        for checks, element in itertools.product([[],*[ [check] for check in checks],checks[2:4]],['all','fire','spell','physical']):
            root=dict(typed_root,damageModifier=[dict(modifier,condition=dict(empty_conditions,actionData=checks))])
            specification(root,dict(effects=[dict(zone='dmg_inc',element=element,bb_key='rate')]),bb_values=dict(rate=.2,hp=.5))
        second=dict(processor,addition=dict(useBlackboardKey=True,blackboardKey='other'))
        branches=dict(typed_root,damageModifier=[modifier,dict(modifier,damageProcessors=[second])])
        for keys in [['other','rate'],['rate','other'],['other','rate','other']]:
            specification(branches,dict(effects=[dict(zone='dmg_inc',bb_key=key) for key in keys]),bb_values=dict(rate=.2,other=.3))
        for name, formula in [('Atk','BaseMultiplier'),('NormalSkillDamageIncrease','BaseAddition'),('FireVulnerableDmgIncrease','BaseAddition')]:
            root=dict(typed_root,damageModifier=[],attributeModifier=dict(isConvertedAttribute=False,attributeModifiers=[dict(
                attributeType=name,formulaItem=formula,modifyAttributeType='Specific',param=dict(useBlackboardKey=True,blackboardKey='rate'))]))
            for zone in ['atk','dmg_inc','fragile']:
                specification(root,dict(effects=[dict(zone=zone,bb_key='rate')]),bb_values=dict(rate=.2))
            specification(root,None,bb_values=dict(rate=.2))
    if args.dynamic_specifications:
        cases.clear()
        def dynamic(spec=None, declared=None, hint=None, **record):
            spec = copy.deepcopy(spec if spec is not None else dict(zone='amp',element='all',base_bb_key='rate'))
            declared = copy.deepcopy(declared if declared is not None else [spec])
            entry = dict(dynamic=True,dynamic_effects=declared)
            add('dynamic-specification',registry=dict(verified_effects={'buff':entry}),
                record=dict(event_key='buff',packet_mapping=hint if hint is not None else dict(dynamic_effects=[spec]),
                            rdps_unresolved_dynamic_effect=True,**record))
        for zone, element, rate in itertools.product(['atk','amp','res','crit','unknown'],
                ['all','fire','spell','ether',None], [None,False,0,-0.0,.2,-.2,'0.2',float('nan'),float('inf')]):
            dynamic(dict(zone=zone,element=element,base_bb_key='rate'),bb_values=dict(rate=rate))
        base=dict(zone='res',element='fire',base_bb_key='rate',base_bb_keys=['alias','rate'])
        for left, right in itertools.product([None,False,-.2,.2,'0.2',.3],repeat=2):
            dynamic(base,bb_values=dict(rate=left,alias=right))
        for parameter,key,aliases in [('base_rate','base_bb_key','base_bb_keys'),('tick_rate','tick_bb_key','tick_bb_keys'),
                ('delayed_add_rate','add_bb_key',''),('delay_sec','delay_bb_key',''),('max_rate','max_bb_key','')]:
            for number, permission in itertools.product([None,False,0,.2,-1,'0.2',float('nan'),float('inf')],
                    [{},{'allow_static_rate':True},{'allow_static_rates':1},{'value_source':'CONSTANT'}]):
                spec=dict(zone='amp',element='all',**{parameter:number})
                dynamic(spec,hint=dict(dynamic_effects=[spec],**permission))
                dynamic(dict(zone='amp',element='all',**{key:'x'}),bb_values=dict(x=number))
            if aliases:
                for keys in [None,[],['x','x'],['x','other'],'x',0,{}]:
                    dynamic(dict(zone='amp',element='all',**{aliases:keys}),bb_values=dict(x=.2,other=.3))
        for operand in ['base_bb_key','tick_bb_key','add_bb_key','delay_bb_key','max_bb_key']:
            dynamic(dict(zone='amp',element='all',**{operand:'unknown'}),declared=[dict(zone='amp',element='all',bb_key='rate')],bb_values=dict(unknown=.2))
        for multiplier in [None,False,0,1,2,-1,'2',float('nan'),float('inf')]:
            for tick in [0,.1]: dynamic(dict(zone='amp',element='all',tick_rate=tick,tick_multiplier=multiplier),hint=dict(allow_static_rate=True))
        for own, restrictions in itertools.product([None,dict(type='always'),dict(type='damage_type_in',elements=['fire'])],
                [[],[{}],[dict(condition=dict(type='always'))],[dict(condition=dict(type='always')),{}]]):
            spec=dict(zone='amp',element='all',base_bb_key='rate')
            if own is not None: spec['condition']=own
            declared=[dict(zone='amp',element='all',base_bb_key='rate',**r) for r in restrictions]
            dynamic(spec,declared,bb_values=dict(rate=.2))
        for specs in [None,[],[None],[{}],[dict(zone='amp',element='all')]]:
            for conflict, rejected in itertools.product([False,True],repeat=2):
                add('dynamic-specification',registry=dict(verified_effects={'buff':dict(dynamic=True,dynamic_effects=specs)}),
                    record=dict(event_key='buff',rdps_live_identity_conflict=conflict,packet_mapping_rejected=rejected,
                                rdps_unresolved_dynamic_effect=True))
        # Exercise lookup through numeric, canonical and mechanism hints using the actual reference lookup.
        effect=dict(zone='amp',element='all',base_bb_key='rate')
        for identity in ['101','buff','202']:
            for mechanisms in [{},{'buff':[dict(dynamic_effects=[effect])]},{'buff':[{},{}]}]:
                add('dynamic-specification',registry=dict(verified_effects={'buff':dict(dynamic=True,dynamic_effects=[effect])}),
                    mappings={'101':dict(canonical_buff_id='buff',dynamic_effects=[effect])},numbers={'202':'buff'},
                    mechanisms=mechanisms,record=dict(event_key='buff',raw_event_key=identity,bb_values=dict(rate=.2)))
        # Resistance refresh provenance, grouping and precedence over legacy snapshots.
        for event in ['buff_common_natural_natural_corrupt_do','buff_common_natural_cryst_triggered','buff_common_natural_fire_triggered']:
            entry=dict(dynamic=True,effects=[dict(zone='res',element='all',bb_key='r')])
            for attr, formula, bound in itertools.product(['PhysicalResistance','NaturalResistance','CrystResistance','PulseResistance','FireResistance','EtherResistance','Atk'],
                    ['BaseAddition','BaseMultiplier'],[True,False,1]):
                modifier=dict(attributeType=attr,formulaItem=formula,modifyAttributeType='Specific',param=dict(useBlackboardKey=bound,blackboardKey='r'))
                add('dynamic-specification',registry=dict(verified_effects={event:entry}),roots={event:dict(attributeModifier=dict(attributeModifiers=[modifier,modifier]))},
                    record=dict(event_key=event,attribute_refresh_snapshots=[dict(timestamp_ms=1,parameters=dict(r=-20))],
                                resistance_parameter_snapshots=[dict(timestamp_ms=0,parameters=dict(r=-99))]))
        # Antal's keyword child is approved from its exact creation origin, then evaluated within one session.
        parent='buff_chr_0023_antal_tageffect'; child='buff_keyword_vulnerable'
        action={'$type':'Beyond.Gameplay.Core.VulnerableAction.Data','serverActionIndex':3,'isEnable':True,'subType':'All',
                'rate':dict(useBlackboardKey=True,blackboardKey='rate')}
        origin=dict(_boundCreateRecord=True,buffUid='7',buffTemplate=child,sourceActorId='11',targetActorId='22',
                    environmentType='Buff',ownerType='1',environmentInstId='77',templateStrId=parent,actionId=3,triggerType=0)
        keyword_root=dict(attributeModifier=dict(isConvertedAttribute=False,attributeModifiers=[dict(attributeType=name,
                         formulaItem='BaseAddition',modifyAttributeType='Specific',param=dict(useBlackboardKey=True,blackboardKey='rate'))
                         for name in ['PulseVulnerableDmgIncrease','FireVulnerableDmgIncrease']]),damageModifier=[])
        for snapshots in [[],[dict(session_id='s',rate=.2)],[dict(session_id=None,rate=.2)],
                [dict(session_id='s',rate=.2),dict(session_id='other',rate=.3)],
                [dict(session_id='s',rate=.2),dict(session_id='s',rate=.3)]]:
            add('dynamic-specification',registry=dict(verified_effects={'buff_chr_0023_antal_normal_fragile':dict(dynamic=True,
                aliases=[parent],effects=[dict(zone='fragile',element='all',bb_key='rate')])},_keyword_buff_map={'Vulnerable':{'All':child}}),
                roots={parent:dict(actions=[action]),child:keyword_root},zones=zone_config,
                record=dict(event_key=child,uid='7',source_actor_id='11',target_actor_id='22',origin_observations=[origin],
                            bb_values=dict(rate=.2),keyword_rate_snapshots=snapshots))
        for literal, declared in [(.2,.3),(.2,.2),(0,0)]:
            dynamic(dict(zone='amp',element='all',base_rate=literal),
                    declared=[dict(zone='amp',element='all',base_rate=declared)],hint=dict(allow_static_rate=True))
        for snapshots in [[dict(session_id=False,rate=.2)],[dict(session_id=0,rate=.2),dict(session_id=False,rate=.3)],
                          [dict(rate=.2)]]:
            add('dynamic-specification',registry=dict(verified_effects={'buff_chr_0023_antal_normal_fragile':dict(dynamic=True,
                aliases=[parent],effects=[dict(zone='fragile',element='all',bb_key='rate')])},_keyword_buff_map={'Vulnerable':{'All':child}}),
                roots={parent:dict(actions=[action]),child:keyword_root},zones=zone_config,
                record=dict(event_key=child,uid='7',source_actor_id='11',target_actor_id='22',origin_observations=[origin],
                            bb_values=dict(rate=.2),keyword_rate_snapshots=snapshots))
    if args.bundled:
        cases.clear()
        relative = '_internal/data/runtime-data.zip'
        archive = args.reference / relative
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Reference runtime bundle changed')
        dependencies[relative] = digest
        with zipfile.ZipFile(archive) as bundle:
            roots = json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))['entries']
            zone_payload = json.loads(bundle.read('data/local_static/damage_zone_config.json'))
        current.clear()
        # Use the reference loader so synthetic and real resources share the same validation boundary.
        with tempfile.TemporaryDirectory() as folder:
            templates._repo_root = lambda: Path(folder)
            path = Path(folder) / 'data/local_static/damage_zone_config.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(zone_payload), encoding='utf8')
            templates._load_damage_zone_config.cache_clear()
            zone_config = templates._load_damage_zone_config()
        relative = '_internal/data/packet_semantics/rdps_semantics_registry.json'
        payload = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Reference effect approvals changed')
        dependencies[relative] = digest
        registry = json.loads(payload)
        if args.dynamic_specifications:
            with zipfile.ZipFile(archive) as bundle:
                keyword = json.loads(bundle.read('data/local_static/buff/keyword_buff_map.json'))['mapping']
            dynamic_roots = {name:item['root'] for name,item in roots.items() if isinstance(item.get('root'),dict)}
            for name,entry in registry.get('verified_effects',{}).items():
                if not isinstance(entry,dict) or not entry.get('dynamic'): continue
                isolated=dict(verified_effects={name:entry},_keyword_buff_map=keyword)
                for identity in [name,*(entry.get('aliases') or []),*(str(number) for number in entry.get('numeric_ids') or [])]:
                    root=dynamic_roots.get(identity,{})
                    keys={row.get('param',{}).get('blackboardKey') for row in root.get('attributeModifier',{}).get('attributeModifiers',[])
                          if row.get('param',{}).get('useBlackboardKey') is True}
                    keys.discard(None)
                    snapshot=dict(ts_ms=1100,line_no=2,operation_seq=7,session_id='s',status='attribute_parameters_observed',
                                  bb_values={key:-20 for key in keys})
                    for snapshots in [{},dict(resistance_parameter_snapshots=[snapshot]),dict(attribute_refresh_snapshots=[snapshot]),
                            dict(attribute_refresh_snapshots=[dict(snapshot,status='unresolved')]),
                            dict(attribute_refresh_snapshots=[snapshot],resistance_parameter_snapshots=[dict(snapshot,bb_values={})])]:
                        add('dynamic-specification',registry=isolated,roots={identity:root},zones=zone_config,
                            record=dict(event_key=identity,source_character_key=entry.get('guard',{}).get('source_character_key','chr_test'),
                                        bb_values={key:-20 for key in keys},**snapshots))
            antal='buff_chr_0023_antal_normal_fragile'; parent='buff_chr_0023_antal_tageffect'
            for action_id,nodes in approval.indexed_root_actions(dynamic_roots.get(parent,{}),{})[1].items():
                for action,enabled in nodes:
                    if action.get('$type') != 'Beyond.Gameplay.Core.VulnerableAction.Data': continue
                    child=keyword.get('Vulnerable',{}).get(action.get('subType'))
                    if child not in dynamic_roots: continue
                    origin=dict(_boundCreateRecord=True,buffUid='7',buffTemplate=child,sourceActorId='11',targetActorId='22',
                                environmentType='Buff',ownerType='1',environmentInstId='77',templateStrId=parent,actionId=action_id,triggerType=0)
                    for snapshots in [[],[dict(ts_ms=1100,line_no=2,operation_seq=7,session_id='s',status='observed',rate_after=.3)],
                            [dict(session_id=None)],[dict(session_id='s'),dict(session_id='other')]]:
                        add('dynamic-specification',registry=dict(verified_effects={antal:registry['verified_effects'][antal]},_keyword_buff_map=keyword),
                            roots={parent:dynamic_roots[parent],child:dynamic_roots[child]},zones=zone_config,
                            record=dict(event_key=child,uid='7',source_character_key='chr_0023_antal',target_character_key='enemy',
                                        source_actor_id='11',target_actor_id='22',origin_observations=[origin],
                                        bb_values=dict(rate=.2),keyword_rate_snapshots=snapshots))
        for name, item in roots.items():
            if args.dynamic_specifications: break
            if not isinstance(item.get('root'), dict): continue
            if not args.specifications:
                for record in [dict(event_key=name, target_character_key='chr_test'), dict(event_key=name, target_character_key='enemy', target_enemy_key='enemy')]:
                    add('classify', roots={name: item['root']}, record=record)
            keys = set()
            pending = [item['root']]
            while pending:
                node = pending.pop()
                if isinstance(node, dict):
                    if node.get('useBlackboardKey') is True and isinstance(node.get('blackboardKey'), str): keys.add(node['blackboardKey'])
                    pending.extend(node.values())
                elif isinstance(node, list): pending.extend(node)
            entry = registry.get('verified_effects', {}).get(name)
            for bb in [{}, {key: .2 for key in keys}]:
                add('specification' if args.specifications else 'semantic', roots={name: item['root']}, zones=zone_config,
                    registry=dict(verified_effects={name: entry} if isinstance(entry, dict) else {}), record=dict(event_key=name, bb_values=bb))
        for name, entry in registry.get('verified_effects', {}).items():
            if args.specifications or args.dynamic_specifications: break
            if not isinstance(entry, dict): continue
            add('ignored', entry=entry)
            keys = rules._rdps_registry_effect_bb_keys(entry)
            records = [{}, dict(bb_values={key: .2 for key in keys}), dict(bb_values={key: -1 for key in keys}), dict(bb_values={key: .1 + i * .05 for i, key in enumerate(sorted(keys))})]
            for record in records:
                add('zones', entry=entry, record=record)
                add('validate', entry=entry, record=record)
                add('unknown', entry=entry, record=record)
            for effect in entry.get('effects') or []:
                if isinstance(effect, dict): rates(effect, records)
        if not args.specifications and not args.dynamic_specifications: add('zone-config', payload=zone_payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output_path.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Effect registry fixtures:', len(cases))


if __name__ == '__main__':
    main()
