"""Extract a release afresh and test it without a system Python on PATH."""
import argparse
import hashlib
import json
import os
import runpy
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


parser = argparse.ArgumentParser()
parser.add_argument('archive', type=Path)
parser.add_argument('--trace', type=Path, help='Optional trace for offline smoke; default is a synthetic fixture')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
archive_path = args.archive.resolve()
verification = ROOT / '_development/verification'
verification.mkdir(parents=True, exist_ok=True)
if args.output:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
else:
    output = Path(tempfile.mkdtemp(prefix='portable 中文路径 ', dir=verification))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


expected = archive_path.with_suffix('.zip.sha256').read_text(encoding='ascii').split()[0]
require(sha(archive_path) == expected, 'ZIP SHA-256 mismatch')
with zipfile.ZipFile(archive_path) as archive:
    for info in archive.infolist():
        relative = PurePosixPath(info.filename)
        if relative.is_absolute() or '..' in relative.parts or '\\' in info.filename:
            raise ValueError('Unsafe archive member')
    print(f'Extracting {len(archive.infolist())} files to a new path', flush=True)
    archive.extractall(output)

folders = [p for p in output.iterdir() if p.is_dir()]
require(len(folders) == 1, 'Verification failed: len(folders) == 1')
app_root = folders[0]
manifest = json.loads((app_root / 'BUILD-MANIFEST.json').read_text(encoding='utf8'))
component = manifest.get('component', 'application')
identity=runpy.run_path(str(app_root/'_internal/src/endfield_pcap/_version.py')) if component=='application' else {}
app_name = identity.get('APP_NAME') if component == 'application' else 'EndfieldLogsUploader'
package_name=identity.get('APP_PACKAGE_NAME',app_name) if component=='application' else app_name
require(component in {'application', 'official_uploader'}, "Verification failed: component in {'application', 'official_uploader'}")
require(manifest['application']['name'] == app_name, "Verification failed: manifest['application']['name'] == app_name")
require(manifest['application']['artifact'] == app_root.name == archive_path.stem, "Verification failed: manifest['application']['artifact'] == app_root.name == archive_path.stem")
require(app_root.name == f"{package_name}-{manifest['application']['version']}-windows-x64", 'Verification failed: app_root.name == f"{package_name}-{manifest[\'application\'][\'version\']}-windows-x64"')
actual = {p.relative_to(app_root).as_posix() for p in app_root.rglob('*') if p.is_file()}
require(actual == set(manifest['files']) | {'BUILD-MANIFEST.json'}, "Verification failed: actual == set(manifest['files']) | {'BUILD-MANIFEST.json'}")
for relative, entry in manifest['files'].items():
    path = app_root / relative
    require(path.stat().st_size == entry['size'] and sha(path) == entry['sha256'], 'Manifest hash mismatch: ' + relative)
require(not (app_root / '.dev-gui').exists(), "Verification failed: not (app_root / '.dev-gui').exists()")
require(not (app_root / '_development').exists(), "Verification failed: not (app_root / '_development').exists()")
require(not any('/tests/' in p or '/__pycache__/' in p for p in actual), "Verification failed: not any('/tests/' in p or '/__pycache__/' in p for p in actual)")
print('Extracted manifest and privacy boundary verified', flush=True)

