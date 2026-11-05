"""A valid report from another build must not be accepted as the requested build."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from verify_benchmark_identity import verify_desktop_identity


def identity(folder, nested=False):
    names = {'process_path': 'EndfieldLogs-Enhanced.exe',
             'core_assembly_path': 'EndfieldLogs.Core.dll',
             'runtime_assembly_path': 'EndfieldLogs.Runtime.dll',
             'desktop_assembly_path': 'EndfieldLogs-Enhanced.dll'}
    result = {}
    for field, name in names.items():
        path = (folder / '_internal/app' if nested and field != 'process_path' else folder) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        result[field] = str(path)
    return result


class BenchmarkIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_records_hashes_of_flat_and_nested_requested_builds(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                folder = self.root / str(nested)
                result = identity(folder, nested)
                verify_desktop_identity(result, folder / 'EndfieldLogs-Enhanced.exe')
                verified = result['verified_desktop_identity']
                self.assertEqual(len(verified), 4)
                self.assertEqual(verified['core_assembly_path']['sha256'], hashlib.sha256(b'EndfieldLogs.Core.dll').hexdigest())

    def test_rejects_old_executable_and_mixed_loaded_assemblies(self):
        for nested in (False, True):
            for wrong_field in ('process_path', 'core_assembly_path', 'runtime_assembly_path', 'desktop_assembly_path'):
                with self.subTest(nested=nested, field=wrong_field):
                    folder = self.root / f'current-{nested}-{wrong_field}'
                    result = identity(folder, nested)
                    old = identity(self.root / f'old-{nested}-{wrong_field}', nested)
                    result[wrong_field] = old[wrong_field]
                    with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                        verify_desktop_identity(result, folder / 'EndfieldLogs-Enhanced.exe')
                    self.assertNotIn('verified_desktop_identity', result)

    def test_rejects_old_probe_without_identity(self):
        with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
            verify_desktop_identity({'passed': True}, self.root / 'EndfieldLogs-Enhanced.exe')


if __name__ == '__main__':
    unittest.main()
