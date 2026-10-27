"""Public fixture boundaries and native dependency isolation."""
from app_test_support.runtime.tools import tool
from app_test_support.paths import ROOT
import hashlib
import json
import pytest
from pathlib import Path


@pytest.mark.parametrize('relative,accepted', [
    ('.github/workflows/ci.yml', True), ('.github/workflows/manual.yaml', True),
    ('.github/secrets.txt', False), ('.github/workflows/random.txt', False),
    ('.github/workflows/nested/ci.yml', False), ('unknown/source.py', False),
])
def test_repository_audit_accepts_only_workflow_yaml_under_github(tmp_path, monkeypatch, capsys, relative, accepted):
    import subprocess
    import sys
    audit = tool('audit_repository')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text('fixture', encoding='utf8')
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['audit_repository.py', '--worktree'])
    assert audit.main() == (0 if accepted else 1)
    assert ('unexpected root directory' in capsys.readouterr().out) == (not accepted)


@pytest.mark.parametrize('label,accepted', [('悬浮窗配置已迁移', True), ('确认？', True), ('?' * 7, False)])
def test_repository_audit_rejects_unreadable_gui_text(tmp_path, monkeypatch, capsys, label, accepted):
    import subprocess
    import sys
    audit = tool('audit_repository')
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    target = tmp_path / '_internal/src/endfield_pcap/gui/main.py'
    target.parent.mkdir(parents=True)
    target.write_text(f'title = {label!r}\n', encoding='utf8')
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['audit_repository.py', '--worktree'])
    assert audit.main() == (0 if accepted else 1)
    assert ('unreadable GUI text placeholder' in capsys.readouterr().out) == (not accepted)


def test_public_protocol_fixtures_are_constructed_without_opening_a_recording(monkeypatch):
    generator = tool('generate_test_fixtures')
    folder = ROOT / '_internal/packages/parser_core/tests/fixtures'
    expected = {p.name: p.read_bytes() for p in folder.glob('*.log')}
    manifests = {name: json.loads((folder / name).with_suffix('.json').read_text(encoding='utf8'))
                 for name in expected if name.startswith('synthetic_')}
    assert set(expected) == {'rdps_snapshot_contract.log', 'ink_recording_contract.log',
                            'synthetic_fire_corrosion.log', 'synthetic_corrosion_packet.log',
                            'synthetic_combo_skill.log', 'synthetic_combo_ultimate.log'}
    def unexpected_read(*args, **kwargs):
        raise AssertionError('Synthetic scenarios must not read recorded logs')
    monkeypatch.setattr(Path, 'open', unexpected_read)
    for name, lines in generator.generate().items():
        payload = ('# SYNTHETIC protocol scenario; generated from constants, not a battle capture.\n' +
                   '\n'.join(lines) + '\n').encode()
        assert payload == expected[name]
        assert manifests[name]['kind'] == 'synthetic'
        assert manifests[name]['fixtureSha256'] == hashlib.sha256(payload).hexdigest()
        assert 'sourceLineNumbers' not in manifests[name]
    assert all('synthetic' in data.splitlines()[0].decode().lower() for data in expected.values())

def test_active_virtual_environment_cannot_mix_legacy_native_dependencies(tmp_path, monkeypatch):
    from endfield_pcap.runtime.environment import configure_paths
    import os
    import sys
    for name in ['src', 'packages/parser_core', 'packages/uploader_core', 'python_deps/gui', 'python_deps/common']:
        (tmp_path / '_internal' / name).mkdir(parents=True)
    monkeypatch.setattr(sys, 'path', [])
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / '.venv'))
    monkeypatch.setattr(sys, 'base_prefix', str(tmp_path / 'base-python'))
    monkeypatch.setattr(os, 'add_dll_directory', lambda p: str(p))
    configure_paths(tmp_path)
    assert all('python_deps' not in p for p in sys.path)
    configure_paths(tmp_path, isolated=False)
    assert any('python_deps' in p for p in sys.path)


@pytest.mark.parametrize('configured,expected', [(None, '1'), ('3', '3')])
def test_runtime_limits_unused_blas_pool_without_overriding_user(tmp_path, monkeypatch, configured, expected):
    import os
    import sys
    from endfield_pcap.runtime.environment import configure_paths

    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(os, 'add_dll_directory', lambda path: None)
    if configured is None:
        monkeypatch.delenv('OPENBLAS_NUM_THREADS', raising=False)
    else:
        monkeypatch.setenv('OPENBLAS_NUM_THREADS', configured)
    configure_paths(tmp_path, isolated=True)
    assert os.environ['OPENBLAS_NUM_THREADS'] == expected
