"""Release boundaries: no personal state, no extra keys, no host Python fallback."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('portable_builder', ROOT / '_development/tools/build_portable.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


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
               '_development/implementations/phase/实施结果.md',
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
    retained = ['launch_gui.py', 'Start-GUI.cmd', '_internal/src/endfield_pcap/service.py',
                '_internal/packages/parser_core/tests/test_unified.py', '_development/tests/test_portable_packaging.py',
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
                '_development/tools/verify_runtime_projection.py', '_development/tests/test_runtime_projection.py',
                '_development/tools/prepare_resources.py', '_development/tools/release.py']
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
                                     'Uploader/tool/uploader_settings.json'])
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
    ca = put(tmp_path, 'Uploader/tool/_internal/certifi/cacert.pem', 'public test CA')
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
                     '_internal/src/app.py', '_internal/packages/core.py'):
        put(source, relative)
    key = put(source, '_internal/secrets/client_privkey.pem')
    key.write_bytes(RSA.generate(1024).export_key())
    uploader = put(source, 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe')
    monkeypatch.setattr(builder, 'ROOT', source)
    monkeypatch.setattr(builder, 'RELEASES', tmp_path / 'releases')
    monkeypatch.setattr(builder, 'CAPTURE_KEY_SHA256', builder.digest(key))
    monkeypatch.setattr(builder, 'OFFICIAL_UPLOADER_SHA256', builder.digest(uploader))
    monkeypatch.setitem(sys.modules, 'prepare_resources', SimpleNamespace(prepare=lambda *a, **kw: 0))
    monkeypatch.setitem(sys.modules, 'audit_runtime_data', SimpleNamespace(verify=lambda: None))
    monkeypatch.setattr(builder, 'copy_runtime_data', lambda stage: None)
    monkeypatch.setattr(builder, 'copy_python', lambda stage: None)
    monkeypatch.setattr(builder, 'copy_dependencies', lambda stage: {})
    monkeypatch.setattr(builder, 'write_manifest', lambda stage, versions: None)
    stage = builder.stage_release()
    assert (stage / '_internal/secrets/client_privkey.pem').read_bytes() == key.read_bytes()
    assert (stage / 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe').read_bytes() == uploader.read_bytes()


def test_launcher_prefers_portable_runtime_over_system_python():
    script = (ROOT / 'Start-GUI.cmd').read_text(encoding='utf8')
    assert script.index('goto portable_python') < script.index('goto venv_python') < script.index('where py')
    assert '"%~dp0_internal\\python\\python.exe" -B "%~dp0launch_gui.py" --detach %*' in script
