"""Restore ignored upstream resources from a pinned, SHA-256-verified ZIP.

Tracked development overrides are never replaced. Keys and the official uploader
are acquired only when requested explicitly. Downloaded applications are not run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'EndfieldLogsClient/_internal/'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resource_path(root, relative):
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in relative or path.parts[0] not in {'data', 'jsondata'}:
        raise ValueError('Unsafe resource path: ' + relative)
    target = (root / '_internal' / relative).resolve()
    if not target.is_relative_to((root / '_internal').resolve()):
        raise ValueError('Resource escapes _internal: ' + relative)
    return target


def missing_resources(root, manifest):
    missing = []
    for row in manifest['files']:
        path = resource_path(root, row['path'])
        if path.is_file():
            if path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
                raise ValueError('Changed resource; review rather than overwrite: ' + row['path'])
        elif row['origin'] != 'official_3_0_12_unchanged':
            raise ValueError('Missing tracked development resource: ' + row['path'])
        else:
            missing.append(row)
    return missing


def acquire_archive(root, manifest, explicit=None, offline=False):
    filename = manifest['source_url'].rsplit('/', 1)[-1]
    candidates = ([explicit] if explicit else [root / '_development/cache' / filename,
                                              root / '_development/verification' / filename])
    for path in candidates:
        if path.is_file():
            if digest(path) != manifest['source_archive_sha256']:
                raise ValueError('Official archive SHA-256 mismatch')
            return path
    if explicit or offline:
        raise FileNotFoundError('Provide the pinned official ZIP with --archive for offline setup')
    target = candidates[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix('.zip.download')
    print('Downloading pinned official resource archive (cached for reuse).', flush=True)
    request = Request(manifest['source_url'], headers={'User-Agent': 'EndfieldLogs resource setup',
                                                     'Referer': 'https://zmdlogs.com/'})
    with urlopen(request, timeout=60) as response, pending.open('wb') as stream:
        shutil.copyfileobj(response, stream, 1024*1024)
    if digest(pending) != manifest['source_archive_sha256']:
        raise ValueError('Downloaded archive SHA-256 mismatch; nothing extracted')
    pending.replace(target)
    return target


def install_member(bundle, member, target, expected=None):
    content = bundle.read(member)
    sha = hashlib.sha256(content).hexdigest()
    if expected and sha != expected:
        raise ValueError('Archive member differs from resource inventory: ' + member)
    if target.exists():
        if not target.is_file() or digest(target) != sha:
            raise ValueError('Refusing to replace a different existing resource: ' + target.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(target.name + '.download')
    pending.write_bytes(content)
    pending.replace(target)


def prepare(root, *, archive=None, offline=False, check=False, uploader=False, capture_key=False):
    manifest = json.loads((root / '_internal/data/resource-manifest.json').read_text(encoding='utf8'))
    missing = missing_resources(root, manifest)
    uploader_exe = root / 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe'
    key = root / '_internal/secrets/client_privkey.pem'
    if check:
        print(f'Runtime resources: {len(manifest["files"])-len(missing)}/{len(manifest["files"])} present and verified.')
        return 2 if missing or (uploader and not uploader_exe.is_file()) or (capture_key and not key.is_file()) else 0
    if not missing and not uploader and not capture_key:
        print('Runtime resources already verified; no download or changes needed.')
        return 0
    source = acquire_archive(root, manifest, archive, offline)
    with zipfile.ZipFile(source) as bundle:
        for row in missing:
            install_member(bundle, PREFIX + row['path'], resource_path(root, row['path']), row['sha256'])
        if uploader:
            prefix = PREFIX + 'uploader/'
            members = [info for info in bundle.infolist() if info.filename.startswith(prefix) and not info.is_dir()]
            if not members:
                raise ValueError('Official uploader missing from archive')
            for info in members:
                relative = PurePosixPath(info.filename[len(prefix):])
                target = (root / 'Uploader' / str(relative)).resolve()
                if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative) or not target.is_relative_to((root / 'Uploader').resolve()):
                    raise ValueError('Unsafe uploader archive member')
                install_member(bundle, info.filename, target)
        if capture_key:
            install_member(bundle, PREFIX + 'secrets/client_privkey.pem', key,
                           'b83257fadefe901f708386da11ffcde0eb0dee6450a6b56fc1b85e197cab1b56')
    if missing_resources(root, manifest):
        raise ValueError('Resource installation incomplete')
    print(f'Verified {len(manifest["files"])} resources; official components prepared as requested.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--check', action='store_true', help='Verify only; missing resources return exit code 2')
    parser.add_argument('--with-uploader', action='store_true')
    parser.add_argument('--with-capture-key', action='store_true')
    args = parser.parse_args()
    try:
        return prepare(ROOT, archive=args.archive, offline=args.offline, check=args.check,
                       uploader=args.with_uploader, capture_key=args.with_capture_key)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'Resource setup failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
