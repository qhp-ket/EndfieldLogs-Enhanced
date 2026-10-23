"""Runtime data must be self-contained, projected and independent of raw inputs."""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from test_repository_inputs import tool, ROOT


def test_sparse_skill_projection_preserves_dynamic_action_order_and_header():
    extractor = tool('extract_runtime_data')
    raw = dict(skillSpecification='NormalSkill', castType='Immediately', attackRangeType='Ranged',
               unused_animation={'curve': list(range(100))},
               actions=[{'$type': 'ModifyDynamicBlackboard+Data', 'serverActionIndex': 4,
                         'key': 'first', 'unused': 'large'},
                        {'$type': 'SimpleCalcBBAction.Data', 'serverActionIndex': 4, 'key': 'last'},
                        {'$type': 'OnlyAnimation', 'unused': 'large'}])
    projected = extractor.project('data/akedata/skill/items/example.json', raw)
    assert 'unused_animation' not in projected
    assert [item['key'] for item in projected['actions']] == ['first', 'last']
    from parser_core import battle_log_parser as parser
    def indices(value):
        result, pending = {}, [value]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                name = str(node.get('$type') or '').replace('+', '.')
                if 'ModifyDynamicBlackboard.Data' in name or 'SimpleCalcBBAction.Data' in name:
                    index = parser._coerce_optional_int(node.get('serverActionIndex'))
                    if index is not None and node.get('key'):
                        result[index] = node['key']
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        return result
    assert indices(projected) == indices(raw) == {4: 'first'}


def test_buff_projection_keeps_duration_and_enhanced_child_effect_evidence():
    extractor = tool('extract_runtime_data')
    raw = dict(lifeType='Limited', duration={'useBlackboardKey': True, 'blackboardKey': 'duration'},
               actions=[{'$type': 'EnhancedAction+Data', 'asChildBuff': True,
                         'childBuffId': {'value': 'child'}, 'subType': 'Fire',
                         'rate': {'blackboardKey': 'rate'}, 'irrelevant': 'large'}],
               unused_visual='large')
    projected = extractor.project('data/akedata/buff/items/example.json', raw)
    assert 'unused_visual' not in projected
    assert 'irrelevant' not in projected['actions'][0]
    from parser_core.battle_log_parser import _walk_enhanced_action_child_specs as walk
    expected = [{'zone': 'amp', 'element': 'fire', 'bb_key': 'rate', 'prefer_runtime_rate_key': 'rate'}]
    assert walk(projected, target_child_buff_id='child') == walk(raw, target_child_buff_id='child') == expected
    assert projected['duration'] == raw['duration']


def test_character_projection_keeps_all_levels_and_consumed_attributes_in_order():
    extractor = tool('extract_runtime_data')
    attrs = [{'attrType': key, 'attrValue': key + 0.125} for key in (0, 39, 40, 41, 42, 1, 2, 3, 49)]
    raw = dict(id='chr_example', raw=dict(mainAttrType=39, subAttrType=40,
               attributes=[dict(Attribute=dict(attrs=attrs), breakStage=stage) for stage in (0, 1)],
               unused='large'))
    projected = extractor.project('data/local_tables/character/items/chr_example.json', raw)
    rows = projected['raw']['attributes']
    assert [row['breakStage'] for row in rows] == [0, 1]
    assert rows[0]['Attribute']['attrs'] == attrs[:-1]
    assert projected['raw']['mainAttrType'] == 39
    assert 'unused' not in projected['raw']
    assert raw['raw']['attributes'][0]['Attribute']['attrs'] == attrs


