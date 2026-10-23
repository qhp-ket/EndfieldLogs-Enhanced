"""Build the reviewed runtime projection from local raw resources.

Raw data is an input, never a runtime fallback. Selection is explicit and covers
all IDs, not just resources observed in a sample battle. Output uses the existing
data paths so the canonical parser and GUI share the same resource projection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES = {
    'data/game_resource_snapshot.json',
    'data/local_semantics/team_energy_rules.json',
    'data/local_semantics/skill_frame_rules.json',
    'data/packet_semantics/rdps_semantics_registry.json',
}
SOURCE = dict(source_release='ZMDLogs 3.0.12 (2026-10-16)',
              source_url='https://zmdlogs.com/downloads/EndfieldLogsClient_3.0.12_20261016.zip',
              source_archive_sha256='dbddebee37320fa3da91b2e1e747c30b16c66e893d9a1387d52fbbee0dc74571')
FIXED = {
    'data/akedata/buff/manifest.json', 'data/akedata/character/manifest.json',
    'data/akedata/enemy/manifest.json', 'data/akedata/dungeon/manifest.json',
    'data/local_tables/character/manifest.json', 'data/local_tables/weapon/manifest.json',
    'data/local_tables/weapon/refine_catalog.json', 'data/local_tables/equip/pieces.json',
    'data/local_tables/dungeon/manifest.json', 'data/local_tables/dungeon_catalog.json',
    'data/local_tables/NumIdStrTable.json',
    'data/local_static/buff/typed_roots.json.gz', 'data/local_static/buff/keyword_buff_map.json',
    'data/local_static/damage_zone_config.json', 'data/local_static/skill/manifest.json',
    'data/local_static/skill/damage_element_catalog.json',
    'data/local_static/skill/display_name_catalog.json',
    'data/local_static/skill/item_arts_strength_catalog.json',
    'data/local_static/skill/item_damage_baseline_catalog.json',
    'data/local_semantics/skill/details.json', 'data/local_semantics/buff/details.json',
    'data/local_semantics/classifier_hints.json',
    'data/packet_semantics/packet_resolver_bundle.json',
    'data/packet_semantics/buff_numeric_map.json', 'data/packet_semantics/skill_numeric_map.json',
    'data/packet_semantics/mechanism_registry.json',
    'data/packet_semantics/weapon_static_attack_catalog.json',
    'data/public/contract_tags.json', 'data/message_ids_cs.json', 'data/message_ids_sc.json',
    'jsondata/ActorImageTable.json', 'jsondata/CharacterNameIndex.json', 'jsondata/Dungeon.json',
} | OVERRIDES
ITEMS = (
    'data/akedata/skill/items', 'data/akedata/buff/items', 'data/akedata/character/items',
    'data/akedata/weapon/items', 'data/akedata/equip/items', 'data/akedata/attribute_type/items',
    'data/akedata/dungeon/items', 'data/local_tables/character/items',
    'data/local_tables/weapon/items', 'data/local_tables/equip/items',
    'data/local_tables/dungeon/items',
)
RELATIONS = ('createdBuffIds', 'referencedBuffIds', 'binaryCreatedBuffIds', 'binaryReferencedBuffIds')
CHARACTER_ATTRIBUTES = {0, 1, 2, 3, 39, 40, 41, 42}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def fields(value, keys):
    return {key: value[key] for key in keys if key in value}


def sparse_actions(value, match, keys):
    """Keep consumed action fields and their original traversal ordering.

    Retaining containers preserves the DFS overwrite behavior for duplicate
    serverActionIndex values. No action index is inferred from list position.
    """
    if isinstance(value, dict):
        result = {}
        selected = match(value)
        for key, child in value.items():
            if selected and key in keys:
                result[key] = child
            elif isinstance(child, (dict, list)):
                projected = sparse_actions(child, match, keys)
                if projected:
                    result[key] = projected
        return result
    if isinstance(value, list):
        return [child for item in value if (child := sparse_actions(item, match, keys))]
    return None


def project(relative, value):
    if relative.startswith('data/akedata/skill/items/'):
        def dynamic(node):
            name = str(node.get('$type') or '').replace('+', '.')
            return 'ModifyDynamicBlackboard.Data' in name or 'SimpleCalcBBAction.Data' in name
        result = sparse_actions(value, dynamic, ('$type', 'serverActionIndex', 'key'))
        result.update(fields(value, ('skillSpecification', 'castType', 'attackRangeType')))
        return result
    if relative.startswith('data/akedata/buff/items/'):
        result = sparse_actions(value, lambda n: 'EnhancedAction+Data' in str(n.get('$type') or ''),
                                ('$type', 'asChildBuff', 'childBuffId', 'subType', 'rate'))
        result.update(fields(value, ('lifeType', 'duration')))
        return result
    if relative.startswith('data/akedata/character/items/'):
        result = fields(value, ('charId', 'charType', 'profession', 'weapontype', 'potentials'))
        result['skills'] = [fields(row, ('name', 'groupType', 'skillIds', 'description'))
                            for row in value.get('skills') or []]
        return result
    if relative.startswith('data/local_tables/character/items/'):
        result = dict(value)
        result['raw'] = fields(value.get('raw') or {}, ('attributes', 'mainAttrType', 'subAttrType'))
        rows = []
        for row in result['raw'].get('attributes') or []:
            item = dict(row)
            attribute = dict(row.get('Attribute') or {})
            attrs = []
            for attr in attribute.get('attrs') or []:
                try:
                    consumed = int(attr.get('attrType')) in CHARACTER_ATTRIBUTES
                except (AttributeError, TypeError, ValueError):
                    consumed = False
                if consumed:
                    attrs.append(attr)
            attribute['attrs'] = attrs
            item['Attribute'] = attribute
            rows.append(item)
        result['raw']['attributes'] = rows
        return result
    if relative == 'data/local_tables/NumIdStrTable.json':
        return fields(value, ('buff_id', 'skill_id'))
    if relative == 'data/local_static/skill/manifest.json':
        entries = []
        for row in value.get('entries') or []:
            if not str(row.get('id') or '').startswith('sk_wpn_'):
                continue
            probe = row.get('binaryProbe') or {}
            hints = [fields(hint, ('key', 'value')) for hint in probe.get('blackboardDoubleHints') or []
                     if isinstance(hint, dict) and hint.get('key') == 'max_stack']
            if hints:
                projected = fields(probe, ('highConfidenceCreatedBuffIds', 'createdBuffIds'))
                projected['blackboardDoubleHints'] = hints
                entries.append(dict(id=row['id'], binaryProbe=projected))
        return dict(projection='weapon_buff_stack_limits', sourceResourceCount=len(value.get('entries') or []),
                    entries=entries)
    if relative in {'data/local_semantics/skill/details.json', 'data/local_semantics/buff/details.json'}:
        keys = ('id', *RELATIONS)
        if '/buff/' in relative:
            keys += ('stacking', 'actionTypes')
        entries = {}
        for key, row in value['entries'].items():
            item = fields(row, keys)
            source = row.get('source')
            if isinstance(source, dict) and source.get('decodedDetailPath'):
                item['source'] = fields(source, ('decodedDetailPath',))
            entries[key] = item
        return {'entries': entries}
    if relative == 'data/local_semantics/classifier_hints.json':
        return {'buffHints': {key: fields(row, (*RELATIONS, 'classification', 'effectHints',
                                   'resolvedEffectHints', 'resolvedEffectCount', 'semanticFlags'))
                              for key, row in value.get('buffHints', {}).items()}}
    if relative == 'data/packet_semantics/packet_resolver_bundle.json':
        return dict(runtime_projection=1, skills=value['skills'], buffs=value['buffs'],
                    known_buff_ids=[key for key, row in value.get('content', {}).get('buffs', {}).items()
                                    if isinstance(row, dict) and row])
    return value


def build(source: Path, output: Path, *, overrides: Path | None = None):
    source, output = source.resolve(), output.resolve()
    if output == source or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Output must be separate from the raw source')
    if output.exists():
        raise FileExistsError('Use a new output directory: ' + str(output))
    inventory_path = source / 'data/resource-manifest.json'
    if not inventory_path.is_file():
        raise ValueError('Prepare verified raw inputs with prepare_resources.py --raw first')
    inventory = json.loads(inventory_path.read_text(encoding='utf8'))
    if inventory.get('schema_version') != 1 or inventory.get('source_archive_sha256') != SOURCE['source_archive_sha256']:
        raise ValueError('Expected the verified raw source inventory, not an extracted runtime directory')
    source_rows = {row['path']: row for row in inventory['files']}
    paths = set(FIXED)
    for directory in ITEMS:
        folder = source / directory
        if not folder.is_dir():
            raise FileNotFoundError('Raw input directory missing: ' + directory)
        actual = {path.relative_to(source).as_posix() for path in folder.glob('*.json')}
        expected = {name for name in source_rows if PurePosixPath(name).parent.as_posix() == directory
                    and name.endswith('.json')}
        if actual != expected:
            raise ValueError('Raw item set differs from source inventory: ' + directory)
        paths.update(actual)
    output.mkdir(parents=True)
    rows = []
    raw_bytes = 0
    for relative in sorted(paths):
        src = (overrides / relative) if overrides and relative in OVERRIDES else source / relative
        content = src.read_bytes()
        if relative not in OVERRIDES:
            row = source_rows.get(relative)
            if not row or len(content) != row['bytes'] or sha(content) != row['sha256']:
                raise ValueError('Raw input differs from source inventory: ' + relative)
        raw_bytes += len(content)
        # Weapon-definition bytes are hashed by the canonical parser as evidence.
        # Developer rules remain directly editable and retain their own hashes.
        if relative not in OVERRIDES and not relative.endswith('.gz') and not relative.startswith('data/local_tables/weapon/items/'):
            projected = project(relative, json.loads(content.decode('utf-8-sig')))
            if relative == 'data/local_static/skill/manifest.json':
                projected['sourceManifestSha256'] = sha(content)
            content = json.dumps(projected,
                                 ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
        dst = output / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        rows.append(dict(path=relative, bytes=len(content), sha256=sha(content),
                         origin='development_override' if relative in OVERRIDES else 'runtime_projection'))
    bundle_path = output / 'data/runtime-data.zip'
    with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for row in rows:
            if row['path'] in OVERRIDES:
                continue
            info = zipfile.ZipInfo(row['path'], (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (output / row['path']).read_bytes(), compresslevel=9)
    manifest = dict(schema_version=2, root='_internal', projection_version=2, **SOURCE,
                    bundle=dict(path='data/runtime-data.zip', bytes=bundle_path.stat().st_size,
                                sha256=sha(bundle_path.read_bytes())), files=rows)
    (output / 'data/resource-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf8', newline='\n')
    print(json.dumps(dict(files=len(rows), selected_source_bytes=raw_bytes,
                          runtime_bytes=sum(row['bytes'] for row in rows), bundle_bytes=bundle_path.stat().st_size), indent=2))
    return manifest


def archive_raw(source: Path, destination: Path, manifest):
    """Copy the exact former runtime inputs to a local, ignored source archive."""
    for row in manifest['files']:
        relative = row['path']
        src = (source / relative).resolve()
        target = (destination / relative).resolve()
        parts = PurePosixPath(relative)
        if (parts.is_absolute() or '..' in parts.parts or '\\' in relative
                or not src.is_relative_to(source.resolve()) or not target.is_relative_to(destination.resolve())):
            raise ValueError('Unsafe raw inventory path')
        content = src.read_bytes()
        if len(content) != row['bytes'] or sha(content) != row['sha256']:
            raise ValueError('Raw resource changed: ' + relative)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError('Different archived raw input: ' + relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    target = destination / 'data/resource-manifest.json'
    if not target.exists():
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf8', newline='\n')


def activate(root: Path, projection: Path):
    """Preserve old inputs locally before activating a verified projection."""
    internal = (root / '_internal').resolve()
    old = json.loads((internal / 'data/resource-manifest.json').read_text(encoding='utf8'))
    manifest = json.loads((projection / 'data/resource-manifest.json').read_text(encoding='utf8'))
    if manifest.get('schema_version') != 2:
        raise ValueError('Expected a generated runtime projection')
    new_paths = {row['path'] for row in manifest['files']}
    for row in manifest['files']:
        path = (projection / row['path']).resolve()
        if not path.is_relative_to(projection.resolve()):
            raise ValueError('Unsafe generated member')
        content = path.read_bytes()
        if len(content) != row['bytes'] or sha(content) != row['sha256']:
            raise ValueError('Changed generated member: ' + row['path'])
    bundle = projection / manifest['bundle']['path']
    if sha(bundle.read_bytes()) != manifest['bundle']['sha256']:
        raise ValueError('Changed runtime bundle')
    if old.get('schema_version') == 1:
        archive_raw(internal, root / '_development/raw-resources/_internal', old)
    for row in manifest['files']:
        target = (internal / row['path']).resolve()
        if not target.is_relative_to(internal / 'data') and not target.is_relative_to(internal / 'jsondata'):
            raise ValueError('Unsafe runtime member')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or sha(target.read_bytes()) != row['sha256']:
            pending = target.with_name(target.name + '.pending')
            shutil.copy2(projection / row['path'], pending)
            pending.replace(target)
    # Every removed file has already been preserved and verified by archive_raw.
    for row in old['files']:
        if row['path'] in new_paths:
            continue
        target = (internal / row['path']).resolve()
        if not target.is_relative_to(internal / 'data') and not target.is_relative_to(internal / 'jsondata'):
            raise ValueError('Unsafe obsolete runtime member')
        target.unlink(missing_ok=True)
    shutil.copy2(bundle, internal / 'data/runtime-data.zip')
    shutil.copy2(projection / 'data/resource-manifest.json', internal / 'data/resource-manifest.json')
    print('Activated runtime projection; raw inputs remain under _development/raw-resources/.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Local raw _internal directory')
    parser.add_argument('--output', type=Path, required=True, help='New projected _internal directory')
    parser.add_argument('--install', action='store_true', help='Activate after preserving previous raw inputs locally')
    args = parser.parse_args()
    build(args.source, args.output, overrides=ROOT / '_internal')
    if args.install:
        activate(ROOT, args.output)


if __name__ == '__main__':
    main()
