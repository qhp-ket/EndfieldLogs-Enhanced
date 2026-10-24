"""Use either the active venv or the legacy bundled dependencies consistently."""
from __future__ import annotations
import os
import sys
from pathlib import Path


def configure_paths(root: Path, *, isolated: bool | None = None):
    if isolated is None:
        isolated = sys.prefix != sys.base_prefix
    internal = root / '_internal'
    groups = [internal / 'python_deps/gui', internal / 'python_deps/common']
    paths = [internal / 'src', internal / 'packages/parser_core', internal / 'packages/uploader_core']
    if not isolated:
        for group in groups:
            paths.extend([group, group / 'win32', group / 'win32/lib'])
    sys.path[:0] = [str(p) for p in paths if p.is_dir() and str(p) not in sys.path]
    handles = []
    if hasattr(os, 'add_dll_directory'):
        native = ([Path(sys.prefix) / 'Lib/site-packages/pywin32_system32'] if isolated else
                  [g / 'pywin32_system32' for g in groups])
        native.append(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/Npcap')
        for path in native:
            if path.is_dir():
                handles.append(os.add_dll_directory(str(path)))
    return handles
