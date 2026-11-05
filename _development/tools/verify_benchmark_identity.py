"""Check loaded desktop modules before accepting local benchmark results."""
import hashlib
from pathlib import Path


def desktop_runtime_directory(desktop):
    desktop = Path(desktop).resolve()
    nested = desktop.parent / '_internal/app'
    return nested if (nested / 'EndfieldLogs-Enhanced.dll').is_file() else desktop.parent


def verify_desktop_identity(result, desktop):
    """Reject a different executable or loaded module, even if its results look valid."""
    desktop = desktop.resolve()
    runtime = desktop_runtime_directory(desktop)
    expected = {'process_path': desktop,
                'core_assembly_path': runtime / 'EndfieldLogs.Core.dll',
                'runtime_assembly_path': runtime / 'EndfieldLogs.Runtime.dll',
                'desktop_assembly_path': runtime / 'EndfieldLogs-Enhanced.dll'}
    verified = {}
    for field, path in expected.items():
        actual = result.get(field)
        if not isinstance(actual, str) or Path(actual).resolve() != path:
            raise RuntimeError(f'Benchmark identity mismatch ({field}): {actual!r}; expected {path}. '
                               'Rebuild the requested executable with assembly identity diagnostics.')
        verified[field] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result['verified_desktop_identity'] = verified
