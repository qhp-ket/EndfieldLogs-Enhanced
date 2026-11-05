"""Fixed Windows raw/SDL ABI and state-fallback policies; no live input collection."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    reference = args.reference.resolve()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    dependencies = {}
    for name in ['raw_input.py', 'sdl.py', 'windows_state.py']:
        relative = '_internal/src/endfield_pcap/inputlog/backends/' + name
        digest = hashlib.sha256((reference / relative).read_bytes()).hexdigest()
        if digest != manifest['files'][relative]['sha256']:
            raise ValueError('Fixed input backend reference changed: ' + relative)
        dependencies[relative] = digest
    sys.path.insert(0, str(reference / '_internal/src'))
    from endfield_pcap.inputlog.backends.raw_input import RawInput
    from endfield_pcap.inputlog.backends.sdl import SDLInput
    from endfield_pcap.inputlog.backends.windows_state import WindowsStateFallback
    cases = []

    def add_raw(name, operations):
        output = []
        raw = RawInput.__new__(RawInput)
        raw.pressed = set()
        raw._device = lambda handle: f'raw:{int(handle or 0):x}'
        raw.emit = lambda typ, **fields: output.append(dict(type=typ, **fields))
        for op in operations:
            if op.get('disconnect'):
                raw.pressed = {p for p in raw.pressed if p[0] != op['device']}
            else:
                payload = bytes.fromhex(op['payload'])
                raw._decode(struct.pack('<IIQQ', op['type'], 24 + len(payload), int(op['device'][4:], 16), 0) + payload)
        cases.append(dict(name=name, kind='raw', operations=operations, expected=output))

    def key(vk, scan=30, flags=0, device='raw:1234'):
        return dict(type=1, device=device, payload=struct.pack('<HHHHII', scan, flags, 0, vk, 0x100 + bool(flags & 1), 123).hex())

    for vk in [0, 16, 17, 18, 49, 69, 91, 92, 160, 161, 162, 163, 164, 165, 254, 255]:
        add_raw('keyboard-repeat-release', [key(vk), key(vk), key(vk, flags=1), key(vk), dict(disconnect=True, device='raw:1234'), key(vk)])
    add_raw('independent-devices-and-scan-prefixes', [key(49), key(49, device='raw:4321'), key(49, flags=2), key(49, flags=4), key(49), key(49, flags=1)])
    for buttons in [0, 1, 2, 3, 0x3ff, 0x400, 0x800, 0xc00, 0xfff]:
        for flags, x, y, wheel in [(0, 0, 0, 120), (1, 0, 0, -120), (0, -32768, 2147483647, -1)]:
            raw = struct.pack('<HHHHIiiI', flags, 0, buttons, wheel & 0xffff, 0, x, y, 123456)
            add_raw('mouse-all-fields', [dict(type=0, device='raw:ff', payload=raw.hex())])
    add_raw('truncated-and-hid', [dict(type=typ, device='raw:0', payload=bytes(size).hex()) for typ in [0, 1, 2] for size in [0, 3, 15]])
    rng = random.Random(20261029)
    for _ in range(70):
        add_raw('random-key-stream', [key(rng.randrange(256), scan=rng.randrange(128), flags=rng.randrange(8), device=f'raw:{rng.randrange(3):x}') for _ in range(40)])

    class Buffer:
        raw = bytes(128)
    class Lib:
        def __init__(self, reports): self.reports = iter(reports)
        def SDL_PollEvent(self, buf):
            try: buf.raw = next(self.reports); return True
            except StopIteration: return False

    for typ in list(range(0x600, 0x609)) + list(range(0x650, 0x65f)) + [0, 0x700]:
        for index in [0, 7, 20, 255]:
            if typ in [0x605, 0x606, 0x653, 0x654]: continue  # native handle ownership has independent tests
            raw = bytearray(rng.randbytes(128))
            struct.pack_into('<IIQI', raw, 0, typ, 0, 12345678901234, 12)
            raw[20] = index
            raw[21] = index % 2
            for at in [24, 28, 32, 36]: struct.pack_into('<f', raw, at, rng.uniform(-2, 2))
            for mapped in [False, True]:
                out = []
                source = SDLInput.__new__(SDLInput)
                source.buffer, source.lib = Buffer(), Lib([bytes(raw)])
                source.gamepads = {12: 1} if mapped else {}
                source.emit = lambda typ, **fields: out.append(dict(type=typ, **fields))
                source.pump()
                cases.append(dict(name='sdl-event-abi', kind='sdl', payload=raw.hex(), mapped=mapped, expected=out))

    base = 1793188800000000000
    for iteration in range(100):
        operations = []; state = set(); mono = 0; output = []; steps = []
        env = dict(mono=0, focused=True, keys=[])
        sampler = WindowsStateFallback(lambda typ, **fields: output.append(dict(type=typ, **fields)),
            lambda: env['focused'], lambda vk: 0x8000 if vk in env['keys'] else 0)
        with patch('time.perf_counter_ns', lambda: env['mono']), patch('time.time_ns', lambda: base + env['mono']):
            for at in range(60):
                emitted = len(output)
                mono += rng.choice([1, 7, 8, 40, 80, 160]) * 1000000
                if rng.randrange(6) == 0:
                    op = dict(op='note', mono_ns=mono, code=rng.choice(['K:49', 'K:CTRL', 'M:1']), phase=rng.choice(['down', 'repeat', 'up']))
                    sampler.note_event(op)
                else:
                    vk = rng.choice([1, 2, 4, 5, 6, 17, 49, 69, 162])
                    state.symmetric_difference_update([vk])
                    op = dict(op='sample', mono_ns=mono, wall_ns=base + mono, active=rng.randrange(8) != 0, keys=sorted(state))
                    env.update(mono=mono, focused=op['active'], keys=op['keys'])
                    sampler.pump()
                operations.append(op)
                steps.append(dict(events=deepcopy(output[emitted:]), samples=sampler.samples, announced=sorted(sampler.announced)))
        cases.append(dict(name='state-fallback', kind='state', operations=operations, expected=steps))
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/input-backends.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':'), allow_nan=False), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Input backend fixtures:', len(cases))


if __name__ == '__main__':
    main()
