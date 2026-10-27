"""Release boundaries: no personal state, no extra keys, no host Python fallback."""
from app_test_support.runtime.packaging import builder
from app_test_support.paths import ROOT
import json
import shutil
import subprocess
import sys
from types import SimpleNamespace
import pytest
from Crypto.PublicKey import RSA

def put(root, relative, text='fixture'):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf8')
    return path

def test_gitignore_keeps_source_and_tests_but_excludes_private_and_generated_files(tmp_path):
    if not shutil.which('git'):
        pytest.skip('git is required to validate actual ignore semantics')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    shutil.copy2(ROOT / '.gitignore', tmp_path / '.gitignore')
    ignored = ['.dev-gui/settings.json', '_internal/secrets/extra.pem', 'local/extra.pem', '.env', 'nested/.env.production',
               '_internal/python_deps/common/pytest/__init__.py', '_internal/python/python.exe',
               'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe', '_releases/build/a.zip',
               '_development/verification/result.json', '_development/official-release/source.py',
               '_development/implementations/phase/before/service.py',
               '_development/implementations/phase/live-tmp/settings.json',
               '_development/implementations/phase/nested/parser_core-tmp/buff.json',
               '_development/implementations/phase/visual-tmp/qt-cache/cache.json',
               '_development/implementations/phase/tmp/settings.json',
               '_development/implementations/phase/qt-storage/preferences.json',
               '_development/implementations/phase/probe-after.json',
               '_development/implementations/phase/瀹炴柦缁撴灉.md',
               '_internal/data/akedata/chars/character.json',
               '_internal/jsondata/CharacterNameIndex.json',
               '_development/docs/repository-follow-up-plan.md',
               '_development/tools/verify_uploaded_battle.py',
               'new-private-folder/notes.md',
               '_development/cache/wheels/package.whl',
               '_internal/packages/parser_core/tests/fixtures/private_battle.log',
               'nested/__pycache__/x.pyc']
    ignored += ['_internal/src/uploader_settings.json', '_internal/src/.venv/pyvenv.cfg', '_internal/src/build/output.py',
                '_development/tests/tmp/record.json', '_internal/src/trace_20261024.log.status.json',
                '_development/tests/.cache/state.json', '_internal/data/akedata/character/items/chr_9999_future.json',
                '_development/raw-resources/_internal/data/new.json']
    ignored += ['_internal/data/ui/raw/portrait.png', '_internal/data/ui/characters/original.psd']
    ignored += ['_internal/native/SDL3.dll','_internal/src/private.input.jsonl','trace.input.jsonl']
    ignored += ['_internal/src/nested/.dev-gui/settings.json',
                '_internal/src/nested/private.input.jsonl.part',
                '_development/tests/recorded_events.jsonl']
    ignored += ['.github/secrets.txt', '.github/workflows/private.txt',
                '.github/workflows/nested/job.yml']
    retained = ['launch_gui.py', 'Start-GUI.cmd', '_internal/src/endfield_pcap/service/runtime/server.py',
                '_internal/packages/parser_core/tests/reporting/test_unified.py', '_development/tests/resources/test_portable_packaging.py',
                '_development/tools/build_portable.py', '_internal/secrets/README.md', '.env.example',
                'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', '.gitattributes', 'Setup-Dev.cmd',
                '_internal/packages/parser_core/tests/fixtures/synthetic_fire_corrosion.log',
                '_internal/packages/parser_core/tests/fixtures/synthetic_corrosion_packet.log',
                '_internal/packages/parser_core/tests/fixtures/synthetic_combo_skill.log',
                '_internal/packages/parser_core/tests/fixtures/synthetic_combo_ultimate.log',
                '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log',
                '_internal/packages/parser_core/tests/fixtures/ink_recording_contract.log',
                '_development/tests/integration/test_capture_key.py',
                '_internal/src/endfield_pcap/_version.py',
                '_internal/data/resource-manifest.json',
                '_internal/data/packet_semantics/rdps_semantics_registry.json',
                '_internal/data/runtime-data.zip', '_development/tools/extract_runtime_data.py',
                '_development/tools/verify_runtime_projection.py', '_development/tests/resources/test_runtime_projection.py',
                '_development/tools/prepare_resources.py', '_development/tools/release.py',
                '_development/tools/build_character_avatars.py', '_internal/data/ui/characters/manifest.json',
                '_internal/data/ui/characters/chr_0002_endminm.png']
    retained += ['_internal/native/manifest.json','_internal/native/SDL3-LICENSE.txt',
                 '_development/tools/prepare_native.py','_development/docs/independent-services.md']
    retained += ['.github/workflows/ci.yml', '.github/workflows/manual.yaml']
    for name in ignored + retained:
        put(tmp_path, name)
    result = subprocess.run(['git', '-c', 'core.excludesFile=NUL', '-c', 'core.quotepath=false', 'check-ignore', '--no-index', '--stdin'],
                            input=('\n'.join(ignored + retained)+'\n').encode('utf8'), cwd=tmp_path,
                            capture_output=True, check=False)
    assert result.returncode == 0
    assert set(result.stdout.decode('utf8').splitlines()) == set(ignored)

