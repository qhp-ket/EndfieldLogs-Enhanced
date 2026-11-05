"""Generate JSON-boundary str/repr fixtures with the fixed CPython reference version."""
from pathlib import Path
import argparse
import json
import random
import struct
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[3]
                        / '_internal/dotnet/Specs/Fixtures/python-display.json')
    args = parser.parse_args()
    if sys.version_info[:3] != (3, 14, 2):
        raise SystemExit('Use the fixed CPython 3.14.2 reference to regenerate fixtures.')
    cases = []

    def add(value):
        text = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
        # Match the actual JSON decoder, including paired UTF-16 escapes.
        value = json.loads(text)
        for mode in ('str', 'repr'):
            expected = (str(value) if mode == 'str' else repr(value)).encode('utf-16-be', 'surrogatepass').hex()
            cases.append(dict(name=f'python-display/{len(cases)}', input=text, display=mode, expected=expected))

    for value in (None, True, False, 0, -1, 2**128, {}, [], '', '合成', "'", '"', "'\"", '\\',
                  {'a': [None, True, 1.0, '合成'], "'": {'b': 1}}, '\ud800', '\udc00', '\ud800\udc00'):
        add(value)
    for value in (0.0, -0.0, 1.0, -1.0, float('nan'), float('inf'), -float('inf'),
                  1e-4, 1e-5, 1e15, 1e16, 1e23, 1.7976931348623157e308, 5e-324):
        add(value)
    for exponent in (-324, -308, -10, -5, -4, -1, 0, 1, 15, 16, 20, 23, 100, 307, 308):
        for base in (1.0, 1.5, 9.999999999999998):
            add(base * 10.0**exponent)
    for number in (*range(256), 0x378, 0x61c, 0x1680, 0x2000, 0x2028, 0x2029, 0x202f,
                   0x2066, 0x2069, 0x3000, 0xd800, 0xdc00, 0xe000, 0xffff, 0x10000,
                   0x1f63a, 0x10ffff):
        add(chr(number))
        add({'k'+chr(number): [chr(number), 1.0]})
    rng = random.Random(635271)
    for index in range(1024):
        number = struct.unpack('>d', rng.getrandbits(64).to_bytes(8))[0]
        add(number)
    for index in range(128):
        add(''.join(chr(rng.randrange(0x110000)) for _ in range(6)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    print('Python display fixtures:', len(cases))


if __name__ == '__main__':
    main()
