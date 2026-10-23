"""Version and release workflow: version [NEW], build, verify ZIP.

Build runs the ordinary application/parser/uploader regressions, creates the
canonical artifact, then verifies a fresh extraction using its own Python.
Never publishes to GitHub, installs drivers or starts capture/upload.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / '_internal/src/endfield_pcap/_version.py'
SEMVER = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?')


def identity():
    data = runpy.run_path(str(VERSION_FILE))
    return data['APP_NAME'], data['__version__']


def set_version(value):
    if not SEMVER.fullmatch(value):
        raise ValueError('Use SemVer, e.g. 0.1.0-dev.2 or 0.1.0 (no leading v)')
    text = VERSION_FILE.read_text(encoding='utf8')
    text, count = re.subn(r"^__version__ = '[^']+'$", f"__version__ = '{value}'", text, flags=re.M)
    if count != 1:
        raise ValueError('Version source must have exactly one __version__ assignment')
    VERSION_FILE.write_text(text, encoding='utf8', newline='\n')


def run(script, *args):
    command = [sys.executable, '-B', str(ROOT / '_development' / script), *map(str, args)]
    print('Running: ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    version = commands.add_parser('version')
    version.add_argument('new_version', nargs='?')
    build = commands.add_parser('build')
    build.add_argument('--skip-tests', action='store_true', help='Only when the same sources already passed all regressions')
    build.add_argument('--stage-only', action='store_true', help='Stop before ZIP/relocation verification')
    verify = commands.add_parser('verify')
    verify.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'version':
            if args.new_version:
                set_version(args.new_version)
            name, value = identity()
            print(f'{name} {value}\nArtifact: {name}-{value}-windows-x64.zip')
        elif args.command == 'verify':
            run('tools/verify_portable_zip.py', args.archive.resolve())
        else:
            name, value = identity()
            artifact = ROOT / '_releases' / f'{name}-{value}-windows-x64'
            if artifact.exists() or Path(str(artifact) + '.zip').exists():
                raise ValueError('Version already built; bump version rather than overwrite a tested artifact')
            if not args.skip_tests:
                for suite in ('live', 'parser_core', 'uploader_core'):
                    run('run_tests.py', suite)
            run('tools/build_portable.py', '--stage-only')
            if not args.stage_only:
                run('tools/build_portable.py', '--zip-stage', artifact)
                run('tools/verify_portable_zip.py', Path(str(artifact) + '.zip'))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Release failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