def test_weapon_manifest_projection_preserves_hint_order_and_created_id_fallback():
    extractor = tool('extract_runtime_data')
    def entry(key, hints, high=None):
        return dict(id=key, binaryProbe=dict(blackboardDoubleHints=hints,
                    highConfidenceCreatedBuffIds=high, createdBuffIds=['buff_wpn_fallback'], unused='large'))
    raw = dict(entries=[entry('sk_chr_unused', [dict(key='max_stack', value=9)]),
                        entry('sk_wpn_unused', [dict(key='attack', value=5)]),
                        entry('sk_wpn_example', [dict(key='max_stack', value=-1),
                              dict(key='max_stack', value=3, unused='large')], []),
                        entry('sk_wpn_high', [dict(key='max_stack', value=4)], ['buff_wpn_high'])])
    projected = extractor.project('data/local_static/skill/manifest.json', raw)
    assert projected['sourceResourceCount'] == 4
    assert [row['id'] for row in projected['entries']] == ['sk_wpn_example', 'sk_wpn_high']
    probes = [row['binaryProbe'] for row in projected['entries']]
    assert probes[0]['blackboardDoubleHints'] == [dict(key='max_stack', value=-1), dict(key='max_stack', value=3)]
    assert (probes[0]['highConfidenceCreatedBuffIds'] or probes[0]['createdBuffIds']) == ['buff_wpn_fallback']
    assert (probes[1]['highConfidenceCreatedBuffIds'] or probes[1]['createdBuffIds']) == ['buff_wpn_high']


