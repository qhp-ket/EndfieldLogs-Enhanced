"""Compare exact static arts sources with immutable Python resource/provenance rules."""
import argparse
import copy
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
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires an explicit local output')
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/static-arts-strength.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}

    def pinned(relative):
        data = (args.reference / relative).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != metadata['files'][relative]['sha256']:
            raise ValueError('Fixed arts reference changed: ' + relative)
        dependencies[relative] = digest
        return data

    prefix = '_internal/packages/parser_core/parser_core/'
    for relative in metadata['files']:
        if relative.startswith(prefix) and relative.endswith('.py'):
            pinned(relative)
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference / prefix)]
    sys.modules['parser_core'] = package
    static = importlib.import_module('parser_core.allocation.static_loadout')
    resources = importlib.import_module('parser_core.catalog.resources')
    original_weapons = static._load_weapon_catalog
    binding = copy.deepcopy(resources._NATIVE_DAMAGE_SEMANTICS_BINDING)
    proof = 'a' * 64
    definition = dict(skillId='sk_wpn_a', numericSkillId='101', weaponBindings=[dict(weaponId='wpn_a', skillSlot=0)],
        suitId='suit_a', attributeIndex=0, bbKey='arts', sourceBytes=100, consumedBytes=100, sourceSha256=proof,
        modifier={'$type': 'Beyond.Gameplay.AttributeModifierData.AttributeModifier',
            'attributeType': 'PhysicalAndSpellInflictionEnhance', 'formulaItem': 'BaseAddition', 'modifyAttributeType': 'Specific',
            'param': dict(useBlackboardKey=True, blackboardKey='arts')})
    catalog = dict(schemaVersion=1, source='current_official_item_skill_card_attribute', decoder=binding,
        weaponEntries=[copy.deepcopy(definition)], suitEntries=[copy.deepcopy(definition)])
    numbers = {'101': 'sk_wpn_a', '102': 'sk_wpn_other'}
    weapons = dict(wpn_a=dict(weapon_skill_ids=['sk_wpn_a']))
    shared = dict(catalog=catalog, numbers=numbers, weapons=weapons)
    cases = []
    with tempfile.TemporaryDirectory(prefix='endfield-static-arts-reference-') as directory:
        root = Path(directory)
        path = root / 'data/local_static/skill/item_arts_strength_catalog.json'
        path.parent.mkdir(parents=True)
        static._repo_root = lambda: root
        resources._repo_root = lambda: root
        current = {}
        static._load_weapon_catalog = lambda: current['weapons']
        static._load_num_id_str_skill_map = lambda: current['numbers']

        def add(label, row=None, **changes):
            config = dict(row=copy.deepcopy(row or {}))
            config.update(copy.deepcopy(changes))
            current.clear()
            current.update(shared)
            current.update(changes)
            path.write_text(json.dumps(current['catalog']), encoding='utf8')
            owned = copy.deepcopy(config['row'])
            try:
                entries = static._derive_static_arts_strength_entries(owned)
                result = dict(row=owned, entries=entries)
            except (TypeError, ValueError, OverflowError, AttributeError, KeyError) as exc:
                result = dict(error=type(exc).__name__)
            cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(config, ensure_ascii=True), expected=canonical(result)))

        def equipment(**changes):
            result = dict(source_type='equip_baseline', source_id='equip_a', source_slot=0, attr_index=0, enhance_level=0,
                attr_type=87, value=20, evidence_kind='official_EquipTable_attribute_zero_or_exact', source_table_sha256=proof)
            result.update(changes)
            return result

        def weapon(rate=20, **changes):
            result = dict(weapon_template='wpn_a', weapon_source_skills=[dict(skill_id=101, bb=dict(arts=rate))])
            result.update(changes)
            return result

        def suit(rate=20, **changes):
            effect = dict(suit_id='suit_a', suit_name='suit name', active=True, value=dict(arts=rate))
            effect.update(changes)
            return dict(suit_effects=[effect])

        add('empty')
        for field, values in dict(source_type=['equip', None], attr_type=[True, '87', 86, 87., 87],
                source_id=['', None, 1, 'equip_a'], source_slot=[None, True, -1, 0, 1, '0'], attr_index=[None, True, -1, 0, '0'],
                enhance_level=[None, True, -1, 0, 1, '0'], source_table_sha256=[None, '', 'A' * 64, 'a' * 63, 'a' * 64],
                evidence_kind=[None, 'number_match', 'official_EquipTable_attribute_zero_or_exact']).items():
            for value in values:
                add('equipment-' + field, dict(equipment_baseline_attributes=[equipment(**{field: value})]))
        for value in [None, True, False, -1, 0, -0., 1, 20.5, '20.5', 'nan', float('inf'), 'bad']:
            add('equipment-value', dict(equipment_baseline_attributes=[equipment(value=value)]))
            add('weapon-value', weapon(value))
            add('suit-value', suit(value))
        for value, other, hash_value in itertools.product([0, 20, 20.5], [0, 20, 20.5], [proof, 'b' * 64]):
            add('equipment-conflict', dict(equipment_baseline_attributes=[equipment(value=value), equipment(value=other, source_table_sha256=hash_value)]))
        for field, values in dict(attributeIndex=[None, True, -1, 0, '0'], sourceBytes=[None, True, 0, 100],
                consumedBytes=[None, 99, 100, 100.], sourceSha256=[None, '', 'A' * 64, proof],
                bbKey=['', 'missing', None], numericSkillId=[101, '101', 102, None], skillId=['sk_wpn_other', None]).items():
            for value in values:
                changed = copy.deepcopy(definition)
                changed[field] = value
                source = dict(catalog, weaponEntries=[changed], suitEntries=[changed])
                add('definition-' + field, dict(**weapon(), **suit()), catalog=source)
        for field, values in {'$type': ['other', None], 'attributeType': ['Attack', None], 'formulaItem': ['BaseMultiplier', None],
                'modifyAttributeType': ['All', None], 'param': [None, {}, dict(useBlackboardKey=False, blackboardKey='arts'),
                    dict(useBlackboardKey=1, blackboardKey='arts'), dict(useBlackboardKey=True, blackboardKey='other')]}.items():
            for value in values:
                changed = copy.deepcopy(definition)
                changed['modifier'][field] = value
                add('modifier-' + field, weapon(), catalog=dict(catalog, weaponEntries=[changed], suitEntries=[]))
        for bindings in [[], [None], [dict(weaponId='wpn_a', skillSlot=0)] * 2,
                [dict(weaponId='wpn_a', skillSlot=True)], [dict(weaponId='wpn_a', skillSlot=-1)],
                [dict(weaponId='wpn_other', skillSlot=0)], [dict(weaponId='wpn_a', skillSlot=1)]]:
            add('weapon-binding', weapon(), catalog=dict(catalog, weaponEntries=[dict(definition, weaponBindings=bindings)], suitEntries=[]))
        for source, template, skill in itertools.product(['weapon_source_skills', 'weapon_refine_stats'], ['wpn_a', 'wpn_missing'],
                [101, '101', 'sk_wpn_a', 'skill_101', 102, None]):
            add('weapon-identity', { 'weapon_template': template, source: [dict(skill_id=skill, bb=dict(arts=20))] })
        for active, value in itertools.product([None, False, True, 1], [None, {}, dict(arts=20)]):
            add('suit-binding', suit(active=active, value=value))
        for version, decoder in itertools.product([None, 0, 1, True, '1', 2], [None, {}, binding, dict(binding, extra='retained'), dict(binding, metadataSha256='b' * 64)]):
            add('catalog-provenance', dict(**weapon(), **suit()), catalog=dict(catalog, schemaVersion=version, decoder=decoder))
        for value, name in itertools.product([0, 20, 21], ['suit name', 'different name']):
            add('suit-duplicate', dict(suit_effects=[suit()['suit_effects'][0], suit(value, suit_name=name)['suit_effects'][0]],
                rdps_unresolved_static_multiplier_sources=[dict(reason='existing')]))
        add('independent-equipment-slots', dict(equipment_baseline_attributes=[equipment(), equipment(source_slot=1)]))
        add('all-sources', dict(**weapon(), **suit(), equipment_baseline_attributes=[equipment()]))
        add('weapon-observations-conflict', weapon(weapon_source_skills=[dict(skill_id=101, bb=dict(arts=20)), dict(skill_id='sk_wpn_a', bb=dict(arts=21))]))
        add('definition-provenance-conflict', weapon(), catalog=dict(catalog, weaponEntries=[definition, dict(definition, sourceSha256='b' * 64)]))
        if args.bundled:
            archive = '_internal/data/runtime-data.zip'
            pinned(archive)
            with zipfile.ZipFile(args.reference / archive) as bundle:
                for info in bundle.infolist():
                    if not info.is_dir():
                        target = (root / info.filename).resolve()
                        if not target.is_relative_to(root):
                            raise ValueError('Runtime archive path outside temporary root')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(bundle.read(info))
            resources._load_weapon_catalog.cache_clear()
            actual_weapons = original_weapons()
            actual_catalog = json.loads(path.read_text(encoding='utf8'))
            table = json.loads((root / 'data/local_tables/NumIdStrTable.json').read_text(encoding='utf8'))
            for kind in ['weapon', 'suit']:
                for definition_row in actual_catalog.get(kind + 'Entries') or []:
                    key = definition_row['bbKey']
                    sources = definition_row.get('weaponBindings') or [dict(suitId=definition_row.get('suitId'))]
                    for source in sources:
                        for rate in [0, 10, 20.5]:
                            if kind == 'weapon':
                                item_id = source['weaponId']
                                row = dict(weapon_template=item_id, weapon_source_skills=[dict(skill_id=definition_row['numericSkillId'], bb={key: rate})])
                            else:
                                row = dict(suit_effects=[dict(suit_id=source['suitId'], active=True, value={key: rate})])
                            add('bundled-card', row, catalog=actual_catalog, weapons=actual_weapons, numbers=table['skill_id']['dic'])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(dict(resources_json=json.dumps(shared, ensure_ascii=True), cases=cases), ensure_ascii=True, separators=(',', ':')), encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
        print('Static arts fixtures:', len(cases))


if __name__ == '__main__':
    main()
