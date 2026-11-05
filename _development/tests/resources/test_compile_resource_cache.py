"""固定格式和原始资源绑定；运行端完整值一致性另由 C# 检查。"""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import struct
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[2] / 'tools/compile_resource_cache.py'
SPEC = importlib.util.spec_from_file_location('compile_resource_cache', TOOL)
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


class ResourceCacheTests(unittest.TestCase):
    def test_fixed_encoding_and_source_payload_hashes(self):
        source = gzip.compress(b'[true,false,null,1,-1,0,2.5,"a",{"n":1}]', mtime=0)
        result = compiler.compile_gzip(source)
        payload = (struct.pack('<ii', 2, 1) + b'a\0' + struct.pack('<i', 1) + b'n\0'
                   + struct.pack('<iii', 1, 1, 1) + b'\7' + struct.pack('<i', 9)
                   + b'\2\1\0\3\2\3\1\3\0\5' + struct.pack('<d', 2.5)
                   + b'\6' + struct.pack('<i', 0) + b'\10' + struct.pack('<i', 0) + b'\3\2')
        self.assertEqual(result, b'EGLRC002' + hashlib.sha256(source).digest() + hashlib.sha256(payload).digest() + payload)
        self.assertEqual(compiler.compile_gzip(source), result)

    def test_surrogate_units_and_nonfinite_values_do_not_use_text_replacement(self):
        source = gzip.compress(b'["\\ud800\\u0000\\ud83d\\ude00",-0.0,NaN,Infinity,-Infinity,1267650600228229401496703205376]', mtime=0)
        payload = compiler.compile_gzip(source)[72:]
        self.assertIn(b'\x00\xd8\x00\x00\x3d\xd8\x00\xde', payload)
        self.assertIn(b'\5' + struct.pack('<d', -0.0), payload)
        self.assertIn(b'\5' + struct.pack('<d', float('inf')), payload)
        self.assertIn(b'\4' + struct.pack('<i', 13) + (1 << 100).to_bytes(13, 'little'), payload)

    def test_derivative_creation_never_overwrites_source_or_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'resource.json.gz'
            source.write_bytes(gzip.compress(b'{}', mtime=0))
            original = source.read_bytes()
            output = Path(str(source) + '.egr')
            compiler.write_cache(source, output)
            with self.assertRaises(FileExistsError):
                compiler.write_cache(source, output)
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
