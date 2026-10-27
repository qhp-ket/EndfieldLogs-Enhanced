"""Scope selection must preserve shared boundaries and never report skipped suites as passed."""
import json
import subprocess
import sys

import pytest

from app_test_support.paths import ROOT
from app_test_support.runtime.tools import tool


@pytest.mark.parametrize('paths,expected', [
    (['README.md', '_development/portable/licenses/EndfieldLogs-MIT.txt'], set()),
    (['_development/tests/overlays/test_native_client.py'], {'app-overlays'}),
    (['_internal/src/endfield_pcap/gui/battle/presenter.py'], {'app-battle', 'app-history', 'app-gui', 'app-independent'}),
    (['_internal/src/endfield_pcap/inputlog/controller.py'], {'app-independent', 'app-battle', 'app-history', 'app-gui'}),
    (['_internal/src/endfield_pcap/service/runtime/websocket.py'], {'live', 'parser_core', 'uploader_core'}),
    (['_development/portable/runtime-requirements.txt'], {'live', 'parser_core', 'uploader_core'}),
    (['_development/tests/conftest.py'], {'live', 'parser_core', 'uploader_core'}),
    (['.github/workflows/ci.yml'], {'live', 'parser_core', 'uploader_core'}),
    (['unrecognized.py'], {'live', 'parser_core', 'uploader_core'}),
])
def test_scope_matches_documented_impact(paths, expected):
    selection = tool('select_tests').plan(paths)
    assert set(selection['suites']) == expected
    assert selection['checks'] == ['audit', 'documentation']


def test_rename_includes_removed_old_boundary_and_combined_suites_are_unique():
    scope = tool('select_tests')
    paths = scope.parse_changes(b'R100\0_internal/src/endfield_pcap/service/old.py\0_internal/src/endfield_pcap/gui/new.py\0D\0README.md\0')
    assert paths == ['_internal/src/endfield_pcap/service/old.py', '_internal/src/endfield_pcap/gui/new.py', 'README.md']
    assert scope.plan(paths)['suites'] == list(scope.FULL)
    chosen = scope.plan(['_internal/packages/parser_core/parser_core/parser.py', '_internal/packages/uploader_core/uploader_core/payload.py'])['suites']
    assert chosen.count('app-history') == chosen.count('uploader_core') == 1
    assert set(chosen) == {'parser_core', 'uploader_core', 'app-battle', 'app-history', 'app-service'}
    assert scope.parse_changes(b'') == []
    with pytest.raises(ValueError):
        scope.parse_changes(b'R100\0missing-new-name\0')


def test_push_and_pr_use_complete_ranges_and_pr_merge_base(tmp_path):
    scope = tool('select_tests')
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path).decode().strip()
    git('init', '-q')
    git('config', 'user.name', 'Synthetic Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'README.md').write_text('base', encoding='utf8')
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    git('checkout', '-qb', 'topic')
    (tmp_path / 'README.md').rename(tmp_path / 'GUIDE.md')
    git('add', '-A')
    git('commit', '-qm', 'rename')
    head = git('rev-parse', 'HEAD')
    assert scope.changed_paths(tmp_path, 'push', dict(before=base, after=head)) == ['README.md', 'GUIDE.md']
    git('checkout', '-qb', 'base-progress', base)
    (tmp_path / 'unrelated.py').write_text('unrelated base change', encoding='utf8')
    git('add', '.')
    git('commit', '-qm', 'base progress')
    advanced = git('rev-parse', 'HEAD')
    assert scope.changed_paths(tmp_path, 'pull_request', dict(pull_request=dict(base=dict(sha=advanced), head=dict(sha=head)))) == ['README.md', 'GUIDE.md']


def test_missing_diff_and_manual_runs_fall_back_to_full(tmp_path, monkeypatch):
    scope = tool('select_tests')
    output = tmp_path / 'selection.json'
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(dict(before='0' * 40, after='1' * 40)), encoding='utf8')
    for event_name in ['push', 'workflow_dispatch', 'unexpected']:
        monkeypatch.setattr(sys, 'argv', ['select_tests.py', '--event-name', event_name, '--event-file', str(event), '--output', str(output)])
        assert scope.main() == 0
        result = json.loads(output.read_text(encoding='utf8'))
        assert result['suites'] == list(scope.FULL) and result['full']


def test_selected_runner_continues_after_failure_and_reports_skips(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / '_development/tools'))
    runner = tool('run_ci_tests')
    monkeypatch.setattr(runner, 'source_state', lambda: dict(head='synthetic'))
    report = tmp_path / 'report.json'
    calls = []
    def invoke(arguments):
        calls.append(arguments[-1])
        return 1 if arguments[-1] == 'app-history' else 0
    selection = dict(suites=['app-history', 'app-gui'], reasons=['synthetic changed paths'])
    assert runner.run(selection, report, invoke) == 1
    result = json.loads(report.read_text(encoding='utf8'))
    assert calls[-2:] == ['app-history', 'app-gui']
    assert result['results']['app-history']['status'] == 'failed'
    assert result['results']['app-gui']['status'] == 'passed'
    assert result['results']['parser_core']['status'] == 'not_selected'
    assert '按范围跳过（未验证）' in runner.summary(selection, result['results'])
    calls.clear()
    assert runner.run(dict(suites=[], reasons=['documentation']), report, invoke) == 0
    assert calls == ['--worktree', '_development/tools/check_documentation.py']


def test_portable_documentation_reports_missing_delivery_reference(tmp_path):
    docs = tool('check_documentation')
    assert docs.check(ROOT) == []
    for name in [*docs.DOCUMENTS.values(), '_development/portable/README-uploader.zh-CN.md']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic', encoding='utf8')
    (tmp_path / docs.DOCUMENTS['README.zh-CN.md']).write_text('`licenses/missing.txt`', encoding='utf8')
    assert docs.check(tmp_path) == ['发行说明引用了未交付的许可文件：licenses/missing.txt']
