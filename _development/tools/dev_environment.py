"""Dependency probe usable before pip is installed; all setup writes are external.

Invoked in a subprocess so native import failures cannot hang the setup shell.
No GUI, capture, upload, game DLL, real key or personal configuration is opened.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from importlib import import_module, metadata
import io
import json
from pathlib import Path
import platform
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MODULES = {'PySide6': ('PySide6.QtWidgets', 'PySide6.QtMultimedia'),
           'PySide6-Fluent-Widgets': ('qfluentwidgets',), 'pycryptodome': ('Crypto.PublicKey.RSA',),
           'dpkt': ('dpkt',), 'protobuf': ('google.protobuf',), 'pydantic': ('pydantic',),
           'httpx': ('httpx',), 'websockets': ('websockets',), 'numpy': ('numpy',),
           'psutil': ('psutil',), 'pywin32': ('win32api',), 'pytest': ('pytest',), 'packaging': ('packaging',)}


def probe(root, *, isolated=False):
    sys.path.insert(0, str(root / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    handles = configure_paths(root, isolated=isolated)
    compatible = struct.calcsize('P') == 8 and sys.platform == 'win32'
    missing, locations = [], {}
    errors = {}
    if compatible:
        with redirect_stdout(io.StringIO()):
            for distribution, modules in MODULES.items():
                try:
                    for name in modules:
                        import_module(name)
                    try:
                        dist = metadata.distribution(distribution)
                        locations[distribution] = str(Path(dist.locate_file('')).resolve())
                    except metadata.PackageNotFoundError:
                        pass  # Importability, not package metadata or version, determines readiness.
                except Exception as exc:
                    missing.append(distribution)
                    errors[distribution] = f'{type(exc).__name__}: {exc}'
    manifest = root / '_internal/data/resource-manifest.json'
    capabilities = {'sdl3': (root / '_internal/native/SDL3.dll').is_file()}
    try:
        multimedia = import_module('PySide6.QtMultimedia')
        capabilities['window_capture'] = hasattr(multimedia,'QWindowCapture')
    except ImportError:
        capabilities['window_capture'] = False
    return dict(ready=compatible and not missing,
                compatible=compatible, executable=sys.executable, python=platform.python_version(),
                isolated=isolated, missing=missing, import_errors=errors,
                optional_services=capabilities,
                resource_manifest_present=manifest.exists(),
                capture_key_present=(root / '_internal/secrets/client_privkey.pem').is_file(),
                npcap_present=(Path(__import__('os').environ.get('SystemRoot', 'C:/Windows')) / 'System32/Npcap/wpcap.dll').is_file(),
                package_locations=locations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--isolated', action='store_true')
    args = parser.parse_args()
    try:
        result = probe(args.root.resolve(), isolated=args.isolated)
    except Exception as exc:
        result = dict(ready=False, compatible=False, error=f'{type(exc).__name__}: {exc}')
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
