"""Freeze static source applicability and exact category evidence from the fixed Python tree."""
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/static-applicability.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed applicability reference changed: ' + relative)
            dependencies[relative] = digest
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    static = importlib.import_module('parser_core.allocation.static_loadout')
    categories = importlib.import_module('parser_core.effects.damage_types')
    cases = []
    source = 'current_typed_skill_or_buff_exact_unit_generation_only'

    def add(label, entry=None, hit=None, numeric_baseline=None, attribute=None):
        config = copy.deepcopy(dict(entry=entry or {}, hit=hit or {}, numeric_baseline=numeric_baseline or {}))
        if attribute is not None:
            config['attribute'] = copy.deepcopy(attribute)
        owned = copy.deepcopy(config['hit'])
        baseline = owned.setdefault('baseline', {})
        baseline.update({int(key): value for key, value in config['numeric_baseline'].items()})
        try:
            if attribute is not None:
                result = dict(applies=categories._attr_type_applies_to_skill(config['attribute'].get('attr_type'), None,
                    damage_decorate_mask=owned.get('damage_decorate_mask'),
                    static_damage_decorate_mask=owned.get('static_damage_decorate_mask'),
                    static_damage_decorate_mask_source=owned.get('static_damage_decorate_mask_source')))
            else:
                applies = static._static_entry_applies_to_hit(config['entry'], owned)
                result = dict(applies=applies, quality_present='rdps_unresolved_effect_conditions' in owned,
                    quality=owned.get('rdps_unresolved_effect_conditions'))
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            result = dict(error=type(exc).__name__)
        cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

    default = dict(zone='dmg_inc', rate=.2, attr_type=32, element='all', evidence_kind='official_EquipTable_attribute')
    for attr, runtime in itertools.product([None, 2, 17, 28, 32, 33, 50, '32', 32., True, [], {}],
            [None, 0, 4, 0x100, 0x200, 0x2000, 1 << 63, -1, 1 << 64, True, 256., '256']):
        hit = dict(damage_decorate_mask=runtime)
        add('attribute-runtime', hit=hit, attribute=dict(attr_type=attr))
        add('entry-runtime', dict(default, attr_type=attr), hit)
    for attr, mask, provenance in itertools.product([17, 28, 32, 33, 50], [None, 0, 4, 256, 512, 8192, True, 256., -1, 1 << 64],
            [None, source, 'different-source']):
        hit = dict(static_damage_decorate_mask=mask, static_damage_decorate_mask_source=provenance)
        add('attribute-template', hit=hit, attribute=dict(attr_type=attr))
        add('entry-template', dict(default, attr_type=attr), hit)
    for zone in ['atk', 'dmg_inc', 'amp', 'fragile', 'vuln_taken', 'res', 'combo', 'arts_strength', 'prod_dmg_inc', 'prod_vuln_taken', 'crit', 'unknown', None]:
        for rate in [None, -1, 0, .2, '0.2', True, float('inf'), float('nan')]:
            add('zone-rate', dict(default, zone=zone, rate=rate), dict(damage_decorate_mask=256))
    for kind, attr, value in itertools.product(['official_EquipTable_attribute', 'official_WeaponSkill_text_basic',
            'current_official_item_skill_card_attribute', 'official_WeaponSkill_text_basic_atk', 'other'],
            [2, 32, 50, '32', 32.], [None, 0, .2, '0.2', 'invalid', True, float('inf')]):
        add('text-baseline', dict(default, evidence_kind=kind, attr_type=attr),
            dict(damage_decorate_mask=256, baseline={str(attr): value}))
    for numeric, text in itertools.product([None, 0, .1, 'bad', True], [None, 0, .2, 'bad']):
        add('numeric-key-precedence', default, dict(damage_decorate_mask=256, baseline={'32': text}), {'32': numeric})
    for attr in [2, 32, 32., '32', None, False]:
        add('integer-key-identity', dict(default, attr_type=attr), dict(damage_decorate_mask=256), {'32': 0})
    for element, damage, school in itertools.product([None, 'all', 'physical', 'spell', 'fire', 'ether', 'unknown'],
            [None, 'physical', 'fire', 'ether', 'unknown'], [None, 'physical', 'spell', '', False]):
        add('element-school', dict(zone='dmg_inc', rate=.2, element=element), dict(damage_element=damage, damage_school=school))
    for groups, runtime in itertools.product([[], ['normal'], ['skill'], ['combo'], ['ultimate'], ['normal', 'skill'],
            ['skill', 'skill'], ['skill', 'unknown'], [None, '', False], ['unknown']], [None, 0, 4, 256, 512, 8192, True, '256']):
        add('groups-runtime', dict(zone='dmg_inc', rate=.2, skill_groups=groups), dict(damage_decorate_mask=runtime))
    for groups, mask, provenance in itertools.product([['normal'], ['skill'], ['normal', 'skill']], [0, 4, 256, 8192], [source, 'other']):
        add('groups-template', dict(zone='dmg_inc', rate=.2, skill_groups=groups),
            dict(static_damage_decorate_mask=mask, static_damage_decorate_mask_source=provenance))
    for value in [False, True, 'existing', 0]:
        add('preserve-quality', dict(default), dict(damage_decorate_mask=256, rdps_unresolved_effect_conditions=value))
        add('mark-quality', dict(default), dict(rdps_unresolved_effect_conditions=value))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Static applicability fixtures:', len(cases))


if __name__ == '__main__':
    main()
