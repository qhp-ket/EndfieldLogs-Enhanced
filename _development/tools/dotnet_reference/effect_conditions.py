"""Verify observed guards and typed condition decoding against the fixed source."""
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
from types import ModuleType
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires a local output path')
    target = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/effect-conditions.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed effect condition reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    conditions = importlib.import_module('parser_core.effects.conditions')
    current = {}
    conditions._load_current_buff_roots = lambda: current

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        return value

    cases = []

    def add(kind, effect=None, hit=None, root=None, name=None):
        effect = {} if effect is None else copy.deepcopy(effect)
        hit = {} if hit is None else copy.deepcopy(hit)
        current.clear()
        current['buff_test'] = root
        conditions._decoded_damage_modifier_condition_rows.cache_clear()
        before = encode([effect, hit, root])
        try:
            if kind == 'failure': result = conditions._effect_condition_failure(effect, hit)
            elif kind == 'elements': result = sorted(conditions._effect_damage_type_condition_elements(effect))
            elif kind == 'applies': result = conditions._effect_element_applies_to_hit(effect, effect.get('damage_element'), effect.get('damage_school'))
            elif kind == 'filter': result = conditions._element_filter_debug_fields(effect.get('element'), effect.get('damage_element'), effect.get('damage_school'))
            elif kind == 'normalize': result = conditions._normalize_condition_damage_type(effect.get('value'))
            elif kind == 'attach':
                result = copy.deepcopy(effect)
                conditions._attach_bb_key_damage_type_condition(result, effect.get('bb_key'))
            elif kind == 'decode': result = conditions._decoded_damage_modifier_condition_rows('buff_test')
            else: raise ValueError(kind)
        except TypeError:
            result = {'error': 'TypeError'}
        if encode([effect, hit, root]) != before:
            raise AssertionError('Reference changed inputs: ' + str(len(cases)))
        cases.append(dict(name=name or f'{kind}/{len(cases)}', kind=kind,
            effect_json=json.dumps(effect, ensure_ascii=True), hit_json=json.dumps(hit, ensure_ascii=True),
            root_json=json.dumps(root, ensure_ascii=True), expected=encode(result)))

    def failure(condition, hit=None):
        add('failure', dict(condition=condition), hit)

    add('failure')
    for value in (None, False, 0, [], 'always', {}, dict(type='always'), dict(type='unknown')):
        failure(value)
    masks = [None, False, True, -1, 0, 1, 4, 5, 0x22784, 0x4001C000, 0x0FD00038, 2**63, 2**64-1, 2**64, 1.0, '4']
    for required, check, actual in itertools.product(masks, ['HasAll', 'HasAny', '', None], masks):
        failure(dict(type='damage_decorate_mask', source='typed', mask=required, check=check), dict(damage_decorate_mask=actual))
    for required, static, source in itertools.product([0, 4, 0x100, 0x4000, 0x2000000, 0x10000000, 2**63], masks,
            [None, 'guessed', 'current_typed_skill_or_buff_exact_unit_generation_only']):
        for check in ('HasAll', 'HasAny'):
            failure(dict(type='damage_decorate_mask', mask=required, check=check),
                dict(static_damage_decorate_mask=static, static_damage_decorate_mask_source=source))
    hp = dict(enemy_hp_before=50, target_enemy_max_hp=100, attacker_hp_before=30, attacker_max_hp=60)
    for compare, ratio, side, threshold in itertools.product(['LT', 'LE', 'GT', 'GE', 'EQ', 'NE'], [False, True],
            ['attacker', 'defender'], [0, .5, 1, 30, 50, 100]):
        failure(dict(type='target_hp_compare', compare=compare, is_ratio=ratio, threshold=threshold, subject_side=side), hp)
    for field, values in dict(compare=[None, 'eq', 1], is_ratio=[None, 1, 'true'], threshold=[None, -1, True, '0.5', 'NaN', float('inf'), 10**400],
            subject_side=[None, '', 'target']).items():
        for value in values:
            failure(dict(dict(type='target_hp_compare', compare='LE', is_ratio=True, threshold=.5), **{field:value}), hp)
    for field, values in dict(enemy_hp_before=[None, -1, 0, 101, '50', False, float('nan')],
            target_enemy_max_hp=[None, -1, 0, 49, '100', True, float('inf')]).items():
        for value in values:
            for ratio in (True, False):
                failure(dict(type='target_hp_compare', compare='LE', is_ratio=ratio, threshold=.5), dict(hp, **{field:value}))
                failure(dict(type='target_hp_ratio_lte', threshold=.5), dict(hp, **{field:value}))
    for ids, active, complete, side in itertools.product([None, [], [''], [1], ['a'], ['a', 'a'], ['a', 'b']],
            [None, [], ['a'], ['b'], ['c'], ['a', 'b']], [None, False, True, 1], ['attacker', 'defender']):
        hit = {('_active_attacker_buff_ids' if side == 'attacker' else '_active_target_buff_ids'):active,
            ('attacker_buff_state_complete' if side == 'attacker' else 'target_buff_state_complete'):complete}
        failure(dict(type='target_has_buff', buff_ids=ids, subject_side=side), hit)
    failure(dict(type='target_has_buff', buff_ids=['a'], subject_side='enemy'))
    for elements, actual in itertools.product([None, [], ['physical'], ['fire', 'pulse'], ['real'], ['ether'], ['cryst', 'natural'], [False], ['Fire']],
            [None, 'physical', 'fire', 'pulse', 'cryst', 'natural', 'real', 'ether', 1]):
        failure(dict(type='damage_type_in', elements=elements), dict(damage_element=actual))
    children = [dict(type='always'), dict(type='damage_type_in', elements=['physical']),
        dict(type='damage_decorate_mask', mask=4, check='HasAll'), dict(type='unknown')]
    for kind in ('all', 'any'):
        for child_list in [None, [], [None], *[list(values) for values in itertools.product(children, repeat=2)]]:
            for hit in ({}, dict(damage_element='fire', damage_decorate_mask=4), dict(damage_element='physical')):
                failure(dict(type=kind, conditions=child_list), hit)
        failure(dict(type=kind, conditions=[dict(type=kind, conditions=children[:2]), children[2]]), {})
    element_conditions = [None, {}, dict(type='damage_type_in', elements=['physical']),
        dict(type='damage_type_in', elements=['fire', 'pulse']), dict(type='damage_type_in', elements='fire'),
        dict(type='damage_type_in', elements=[0, None, False, 'fire', 1]),
        dict(type='all', conditions=[dict(type='damage_type_in', elements=['physical']), None]),
        dict(type='any', conditions=[dict(type='damage_type_in', elements=['physical'])])]
    for condition in element_conditions:
        add('elements', dict(condition=condition))
    for element, actual, school, condition in itertools.product([None, '', 'all', 'physical', 'spell', 'fire', 'real', 'unknown'],
            [None, 'physical', 'fire', 'ether'], [None, '', 'physical', 'spell'], element_conditions):
        effect = dict(element=element, damage_element=actual, damage_school=school, condition=condition)
        add('applies', effect)
    for element in (None, '', 'all', 'physical', 'spell', 'fire', 'unknown'):
        add('filter', dict(element=element, damage_element='fire', damage_school='spell'))
    for condition, key in itertools.product([None, {}, False, [], dict(type='always')],
            [None, '', 'PHYSICAL_RES_DOWN', 'physical_vulnerable_dmg_increase', 'phy_resist_down', ' physical_res_down', 'fire']):
        add('attach', dict(condition=condition, bb_key=key, name='effect'))
    for value in [None, False, 1, [], {}, 'physic', 'PHYSICAL', ' fire ', '\u001cCrystal\u001f', 'Cryst', 'natural', 'ether', 'real']:
        add('normalize', dict(value=value))

    selector = dict(targetSource='Target', selectorData={})
    hp_action = dict(isEnable=True, **{'$type':'CheckHp'}, hpOwner=selector, compare='LE', isRatio=True,
        value=dict(useBlackboardKey=False, value=.5))
    buff_action = dict(isEnable=True, **{'$type':'CheckBuffStackNumAdvanced'}, checkTarget=selector,
        buffSettings=dict(buffIdList=['b','a','a'], checkType='Id'), buffStackNumType='BuffCount', compareType='GE',
        limitSkillCastId=False, value=dict(useBlackboardKey=False, value=1))
    actions = [hp_action, buff_action, dict(isEnable=True, **{'$type':'CheckDamageType'}, damageType='Fire'),
        dict(isEnable=True, **{'$type':'CheckDamageTypeMask'}, damageTypeMask=5),
        dict(isEnable=True, **{'$type':'CheckDamageDecorateMask'}, mask=4, checkType='HasAny')]

    def decode(items, **changes):
        container = dict(onlyExecuteWhenSourceIsMainChar=False, onlyExecuteWhenSourceIsGuard=False, actionData=items)
        container.update(changes)
        add('decode', root=dict(damageModifier=[dict(condition=container)]))

    for root in [None, {}, [], dict(damageModifier=None), dict(damageModifier=[None, {}, dict(condition=None), dict(condition=dict(actionData=None))])]:
        add('decode', root=root)
    for guard in (None, False, True, 0, ''):
        decode(actions, onlyExecuteWhenSourceIsGuard=guard)
    for action in actions:
        decode([action])
        for enabled in (False, None, 0, 'true'):
            decode([dict(action, isEnable=enabled)])
        short = action['$type']
        prefix = 'Beyond.Gameplay.Core.' + ('Conditions.' if short != 'CheckBuffStackNumAdvanced' else '')
        for symbol in [prefix+short+'.Data', prefix+short+'+Data, Assembly', prefix+short+'.Data ', 'Unknown', None]:
            decode([dict(action, **{'$type':symbol})])
    decode([])
    decode([dict(buff_action, buffSettings=dict(buffIdList=['\ue000', '😀', 'a', '😀'], checkType='Id'))])
    decode([None, {}, dict(isEnable=False), *actions])
    decode([dict(action, isEnable=False) for action in actions])
    for action in (hp_action, buff_action):
        field = 'hpOwner' if action is hp_action else 'checkTarget'
        for selected in [None, {}, dict(targetSource='Source'), dict(selector, selectorData='bad'),
                dict(selector, targetGroupKey='group'), dict(selector, ownerContextKey='owner'),
                dict(selector, targetContextKey='context'), dict(selector, selectorData=dict(validatorData=[1])),
                dict(selector, selectorData=dict(postProcessorData=[1])), dict(selector, selectorData=[]), dict(selector, selectorData=None)]:
            decode([dict(action, **{field:selected})])
    for field, values in dict(compare=[None, 'eq', 'GT'], isRatio=[None, 1, False],
            value=[None, {}, dict(useBlackboardKey=None), dict(useBlackboardKey=True), dict(useBlackboardKey=True, blackboardKey='hp')]).items():
        for value in values: decode([dict(hp_action, **{field:value})])
    for field, values in dict(buffSettings=[None, {}, dict(buffIdList=[], checkType='Id'), dict(buffIdList=['a'],checkType='Any'), dict(buffIdList=[1],checkType='Id')],
            buffStackNumType=[None, 'StackNum'], compareType=['LE', None], limitSkillCastId=[None, 0, True],
            value=[None, {}, dict(useBlackboardKey=True,value=1), dict(useBlackboardKey=False,value='1'), dict(useBlackboardKey=False,value=2)]).items():
        for value in values: decode([dict(buff_action, **{field:value})])
    for mask in [None, False, True, -1, 0, *range(1,257), 2**64, 1.0, 'Physical','Real','Fire','Pulse','Cryst','LifeDrain','Natural','Ether','physical']:
        decode([dict(actions[3], damageTypeMask=mask)])
    for mask, check in itertools.product(masks + [2**80], ['HasAll','HasAny','HasNone',None]):
        decode([dict(actions[4], mask=mask, checkType=check)])
    add('elements', dict(condition=dict(type='damage_type_in', elements=['\ue000', '😀', 'a', '😀'])))

    if args.bundled:
        cases.clear()
        relative = '_internal/data/runtime-data.zip'
        archive = args.reference / relative
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Reference runtime bundle changed')
        dependencies[relative] = digest
        with zipfile.ZipFile(archive) as bundle:
            payload = json.loads(gzip.decompress(bundle.read('data/local_static/buff/typed_roots.json.gz')))
        for name, entry in payload['entries'].items():
            root = entry.get('root')
            if isinstance(root, dict) and root.get('damageModifier'):
                add('decode', root=root, name='bundled/' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    target.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Effect condition fixtures:', len(cases))


if __name__ == '__main__':
    main()