if component == 'official_uploader':
    from prepare_resources import acquire_archive
    from portable_uploader import PREFIX
    resources = json.loads((ROOT / '_internal/data/resource-manifest.json').read_text(encoding='utf8'))
    original_archive = acquire_archive(ROOT, resources)
    with zipfile.ZipFile(original_archive) as original:
        members = [i for i in original.infolist() if not i.is_dir() and i.filename.startswith(PREFIX)]
        originals = {'Uploader/' + i.filename[len(PREFIX):]: i for i in members}
        require({p for p in actual if p.startswith('Uploader/')} == originals.keys(), "Verification failed: {p for p in actual if p.startswith('Uploader/')} == originals.keys()")
        for relative, member in originals.items():
            require((app_root / relative).read_bytes() == original.read(member), relative)
    executable = app_root / 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe'
    require(sha(executable) == manifest['official_uploader']['executable_sha256'], "Verification failed: sha(executable) == manifest['official_uploader']['executable_sha256']")
    require(not (app_root / '_internal').exists(), "Verification failed: not (app_root / '_internal').exists()")
    require(not any(p.endswith(('.key', '.pfx', '.p12')) or '/secrets/' in p for p in actual), "Verification failed: not any(p.endswith(('.key', '.pfx', '.p12')) or '/secrets/' in p for p in actual)")
    result = dict(archive=archive_path.name, component=component,
                  bytes=archive_path.stat().st_size, sha256=expected,
                  uncompressed_bytes=sum((app_root / p).stat().st_size for p in actual),
                  manifest_files=len(manifest['files']), official_executable_hash_verified=True,
                  official_archive_files_verified=len(originals),
                  main_application_runtime_included=False)
    (output / 'portable-zip-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0)

require(not (app_root / 'Uploader').exists(), 'Uploader must be distributed separately')

env = dict(os.environ)
for key in list(env):
    if key.upper().startswith(('PYTHON', 'ENDFIELD_')):
        env.pop(key)
env['PATH'] = str(Path(env.get('SystemRoot', 'C:/Windows')) / 'System32')
env['PYTHONHOME'] = str(output / 'nonexistent-python-home')
env['PYTHONPATH'] = str(output / 'nonexistent-site-packages')
env['ENDFIELD_GUI_NO_PAUSE'] = '1'
env['QT_QPA_PLATFORM'] = os.environ.get('ENDFIELD_UI_TEST_PLATFORM', 'offscreen')
env['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-dev-shm-usage'
cmd = Path(env.get('SystemRoot', 'C:/Windows')) / 'System32/cmd.exe'
check = subprocess.run([str(cmd), '/d', '/c', 'Start-GUI.cmd', '--check'], cwd=app_root,
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
(output / 'cmd-check.log').write_bytes(check.stdout)
require(check.returncode == 0, check.stdout.decode('utf8', errors='replace')[-3000:])
config = json.loads((app_root / '.dev-gui/settings.json').read_text(encoding='utf8'))
for key in ('rsa_key_txt', 'name_index_path', 'log_dir', 'debug_dir'):
    require((app_root / config['service'][key]).resolve().is_relative_to(app_root),
            'Application-owned path escaped package: ' + key)


def run_smoke(root, destination):
    python = root / '_internal/python/python.exe'
    command = [str(python), '-B', str(ROOT / '_development/tools/smoke_portable.py'),
               '--root', str(root), '--output', str(destination), '--use-app-profile',
               '--trace', str(args.trace.resolve() if args.trace else
                              ROOT / '_internal/packages/parser_core/tests/fixtures/synthetic_fire_corrosion.log')]
    result = subprocess.run(command, cwd=output, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180)
    destination.with_suffix('.log').write_bytes(result.stdout)
    require(result.returncode == 0, result.stdout.decode('utf8', errors='replace')[-3000:])
    return result


smoke = run_smoke(app_root, output / 'smoke')
previous_config = json.loads((app_root / '.dev-gui/settings.json').read_text(encoding='utf8'))
marker = app_root / '.dev-gui/migration-marker.txt'
marker.write_text('portable profile', encoding='utf8')
old_root = app_root
moved_parent = output / '运行后移动 目录'
moved_parent.mkdir()
app_root = app_root.rename(moved_parent / app_root.name)
check_moved = subprocess.run([str(cmd), '/d', '/c', 'Start-GUI.cmd', '--check'], cwd=app_root,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
(output / 'cmd-check-moved.log').write_bytes(check_moved.stdout)
require(check_moved.returncode == 0, check_moved.stdout.decode('utf8', errors='replace')[-3000:])
require(not old_root.exists(), 'Original portable directory still exists')
require((app_root / '.dev-gui/migration-marker.txt').read_text(encoding='utf8') == 'portable profile',
        'Profile contents changed during migration')
moved_config = json.loads((app_root / '.dev-gui/settings.json').read_text(encoding='utf8'))
require(moved_config['service']['ws_browser_token'] == previous_config['service']['ws_browser_token'],
        'Persisted settings were reset during migration')
require(moved_config['service']['dll_dir'] == previous_config['service']['dll_dir'],
        'External game path changed during migration')
for key in ('rsa_key_txt', 'name_index_path', 'log_dir', 'debug_dir'):
    value = moved_config['service'][key]
    require(not Path(value).is_absolute() and (app_root / value).resolve().is_relative_to(app_root),
            'Moved package retained an absolute application path: ' + key)
smoke_moved = run_smoke(app_root, output / 'smoke-moved')
result = dict(archive=archive_path.name, bytes=archive_path.stat().st_size, sha256=expected,
              uncompressed_bytes=sum((app_root / p).stat().st_size for p in actual),
              manifest_files=len(manifest['files']), archive_has_personal_profile=False,
              cmd_check_exit=check.returncode, smoke_exit=smoke.returncode,
              used_directory_relocation_verified=True, relocated_gui_exit=smoke_moved.returncode,
              relocation_with_spaces_and_chinese=(' ' in str(output) and any(ord(c) > 127 for c in str(output))),
              uploader_included=False, system_python_on_path=False,
              smoke=json.loads((output / 'smoke/result.json').read_text(encoding='utf8')))
(output / 'portable-zip-result.json').write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
