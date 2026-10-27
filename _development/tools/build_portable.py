"""Build an isolated Windows source-GUI distribution from tested dependencies.

Use --stage-only, verify that tree, then --zip-stage PATH. Never copy a user's
profile, never collect arbitrary site-packages, and never build an application EXE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import platform
import runpy
import shutil
import subprocess
import sys
import sysconfig
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / '_releases'
IDENTITY = runpy.run_path(str(ROOT / '_internal/src/endfield_pcap/_version.py'))
APP_NAME, VERSION = IDENTITY['APP_NAME'], IDENTITY['__version__']
APP_PACKAGE_NAME = IDENTITY['APP_PACKAGE_NAME']
RELEASE_NAME = f'{APP_PACKAGE_NAME}-{VERSION}-windows-x64'
UPLOADER_NAME = 'EndfieldLogsUploader'
UPLOADER_VERSION = '3.0.12'
UPLOADER_RELEASE_NAME = f'{UPLOADER_NAME}-{UPLOADER_VERSION}-windows-x64'
sys.dont_write_bytecode = True
GUI_DEPS = ROOT / '_internal/python_deps/gui'
COMMON_DEPS = ROOT / '_internal/python_deps/common'
if sys.prefix == sys.base_prefix:
    sys.path[:0] = [str(GUI_DEPS), str(COMMON_DEPS)]
from packaging.requirements import Requirement
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable_dependencies import dependency_file_allowed, qt_runtime_files
from portable_uploader import extract_uploader

CAPTURE_KEY_SHA256 = 'b83257fadefe901f708386da11ffcde0eb0dee6450a6b56fc1b85e197cab1b56'
OFFICIAL_UPLOADER_SHA256 = 'd37373181c92273d379c72bac353f7057373e84bccbc08fadca721270c543179'
ROOT_REQUIREMENTS = ('PySide6-Fluent-Widgets', 'dpkt', 'pycryptodome', 'protobuf',
                     'websockets', 'psutil', 'pydantic', 'numpy', 'httpx')
SKIP_DIRS = {'__pycache__', 'test', 'tests', 'SelfTest', '.git', '.pytest_cache'}
PRIVATE_NAMES = {'.env', 'credentials.json', 'session.json', 'settings.json', 'uploader_settings.json',
                 'rsa_keys.txt', 'embedded_keys.py'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def excluded(relative):
    path = PurePosixPath(str(relative).replace('\\', '/'))
    return (bool(set(path.parts) & SKIP_DIRS) or any(p.endswith('.egg-info') for p in path.parts)
            or path.suffix.lower() in {'.pyc', '.pyo', '.log', '.ndjson', '.pcap', '.pcapng'}
            or path.name.lower().endswith('.input.jsonl')
            or path.name.lower() in PRIVATE_NAMES or path.name.lower().startswith('.env.'))


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if digest(source) != digest(target):
            raise ValueError(f'Conflicting distribution file: {target.name}')
        return
    shutil.copy2(source, target)


def copy_tree(source, target):
    if not source.is_dir():
        raise FileNotFoundError(source)
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if path.is_file() and not excluded(relative):
            if path.is_symlink():
                raise ValueError(f'Symlinks are not supported: {relative}')
            copy_file(path, target / relative)


def dependencies():
    resolved, pending = {}, list(ROOT_REQUIREMENTS)
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        name = requirement.name.lower().replace('_', '-')
        if name == 'pyside6':
            # PySide6 is a convenience metapackage including browser/PDF wheels.
            # The native application uses bindings from these two distributions.
            pending.extend(('PySide6-Essentials'+str(requirement.specifier),
                            'PySide6-Addons'+str(requirement.specifier)))
            continue
        dist = resolved.get(name) or metadata.distribution(requirement.name)
        if requirement.specifier and not requirement.specifier.contains(dist.version):
            raise ValueError(f'Installed dependency does not satisfy {requirement}: {dist.version}')
        if name in resolved:
            continue
        resolved[name] = dist
        pending.extend(dist.requires or [])
    validate_dependency_versions(resolved)
    return resolved


def validate_dependency_versions(resolved):
    locked = {}
    for line in (ROOT / '_development/portable/runtime-requirements.txt').read_text(encoding='utf8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        req = Requirement(line)
        specs = list(req.specifier)
        if req.url or req.marker or req.extras or len(specs) != 1 or specs[0].operator != '==' or '*' in specs[0].version:
            raise ValueError('Release dependencies require exact pins: ' + line)
        name = req.name.lower().replace('_', '-')
        if name in locked:
            raise ValueError('Duplicate release dependency: ' + name)
        locked[name] = specs[0].version
    actual = {name: dist.version for name, dist in resolved.items()}
    if actual != locked:
        differences = [f'{name}: installed={actual.get(name, "missing")}, locked={locked.get(name, "missing")}'
                       for name in sorted(actual.keys() | locked.keys()) if actual.get(name) != locked.get(name)]
        raise ValueError('Release dependency lock mismatch: ' + '; '.join(differences))


def copy_dependencies(stage):
    versions = {}
    resolved = dependencies()
    qt_files = qt_runtime_files(Path(resolved['pyside6-essentials'].locate_file('PySide6')))
    for name, dist in sorted(resolved.items()):
        source_root = Path(dist.locate_file('')).resolve()
        # User-installed packages (e.g. numpy, psutil, websockets) are resolved
        # explicitly through RECORD; no unrelated user files are collected.
        group = 'gui' if source_root == GUI_DEPS.resolve() else 'common'
        target = stage / '_internal/python_deps' / group
        if not dist.files:
            raise ValueError(f'Missing installed RECORD for {name}')
        print(f'Dependency: {name} {dist.version}', flush=True)
        for relative in dist.files:
            source = Path(dist.locate_file(relative)).resolve()
            if not source.is_relative_to(source_root):
                continue  # Scripts outside site-packages are not runtime inputs.
            relative = source.relative_to(source_root)
            if source.is_file() and not excluded(relative) and dependency_file_allowed(relative, qt_files):
                copy_file(source, target / relative)
        versions[name] = dist.version
    return versions


def copy_python(stage):
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 14) or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ValueError('Build with the tested Windows x64 Python 3.14 interpreter')
    home = Path(sys.base_prefix)
    target = stage / '_internal/python'
    target.mkdir(parents=True)
    for name in ('python.exe', 'pythonw.exe', 'python314.dll', 'python3.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        copy_file(home / name, target / name)
    for path in (home / 'DLLs').iterdir():
        if path.is_file() and path.suffix.lower() in {'.pyd', '.dll'} and not path.name.startswith(('_test', 'xx')):
            copy_file(path, target / 'DLLs' / path.name)
    # Include readable standard-library sources, with no installed user packages.
    library = Path(sysconfig.get_path('stdlib'))
    with zipfile.ZipFile(target / 'python314.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(library.rglob('*.py')):
            relative = path.relative_to(library)
            if 'site-packages' not in relative.parts and not excluded(relative):
                archive.write(path, relative.as_posix())
    (target / 'python314._pth').write_text('python314.zip\n.\nDLLs\n', encoding='ascii')


def validate_tree(stage, component='application'):
    """Fail closed on personal state and extra secrets before creating a ZIP."""
    allowed_roots = {'README.zh-CN.md', 'BUILD-MANIFEST.json', 'licenses'}
    if component == 'application':
        allowed_roots |= {'Start-GUI.cmd', 'launch_gui.py', '_internal'}
    elif component == 'official_uploader':
        allowed_roots.add('Uploader')
    else:
        raise ValueError('Unknown portable component: ' + component)
    files = []
    for path in sorted(stage.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(stage)
        if relative.parts[0] not in allowed_roots or excluded(relative):
            raise ValueError(f'Unexpected/private build file: {relative}')
        if '.dev-gui' in relative.parts or 'pytest' in relative.parts or '_pytest' in relative.parts:
            raise ValueError(f'User/test files cannot be distributed: {relative}')
        lowered = relative.as_posix().lower()
        if 'secrets' in relative.parts or path.suffix.lower() in {'.pem', '.key', '.pfx', '.p12'}:
            if lowered == '_internal/secrets/client_privkey.pem':
                if digest(path) != CAPTURE_KEY_SHA256:
                    raise ValueError('Capture key differs from the public official release')
            elif lowered.endswith('/certifi/cacert.pem'):
                pass  # Public certificate trust store, never a personal key.
            else:
                raise ValueError(f'Unapproved secret: {relative}')
        files.append(path)
    return files


def write_manifest(stage, versions, component='application'):
    files = [p for p in validate_tree(stage, component) if p.name != 'BUILD-MANIFEST.json']
    source_commit = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=ROOT,
                                   capture_output=True, text=True, check=False).stdout.strip() or None
    source_dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT,
                                       capture_output=True, text=True, check=False).stdout.strip())
    app_name, app_version = ((APP_NAME, VERSION) if component == 'application' else
                             (UPLOADER_NAME, UPLOADER_VERSION))
    manifest = dict(schema_version=2, component=component, built_at=datetime.now(timezone.utc).isoformat(),
                    application=dict(name=app_name, version=app_version, artifact=stage.name), source_commit=source_commit,
                    source_dirty=source_dirty,
                    python=platform.python_version() if component == 'application' else None,
                    platform='Windows x64', dependencies=versions,
                    packaging=dict(dependency_policy='windows-runtime-closure-v1',
                                   uncompressed_bytes=sum(p.stat().st_size for p in files)),
                    files={p.relative_to(stage).as_posix(): dict(size=p.stat().st_size, sha256=digest(p)) for p in files})
    if component == 'application':
        manifest['capture_key'] = 'Unmodified shared runtime resource from official 3.0.12; not an account credential'
    else:
        manifest['official_uploader'] = dict(version=UPLOADER_VERSION, executable_sha256=OFFICIAL_UPLOADER_SHA256,
                                            resource_packaging='official-archive-byte-exact-v1')
        manifest['packaging']['dependency_policy'] = 'official-frozen-runtime-unchanged'
    (stage / 'BUILD-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')


def copy_runtime_data(stage):
    """Use the reviewed runtime inventory, never a recursive raw-data copy."""
    manifest_path = ROOT / '_internal/data/resource-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    if manifest.get('schema_version') != 2:
        raise ValueError('Build the compact runtime projection before packaging')
    for row in manifest['files']:
        relative = PurePosixPath(row['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in row['path'] or relative.parts[0] not in {'data', 'jsondata'}:
            raise ValueError('Unsafe runtime-data inventory member')
        source = ROOT / '_internal' / row['path']
        if source.stat().st_size != row['bytes'] or digest(source) != row['sha256']:
            raise ValueError('Changed runtime-data member: ' + row['path'])
        copy_file(source, stage / '_internal' / row['path'])
    copy_file(manifest_path, stage / '_internal/data/resource-manifest.json')
    # The source restore ZIP is deliberately not duplicated in an extracted app.


def stage_release(name=None):
    name = name or RELEASE_NAME
    if name != RELEASE_NAME:
        raise ValueError(f'Release name must match the version file: {RELEASE_NAME}')
    dependencies()
    from prepare_resources import prepare
    if prepare(ROOT, check=True):
        raise ValueError('Prepare the bundled runtime data before packaging')
    from audit_runtime_data import verify
    verify()
    key = ROOT / '_internal/secrets/client_privkey.pem'
    if not key.is_file() or digest(key) != CAPTURE_KEY_SHA256:
        raise ValueError('Prepare the verified official capture key before packaging')
    stage = RELEASES / name
    stage.mkdir(parents=True, exist_ok=False)
    for name in ('Start-GUI.cmd', 'launch_gui.py'):
        copy_file(ROOT / name, stage / name)
    copy_file(ROOT / '_development/portable/README.zh-CN.md', stage / 'README.zh-CN.md')
    copy_tree(ROOT / '_development/portable/licenses', stage / 'licenses')
    copy_file(ROOT / 'LICENSE', stage / 'licenses/EndfieldLogs-LICENSE.txt')
    copy_file(ROOT / 'THIRD_PARTY_NOTICES.md', stage / 'licenses/EndfieldLogs-THIRD_PARTY_NOTICES.md')
    copy_file(ROOT / '_development/docs/licensing.md', stage / 'licenses/EndfieldLogs-LICENSING.zh-CN.md')
    for folder in ('src', 'packages'):
        print(f'Runtime resources: {folder}', flush=True)
        copy_tree(ROOT / '_internal' / folder, stage / '_internal' / folder)
    copy_runtime_data(stage)
    copy_tree(ROOT / '_internal/data/ui/characters', stage / '_internal/data/ui/characters')
    from prepare_native import prepare_native
    prepare_native(ROOT,check=True)
    for name in ('SDL3.dll','SDL3-LICENSE.txt','manifest.json'):
        copy_file(ROOT / '_internal/native' / name,stage / '_internal/native' / name)
    if digest(key) != CAPTURE_KEY_SHA256:
        raise ValueError('Refusing to distribute a changed/private capture key')
    copy_file(key, stage / '_internal/secrets/client_privkey.pem')
    print('Python runtime', flush=True)
    copy_python(stage)
    versions = copy_dependencies(stage)
    write_manifest(stage, versions)
    print(f'STAGED: {stage}', flush=True)
    return stage


def stage_uploader(name=None):
    name = name or UPLOADER_RELEASE_NAME
    if name != UPLOADER_RELEASE_NAME:
        raise ValueError(f'Uploader release name must match its upstream version: {UPLOADER_RELEASE_NAME}')
    from prepare_resources import acquire_archive
    manifest = json.loads((ROOT / '_internal/data/resource-manifest.json').read_text(encoding='utf8'))
    archive = acquire_archive(ROOT, manifest)
    stage = RELEASES / name
    stage.mkdir(parents=True, exist_ok=False)
    stats = extract_uploader(archive, stage / 'Uploader')
    executable = stage / 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe'
    if not executable.is_file() or digest(executable) != OFFICIAL_UPLOADER_SHA256:
        raise ValueError('Official uploader executable differs from the pinned release')
    copy_file(ROOT / '_development/portable/README-uploader.zh-CN.md', stage / 'README.zh-CN.md')
    copy_tree(ROOT / '_development/portable/licenses', stage / 'licenses')
    write_manifest(stage, {}, component='official_uploader')
    print(f'Uploader: {stats}\nSTAGED: {stage}', flush=True)
    return stage


def zip_stage(stage):
    stage = stage.resolve()
    if stage.parent != RELEASES.resolve() or not (stage / 'BUILD-MANIFEST.json').is_file():
        raise ValueError('Only an existing build directly under _releases can be archived')
    manifest = json.loads((stage / 'BUILD-MANIFEST.json').read_text(encoding='utf8'))
    if manifest.get('source_dirty'):
        raise ValueError('Dirty development staging cannot be archived as a release ZIP')
    component = manifest.get('component', 'application')
    files = validate_tree(stage, component)
    actual = {p.relative_to(stage).as_posix() for p in files if p.name != 'BUILD-MANIFEST.json'}
    if actual != set(manifest['files']):
        raise ValueError('Build contents changed since staging')
    for p in files:
        if p.name != 'BUILD-MANIFEST.json' and digest(p) != manifest['files'][p.relative_to(stage).as_posix()]['sha256']:
            raise ValueError(f'Build file changed: {p.relative_to(stage)}')
    identity = manifest.get('application') or {}
    expected_name = APP_NAME if component == 'application' else UPLOADER_NAME
    expected_package = APP_PACKAGE_NAME if component == 'application' else UPLOADER_NAME
    if (identity.get('name') != expected_name or identity.get('artifact') != stage.name
            or stage.name != f"{expected_package}-{identity.get('version')}-windows-x64"):
        raise ValueError('Staged artifact identity does not match its canonical versioned name')
    output = RELEASES / f'{stage.name}.zip'
    # Exclusive creation avoids silently replacing an existing tested release.
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in files:
            archive.write(path, (Path(stage.name) / path.relative_to(stage)).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC verification failed')
    sha = digest(output)
    output.with_suffix('.zip.sha256').write_text(f'{sha}  {output.name}\n', encoding='ascii')
    print(f'ZIP: {output}\nUncompressed bytes: {sum(p.stat().st_size for p in files)}'
          f'\nZIP bytes: {output.stat().st_size}\nSHA256: {sha}', flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', help='Must match the canonical versioned artifact name')
    parser.add_argument('--component', choices=('application', 'uploader'), default='application')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--zip-stage', type=Path)
    args = parser.parse_args()
    if args.zip_stage:
        zip_stage(args.zip_stage)
    else:
        stage = stage_release(args.name) if args.component == 'application' else stage_uploader(args.name)
        if not args.stage_only:
            zip_stage(stage)
