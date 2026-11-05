"""将已校验的静态 gzip JSON 编译成原生客户端的只读派生缓存。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct

MAGIC = b'EGLRC002'


def compile_gzip(source: bytes) -> bytes:
    document = json.loads(gzip.decompress(source))
    strings: dict[str, int] = {}
    shapes: dict[tuple[str, ...], int] = {}

    def intern(value):
        if value not in strings:
            strings[value] = len(strings)

    def collect(value):
        if isinstance(value, dict):
            shape = tuple(value)
            if shape not in shapes:
                shapes[shape] = len(shapes)
            for key, child in value.items():
                intern(key)
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str):
            intern(value)

    collect(document)
    buffer = io.BytesIO()

    def i32(value):
        buffer.write(struct.pack('<i', value))

    i32(len(strings))
    for value in strings:
        # Preserve UTF-16 code units, including lone surrogates accepted by JSON.
        encoded = value.encode('utf-16-le', errors='surrogatepass')
        i32(len(encoded) // 2)
        buffer.write(encoded)
    i32(len(shapes))
    for shape in shapes:
        i32(len(shape))
        for name in shape:
            i32(strings[name])

    def visit(value):
        if value is None:
            buffer.write(b'\0')
        elif value is False:
            buffer.write(b'\1')
        elif value is True:
            buffer.write(b'\2')
        elif isinstance(value, int):
            if -(1 << 63) <= value < (1 << 63):
                buffer.write(b'\3')
                number = (value << 1) ^ (value >> 63)
                while number >= 128:
                    buffer.write(bytes([(number & 127) | 128]))
                    number >>= 7
                buffer.write(bytes([number]))
            else:
                buffer.write(b'\4')
                encoded = value.to_bytes((value.bit_length() + 8) // 8, 'little', signed=True)
                i32(len(encoded))
                buffer.write(encoded)
        elif isinstance(value, float):
            buffer.write(b'\5' + struct.pack('<d', value))
        elif isinstance(value, str):
            buffer.write(b'\6')
            i32(strings[value])
        elif isinstance(value, list):
            buffer.write(b'\7')
            i32(len(value))
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            buffer.write(b'\10')
            i32(shapes[tuple(value)])
            for child in value.values():
                visit(child)
        else:
            raise TypeError(type(value))

    visit(document)
    payload = buffer.getvalue()
    return MAGIC + hashlib.sha256(source).digest() + hashlib.sha256(payload).digest() + payload


def write_cache(source: Path, destination: Path) -> None:
    compiled = compile_gzip(source.read_bytes())
    with destination.open('xb') as stream:
        stream.write(compiled)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    write_cache(args.source, args.destination)


if __name__ == '__main__':
    main()