@pytest.mark.parametrize('relative', ['.dev-gui/settings.json', '_internal/secrets/extra.pem',
                                     '_internal/secrets/client_privkey.pem', '_internal/src/.env',
                                     '_development/tests/fixture.log', '_internal/src/session.json',
                                     'Uploader/tool/uploader_settings.json', '_internal/src/private.input.jsonl'])
def test_release_rejects_personal_state_or_unapproved_key(tmp_path, relative):
    put(tmp_path, relative)
    with pytest.raises(ValueError):
        builder.validate_tree(tmp_path)

def test_only_allowlisted_capture_key_and_public_ca_can_be_distributed(tmp_path, monkeypatch):
    target = tmp_path / '_internal/secrets/client_privkey.pem'
    target.parent.mkdir(parents=True)
    # Test-only key and digest; the real builder's official allowlist is unchanged.
    target.write_bytes(RSA.generate(1024).export_key())
    monkeypatch.setattr(builder, 'CAPTURE_KEY_SHA256', builder.digest(target))
    ca = put(tmp_path, '_internal/python_deps/common/certifi/cacert.pem', 'public test CA')
    assert set(builder.validate_tree(tmp_path)) == {target, ca}

def test_archive_refuses_files_modified_after_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'RELEASES', tmp_path)
    stage = tmp_path / 'release'
    source = put(stage, 'launch_gui.py', 'original')
    manifest = {'files': {'launch_gui.py': {'sha256': builder.digest(source)}}}
    put(stage, 'BUILD-MANIFEST.json', json.dumps(manifest))
    source.write_text('modified', encoding='utf8')
    with pytest.raises(ValueError, match='changed'):
        builder.zip_stage(stage)
    assert not (tmp_path / 'release.zip').exists()

