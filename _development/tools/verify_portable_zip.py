"""Extract a release afresh and test it without a system Python on PATH."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
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
assert sha(archive_path) == expected
with zipfile.ZipFile(archive_path) as archive:
    for info in archive.infolist():
        relative = PurePosixPath(info.filename)
        if relative.is_absolute() or '..' in relative.parts or '\\' in info.filename:
            raise ValueError('Unsafe archive member')
    print(f'Extracting {len(archive.infolist())} files to a new path', flush=True)
    archive.extractall(output)

folders = [p for p in output.iterdir() if p.is_dir()]
assert len(folders) == 1
app_root = folders[0]
manifest = json.loads((app_root / 'BUILD-MANIFEST.json').read_text(encoding='utf8'))
assert manifest['application']['name'] == 'EndfieldLogs'
assert manifest['application']['artifact'] == app_root.name == archive_path.stem
assert app_root.name == f"EndfieldLogs-{manifest['application']['version']}-windows-x64"
actual = {p.relative_to(app_root).as_posix() for p in app_root.rglob('*') if p.is_file()}
assert actual == set(manifest['files']) | {'BUILD-MANIFEST.json'}
for relative, entry in manifest['files'].items():
    path = app_root / relative
    assert path.stat().st_size == entry['size'] and sha(path) == entry['sha256'], relative
assert not (app_root / '.dev-gui').exists()
assert not (app_root / '_development').exists()
assert not any('/tests/' in p or '/__pycache__/' in p for p in actual)
print('Extracted manifest and privacy boundary verified', flush=True)

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
assert check.returncode == 0, check.stdout.decode('utf8', errors='replace')[-3000:]
config = json.loads((app_root / '.dev-gui/settings.json').read_text(encoding='utf8'))
assert Path(config['service']['rsa_key_txt']).resolve().is_relative_to(app_root)
assert Path(config['service']['log_dir']).resolve().is_relative_to(app_root)

python = app_root / '_internal/python/python.exe'
command = [str(python), '-B', str(ROOT / '_development/tools/smoke_portable.py'),
           '--root', str(app_root), '--output', str(output / 'smoke'),
           '--trace', str(args.trace.resolve() if args.trace else ROOT / '_internal/packages/parser_core/tests/fixtures/synthetic_fire_corrosion.log')]
smoke = subprocess.run(command, cwd=output, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=180)
(output / 'smoke.log').write_bytes(smoke.stdout)
assert smoke.returncode == 0, smoke.stdout.decode('utf8', errors='replace')[-3000:]
result = dict(archive=archive_path.name, bytes=archive_path.stat().st_size, sha256=expected,
              manifest_files=len(manifest['files']), archive_has_personal_profile=False,
              cmd_check_exit=check.returncode, smoke_exit=smoke.returncode,
              relocation_with_spaces_and_chinese=True, system_python_on_path=False,
              smoke=json.loads((output / 'smoke/result.json').read_text(encoding='utf8')))
(output / 'portable-zip-result.json').write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
