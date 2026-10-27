"""Check the source documents and license references shipped in portable packages."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    'README.zh-CN.md': '_development/portable/README.zh-CN.md',
    'licenses/EndfieldLogs-LICENSE.txt': 'LICENSE',
    'licenses/EndfieldLogs-THIRD_PARTY_NOTICES.md': 'THIRD_PARTY_NOTICES.md',
    'licenses/EndfieldLogs-LICENSING.zh-CN.md': '_development/docs/licensing.md',
}


def check(root):
    files = dict(DOCUMENTS)
    files.update((f'licenses/{path.name}', path.relative_to(root).as_posix())
                 for path in (root / '_development/portable/licenses').glob('*') if path.is_file())
    issues = [f'发行说明缺失或为空：{source}' for source in files.values()
              if not (root / source).is_file() or not (root / source).stat().st_size]
    uploader = root / '_development/portable/README-uploader.zh-CN.md'
    if not uploader.is_file() or not uploader.stat().st_size:
        issues.append('独立上传器说明缺失或为空')
    readme = root / DOCUMENTS['README.zh-CN.md']
    if readme.is_file():
        for target in re.findall(r'`(licenses/[^`]+)`', readme.read_text(encoding='utf8')):
            if target.rstrip('/') != 'licenses' and target not in files:
                issues.append(f'发行说明引用了未交付的许可文件：{target}')
    return issues


if __name__ == '__main__':
    issues = check(ROOT)
    print('\n'.join(issues) if issues else 'Portable documentation references passed.')
    raise SystemExit(bool(issues))