def projection_fixture(root):
    data = root / '_internal/data'
    data.mkdir(parents=True)
    runtime = b'{"value":42}'
    override = b'{"rule":true}'
    (data / 'rule.json').write_bytes(override)
    with zipfile.ZipFile(data / 'runtime-data.zip', 'w') as bundle:
        bundle.writestr('data/base.json', runtime)
    rows = [dict(path='data/base.json', bytes=len(runtime), sha256=hashlib.sha256(runtime).hexdigest(), origin='runtime_projection'),
            dict(path='data/rule.json', bytes=len(override), sha256=hashlib.sha256(override).hexdigest(), origin='development_override')]
    archive = data / 'runtime-data.zip'
    manifest = dict(schema_version=2, files=rows,
                    bundle=dict(path='data/runtime-data.zip', bytes=archive.stat().st_size,
                                sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    (data / 'resource-manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    return data, manifest


def test_source_setup_uses_bundled_projection_without_network_or_raw(tmp_path, monkeypatch):
    resources = tool('prepare_resources')
    data, _ = projection_fixture(tmp_path)
    monkeypatch.setattr(resources, 'acquire_archive', lambda *a, **k: pytest.fail('No upstream archive for normal setup'))
    assert resources.prepare(tmp_path, check=True) == 2
    assert resources.prepare(tmp_path, offline=True) == 0
    assert json.loads((data / 'base.json').read_bytes()) == {'value': 42}
    assert resources.prepare(tmp_path, check=True) == 0
    assert resources.prepare(tmp_path, offline=True) == 0
    assert not (tmp_path / '_development/raw-resources').exists()
    assert not (tmp_path / '_internal/secrets').exists()


def test_bundled_projection_rejects_changes_and_unreviewed_members(tmp_path):
    resources = tool('prepare_resources')
    data, manifest = projection_fixture(tmp_path)
    archive = data / 'runtime-data.zip'
    with zipfile.ZipFile(archive, 'a') as bundle:
        bundle.writestr('../outside.json', b'{}')
    with pytest.raises(ValueError, match='missing or changed'):
        resources.prepare(tmp_path, offline=True)
    manifest['bundle'].update(bytes=archive.stat().st_size, sha256=resources.digest(archive))
    (data / 'resource-manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='member set'):
        resources.prepare(tmp_path, offline=True)
    assert not (tmp_path / 'outside.json').exists()


def test_raw_maintenance_is_separate_and_does_not_extract_keys_or_uploader(tmp_path):
    resources = tool('prepare_resources')
    data, manifest = projection_fixture(tmp_path)
    archive = tmp_path / 'official-fixture.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(resources.PREFIX + 'data/raw.json', b'{"visual_config":[1,2,3]}')
        bundle.writestr(resources.PREFIX + 'secrets/client_privkey.pem', b'not requested')
        bundle.writestr(resources.PREFIX + 'uploader/uploader.exe', b'not requested')
    manifest['source_archive_sha256'] = resources.digest(archive)
    resources.prepare_raw(tmp_path, manifest, archive)
    raw = tmp_path / '_development/raw-resources/_internal'
    assert (raw / 'data/raw.json').is_file()
    assert not (data / 'raw.json').exists()
    assert not (raw / 'secrets').exists()
    assert not (raw / 'uploader').exists()
    assert (raw / 'data/rule.json').read_bytes() == (data / 'rule.json').read_bytes()
    inventory = json.loads((raw / 'data/resource-manifest.json').read_text(encoding='utf8'))
    assert inventory['schema_version'] == 1
    assert inventory['source_archive_sha256'] == manifest['source_archive_sha256']


def test_extraction_refuses_compact_inputs_and_nested_output(tmp_path):
    extractor = tool('extract_runtime_data')
    data, _ = projection_fixture(tmp_path)
    with pytest.raises(ValueError, match='verified raw source inventory'):
        extractor.build(data.parent, tmp_path / 'output')
    with pytest.raises(ValueError, match='separate'):
        extractor.build(data.parent, data / 'output')


def test_portable_data_copy_uses_only_manifest_and_excludes_raw_and_restore_zip(tmp_path, monkeypatch):
    resources = tool('prepare_resources')
    source = tmp_path / 'source'
    data, _ = projection_fixture(source)
    resources.prepare(source, offline=True)
    (data / 'unused-raw.json').write_text('raw data', encoding='utf8')
    builder = tool('build_portable')
    monkeypatch.setattr(builder, 'ROOT', source)
    stage = tmp_path / 'stage'
    builder.copy_runtime_data(stage)
    assert (stage / '_internal/data/base.json').is_file()
    assert not (stage / '_internal/data/runtime-data.zip').exists()
    assert not (stage / '_internal/data/unused-raw.json').exists()


def test_real_runtime_bundle_contains_only_inventory_members():
    data = ROOT / '_internal/data'
    manifest = json.loads((data / 'resource-manifest.json').read_text(encoding='utf8'))
    assert manifest['schema_version'] == 2
    with zipfile.ZipFile(data / 'runtime-data.zip') as bundle:
        expected = {row['path']: row for row in manifest['files'] if row['origin'] == 'runtime_projection'}
        assert len(bundle.namelist()) == len(expected)
        assert set(bundle.namelist()) == set(expected)
        for path, row in expected.items():
            content = bundle.read(path)
            assert len(content) == row['bytes']
            assert hashlib.sha256(content).hexdigest() == row['sha256']
        assert 'data/local_static/buff/typed_roots.json.gz' in expected
        assert not any('typed_audit' in name or 'rotation-assets' in name for name in expected)


def test_new_character_ids_are_discovered_and_missing_raw_items_are_rejected(tmp_path, monkeypatch):
    extractor = tool('extract_runtime_data')
    resources = tool('prepare_resources')
    monkeypatch.setattr(extractor, 'FIXED', {'data/akedata/character/manifest.json'})
    monkeypatch.setattr(extractor, 'ITEMS', ('data/akedata/character/items',))
    source, projected, clean = (tmp_path / name for name in ('raw', 'projected', 'clean'))
    rows = []
    for key in ('chr_9998_new_alpha', 'chr_9999_new_beta'):
        relative = f'data/akedata/character/items/{key}.json'
        content = json.dumps(dict(charId=key, skills=[dict(name='New skill', groupType=2,
                             skillIds=[key+'_normal_skill'], description='description')], unused='large')).encode()
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        rows.append(dict(path=relative, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
    relative = 'data/akedata/character/manifest.json'
    content = json.dumps([dict(id='chr_9998_new_alpha'), dict(id='chr_9999_new_beta')]).encode()
    (source / relative).write_bytes(content)
    rows.append(dict(path=relative, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
    (source / 'data/resource-manifest.json').write_text(json.dumps(dict(schema_version=1,
        source_archive_sha256=extractor.SOURCE['source_archive_sha256'], files=rows)), encoding='utf8')
    manifest = extractor.build(source, projected)
    import shutil
    shutil.copytree(projected, clean / '_internal', ignore=shutil.ignore_patterns('items', 'manifest.json'))
    assert resources.prepare(clean, offline=True) == 0
    for row in rows[:2]:
        value = json.loads((clean / '_internal' / row['path']).read_bytes())
        assert value['skills'][0]['skillIds'] == [value['charId']+'_normal_skill']
        assert 'unused' not in value
    assert {row['path'] for row in manifest['files']} == {row['path'] for row in rows}
    (source / rows[0]['path']).unlink()
    with pytest.raises(ValueError, match='Raw item set differs'):
        extractor.build(source, tmp_path / 'incomplete')
