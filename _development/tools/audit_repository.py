"""Inspect exactly the staged Git blobs for accidental private/binary content.

Only filenames and issue categories are printed, never matched secret values.
This is a useful pre-commit check, not a replacement for reviewing the diff.
"""
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s"\x27]{0,8}(?:\r?\n|\\n)[A-Za-z0-9+/=]{32,}|(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})')
LOCAL = re.compile(rb'(?:[A-Za-z]:[\\/]Users[\\/][^\s"\x27<>]+|[A-Za-z]:[\\/]MyFiles[\\/][^\s"\x27<>]+)')
LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)]+)\)')


def staged_blobs():
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).split(b'\0')
    names, hashes = [], []
    for entry in entries:
        if entry:
            info, path = entry.split(b'\t', 1)
            names.append(path.decode('utf8'))
            hashes.append(info.split()[1])
    response = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT, input=b'\n'.join(hashes)+b'\n')
    offset, result = 0, {}
    for path in names:
        end = response.index(b'\n', offset)
        size = int(response[offset:end].split()[2])
        result[path] = response[end+1:end+1+size]
        offset = end+size+2
    return result


def main():
    blobs = staged_blobs()
    issues = []
    for name, content in blobs.items():
        path = PurePosixPath(name)
        if path.suffix.lower() in {'.pem', '.key', '.pfx', '.p12', '.exe', '.dll', '.pyd', '.zip', '.ndjson', '.pcap', '.pcapng'}:
            issues.append((name, 'private/binary file type'))
        if path.parts[0] not in {'_internal', '_development'} and len(path.parts) > 1:
            issues.append((name, 'unexpected root directory'))
        if SECRET.search(content):
            issues.append((name, 'private key or credential token'))
        if LOCAL.search(content):
            issues.append((name, 'machine-local user path'))
        if path.suffix == '.md':
            text = content.decode('utf8')
            for target in LINK.findall(text):
                target = target.split('#')[0].strip('<>')
                if not target or re.match(r'[a-z]+:', target, re.I):
                    continue
                resolved = (ROOT / path.parent / target).resolve()
                if not resolved.is_relative_to(ROOT) or resolved.relative_to(ROOT).as_posix() not in blobs:
                    issues.append((name, 'documentation link not in repository: ' + target))
    print(f'Staged: {len(blobs)} files, {sum(map(len, blobs.values())):,} bytes')
    for name, reason in issues:
        print(f'{name}: {reason}')
    if issues:
        return 1
    print('Staged credential/path/file-type/link checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
