"""Select sequential regression suites from a complete Git change range."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FULL = ('live', 'parser_core', 'uploader_core')
APPLICATION = ('battle', 'gui', 'history', 'overlays', 'service', 'resources', 'independent', 'integration')
ORDER = ('live', 'parser_core', 'uploader_core', *(f'app-{name}' for name in APPLICATION))
# Prefixes form the shared-boundary map; unrecognized changes select FULL.
RULES = (
    ('_internal/packages/parser_core/', ('parser_core', 'app-battle', 'app-history', 'app-service', 'uploader_core')),
    ('_internal/packages/uploader_core/', ('uploader_core', 'app-history')),
    ('_internal/data/', ('parser_core', 'app-battle', 'app-history', 'app-service', 'app-resources', 'uploader_core')),
    ('_internal/src/endfield_pcap/gui/battle/', ('app-battle', 'app-history', 'app-gui', 'app-independent')),
    ('_internal/src/endfield_pcap/gui/pages/history/', ('app-history', 'app-gui')),
    ('_internal/src/endfield_pcap/gui/pages/overlays/', ('app-overlays', 'app-gui', 'app-independent')),
    ('_internal/src/endfield_pcap/gui/', ('app-gui', 'app-battle', 'app-history', 'app-overlays', 'app-independent')),
    ('_internal/src/endfield_pcap/history/', ('app-history', 'app-gui', 'app-battle')),
    ('_internal/src/endfield_pcap/inputlog/', ('app-independent', 'app-battle', 'app-history', 'app-gui')),
    ('_internal/src/endfield_pcap/vision/', ('app-independent', 'app-overlays', 'app-gui')),
    ('_internal/src/endfield_pcap/overlays/', ('app-overlays', 'app-gui', 'app-history', 'app-independent', 'app-resources')),
    ('_internal/src/endfield_pcap/analysis/', ('app-battle', 'app-history', 'app-service', 'app-overlays')),
    ('_internal/src/endfield_pcap/capture/', ('app-service', 'app-gui')),
    ('_internal/src/endfield_pcap/trace/', ('app-service', 'app-history', 'app-battle')),
    ('_internal/src/endfield_pcap/data/', ('app-resources', 'app-battle', 'app-independent')),
    ('_development/portable/', ('app-resources', 'app-gui')),
)
SHARED = ('_internal/src/endfield_pcap/models', '_internal/src/endfield_pcap/service/',
          '_internal/src/endfield_pcap/settings/', '_internal/src/endfield_pcap/runtime/',
          '_internal/src/endfield_pcap/application/', '_internal/src/endfield_pcap/proto_generated/',
          '_development/environment/', '_development/tests/app_test_support/', '.github/')
PACKAGING = {'build_portable', 'portable_dependencies', 'portable_uploader', 'verify_portable_zip',
             'smoke_portable', 'release', 'prepare_resources', 'prepare_native', 'check_dependencies', 'audit_repository',
             'check_documentation', 'fetch_official_release'}


def plan(paths, full_reason=None):
    selected, reasons = set(), []
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            full_reason = '无法安全分类路径'
            break
        if path.suffix.lower() == '.md' or path.name in {'LICENSE', 'COPYING', 'NOTICE'} or name.startswith('_development/portable/licenses/'):
            reasons.append(f'{name}：文档、许可及打包引用检查')
            continue
        if name.startswith(SHARED) or name in {'_development/run_tests.py', '_development/tests/conftest.py', '.gitignore',
                '_development/portable/runtime-requirements.txt', '_internal/src/endfield_pcap/gui/config.py', '_internal/src/endfield_pcap/gui/service.py'}:
            full_reason = f'{name}：共享边界或验证基础设施'
            break
        if name.startswith('_development/tests/'):
            category = path.parts[2] if len(path.parts) > 2 else ''
            if category in APPLICATION:
                selected.add('app-' + category)
                reasons.append(f'{name}：对应应用测试')
                continue
        if path.name in {'Start-GUI.cmd', 'Setup-Dev.cmd', 'launch_gui.py'} or (name.startswith('_development/tools/') and path.stem in PACKAGING):
            selected.update(('app-resources', 'app-gui'))
            reasons.append(f'{name}：打包与启动')
            continue
        rule = next((suites for prefix, suites in RULES if name.startswith(prefix)), None)
        if rule:
            selected.update(rule)
            reasons.append(f'{name}：功能及已知调用方')
        else:
            full_reason = f'{name}：未识别的影响范围'
            break
    if full_reason:
        selected, reasons = set(FULL), [full_reason]
    if 'live' in selected:
        selected = {name for name in selected if not name.startswith('app-')}
    suites = [name for name in ORDER if name in selected]
    return dict(suites=suites, checks=['audit', 'documentation'], reasons=reasons or ['差异为空：仅执行基础检查'],
                full=bool(full_reason), paths=list(paths))


def parse_changes(data):
    """Read NUL-delimited name-status, including both sides of moves/copies."""
    fields = data.split(b'\0')
    if fields.pop() != b'':
        raise ValueError('Truncated Git change list')
    paths = []
    index = 0
    while index < len(fields):
        status = fields[index].decode('ascii')
        if not status or status[0] not in 'ACDMRTUXB':
            raise ValueError('Unknown Git change status')
        count = 2 if status[0] in 'RC' else 1
        if index + count >= len(fields):
            raise ValueError('Missing Git change path')
        paths.extend(field.decode('utf8') for field in fields[index + 1:index + count + 1])
        index += count + 1
    return list(dict.fromkeys(paths))


def changed_paths(root, event_name, event):
    if event_name == 'pull_request':
        base = event['pull_request']['base']['sha']
        head = event['pull_request']['head']['sha']
        base = subprocess.check_output(['git', 'merge-base', base, head], cwd=root).decode('ascii').strip()
    elif event_name == 'push':
        base, head = event['before'], event['after']
    else:
        raise ValueError('手动验证或未知事件：执行全套')
    if any(not value or len(value) != 40 or any(char not in '0123456789abcdef' for char in value) or set(value) == {'0'} for value in (base, head)):
        raise ValueError('缺少可比较的完整提交')
    return parse_changes(subprocess.check_output(['git', 'diff', '--name-status', '-z', '--find-renames', base, head, '--'], cwd=root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-file', type=Path, default=os.environ.get('GITHUB_EVENT_PATH'))
    parser.add_argument('--event-name', default=os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    try:
        if args.event_name == 'workflow_dispatch':
            selection = plan([], '手动完整验证')
        else:
            event = json.loads(args.event_file.read_text(encoding='utf8')) if args.event_file else {}
            selection = plan(changed_paths(ROOT, args.event_name, event))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        selection = plan([], f'差异不可用，执行全套（{type(error).__name__}）')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf8')
    if args.github_output:
        with args.github_output.open('a', encoding='utf8') as stream:
            stream.write(f'has_tests={str(bool(selection["suites"])).lower()}\n')
    print(json.dumps(selection, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
