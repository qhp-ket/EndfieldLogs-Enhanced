"""Run selected checks sequentially and report selected, skipped and unfinished work."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from select_tests import ORDER, plan

ROOT = Path(__file__).resolve().parents[2]


def summary(selection, results):
    lines = ['# 验证范围', '', *['- ' + reason for reason in selection['reasons']], '',
             '| 检查 | 结果 |', '| --- | --- |']
    labels = {'passed': '通过', 'failed': '失败', 'not_run': '未执行', 'not_selected': '按范围跳过（未验证）'}
    for name, result in results.items():
        lines.append(f'| {name} | {labels[result["status"]]} |')
    return '\n'.join(lines) + '\n'


def source_state():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT)
    paths = ['_development/environment/constraints-ci.txt', '_development/portable/runtime-requirements.txt',
             '_internal/data/resource-manifest.json']
    untracked = [name.decode('utf8') for name in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if name]
    return dict(head=git('rev-parse', 'HEAD').decode().strip(),
                worktree=git('status', '--porcelain').decode('utf8'),
                tracked_diff_sha256=hashlib.sha256(git('diff', '--binary', 'HEAD')).hexdigest(),
                untracked_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in untracked},
                python=sys.version, resource_dependencies={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths})


def run(selection, report_path, invoke=None):
    invoke = invoke or (lambda args: subprocess.run(args, cwd=ROOT).returncode)
    if any(name not in ORDER for name in selection['suites']):
        raise ValueError('Unknown test suite in CI selection')
    selected = selection['suites']
    results = {name: dict(status='not_run' if name in selected else 'not_selected') for name in ORDER}
    checks = [('audit', ['_development/tools/audit_repository.py', '--worktree']),
              ('documentation', ['_development/tools/check_documentation.py'])]
    if selected:
        checks.append(('runtime-data', ['_development/tools/prepare_resources.py', '--offline']))
    results = {**{name: dict(status='not_run') for name, _ in checks}, **results}
    report = dict(selection=selection, source=source_state(), results=results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    save()
    for name, arguments in [*checks, *[(suite, ['_development/run_tests.py', suite]) for suite in selected]]:
        print(f'Verification: {name}', flush=True)
        try:
            code = invoke([sys.executable, '-B', *arguments])
            results[name] = dict(status='passed' if code == 0 else 'failed', exit_code=code)
        except OSError as error:
            results[name] = dict(status='failed', error=str(error))
        save()
    return int(any(result['status'] in {'failed', 'not_run'} for result in results.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, default=ROOT / '_development/verification/test-selection.json')
    parser.add_argument('--report', type=Path, default=ROOT / '_development/verification/ci-results.json')
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()
    if args.summary_only:
        if args.report.is_file():
            report = json.loads(args.report.read_text(encoding='utf8'))
            text = summary(report['selection'], report['results'])
        else:
            text = '# 验证未执行\n\n检查准备步骤的失败信息。\n'
        print(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf8') as stream:
                stream.write(text)
        return 0
    selection = json.loads(args.selection.read_text(encoding='utf8')) if args.selection.is_file() else plan([], '分类结果缺失：执行全套')
    return run(selection, args.report)


if __name__ == '__main__':
    raise SystemExit(main())