def test_portable_stage_includes_verified_capture_key(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for relative in ('Start-GUI.cmd', 'launch_gui.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                     '_development/portable/README.zh-CN.md', '_development/portable/licenses/test.txt',
                     '_development/docs/licensing.md',
                     '_internal/src/app.py', '_internal/packages/core.py'):
        put(source, relative)
    portrait = put(source, '_internal/data/ui/characters/placeholder.png')
    key = put(source, '_internal/secrets/client_privkey.pem')
    key.write_bytes(RSA.generate(1024).export_key())
    monkeypatch.setattr(builder, 'ROOT', source)
    monkeypatch.setattr(builder, 'RELEASES', tmp_path / 'releases')
    monkeypatch.setattr(builder, 'CAPTURE_KEY_SHA256', builder.digest(key))
    monkeypatch.setitem(sys.modules, 'prepare_resources', SimpleNamespace(prepare=lambda *a, **kw: 0))
    monkeypatch.setitem(sys.modules, 'audit_runtime_data', SimpleNamespace(verify=lambda: None))
    monkeypatch.setitem(sys.modules, 'prepare_native', SimpleNamespace(prepare_native=lambda *a, **kw: None))
    for name in ('SDL3.dll','SDL3-LICENSE.txt','manifest.json'):
        put(source,'_internal/native/'+name)
    monkeypatch.setattr(builder, 'copy_runtime_data', lambda stage: None)
    monkeypatch.setattr(builder, 'copy_python', lambda stage: None)
    monkeypatch.setattr(builder, 'dependencies', lambda: {})
    monkeypatch.setattr(builder, 'copy_dependencies', lambda stage: {})
    monkeypatch.setattr(builder, 'write_manifest', lambda stage, versions: None)
    stage = builder.stage_release()
    assert (stage / '_internal/secrets/client_privkey.pem').read_bytes() == key.read_bytes()
    assert (stage / 'licenses/EndfieldLogs-LICENSING.zh-CN.md').read_bytes() == (source / '_development/docs/licensing.md').read_bytes()
    assert (stage / 'licenses/EndfieldLogs-LICENSE.txt').read_bytes() == (source / 'LICENSE').read_bytes()
    assert not (stage / 'Uploader').exists()
    assert (stage / '_internal/data/ui/characters/placeholder.png').read_bytes() == portrait.read_bytes()

def test_application_rejects_accidentally_bundled_uploader(tmp_path):
    put(tmp_path, 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe')
    with pytest.raises(ValueError, match='Unexpected'):
        builder.validate_tree(tmp_path)

def test_official_uploader_build_is_independent_of_app_python_data_and_key(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    uploader = put(source, 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe', 'official fixture')
    put(source, '_development/portable/README-uploader.zh-CN.md')
    put(source, '_development/portable/licenses/upstream.txt')
    import zipfile
    from portable_uploader import PREFIX
    archive = source / 'official.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(PREFIX + 'EndfieldLogsUploader/EndfieldLogsUploader.exe', uploader.read_bytes())
    put(source, '_internal/data/resource-manifest.json', '{}')
    monkeypatch.setitem(sys.modules, 'prepare_resources', SimpleNamespace(acquire_archive=lambda *a: archive))
    monkeypatch.setattr(builder, 'ROOT', source)
    monkeypatch.setattr(builder, 'RELEASES', tmp_path / 'releases')
    monkeypatch.setattr(builder, 'OFFICIAL_UPLOADER_SHA256', builder.digest(uploader))
    # The fixture lives below the developer checkout. Give it its own clean
    # Git boundary so provenance does not inherit unrelated worktree changes.
    subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
    (source / '.git/info/exclude').write_text('*\n', encoding='utf8')
    stage = builder.stage_uploader()
    assert stage.name == builder.UPLOADER_RELEASE_NAME
    assert not (stage / '_internal').exists()
    assert not (stage / 'Start-GUI.cmd').exists()
    manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text(encoding='utf8'))
    assert manifest['component'] == 'official_uploader'
    assert manifest['application']['version'] == builder.UPLOADER_VERSION
    assert 'capture_key' not in manifest
    assert manifest['source_dirty'] is False
    archive = builder.zip_stage(stage)
    assert archive.name == builder.UPLOADER_RELEASE_NAME+'.zip'
    manifest['source_dirty'] = True
    (stage / 'BUILD-MANIFEST.json').write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='Dirty development staging'):
        builder.zip_stage(stage)

def test_launcher_prefers_portable_runtime_over_system_python():
    script = (ROOT / 'Start-GUI.cmd').read_text(encoding='utf8')
    assert script.index('goto portable_python') < script.index('goto venv_python') < script.index('where py')
    assert '"%~dp0_internal\\python\\python.exe" -B "%~dp0launch_gui.py" --detach %*' in script
