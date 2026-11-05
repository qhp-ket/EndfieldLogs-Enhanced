"""Fixed synthetic HUD pixels, layout confirmation and cooldown tracking; no desktop capture."""
import argparse
import base64
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sys
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--dependency-root', type=Path)
    args = parser.parse_args()
    if args.dependency_root: sys.path.insert(0, str(args.dependency_root.resolve()))
    reference = args.reference.resolve(); manifest = json.loads(args.manifest.read_text(encoding='utf8')); dependencies = {}
    for name in ['layout.py', 'pixels.py', 'tracking.py', 'engine.py']:
        relative = '_internal/src/endfield_pcap/vision/' + name
        digest = hashlib.sha256((reference / relative).read_bytes()).hexdigest()
        if digest != manifest['files'][relative]['sha256']: raise ValueError('Fixed vision reference changed: ' + relative)
        dependencies[relative] = digest
    sys.path.insert(0, str(reference / '_internal/src'))
    import numpy as np
    from endfield_pcap.vision.layout import normalize_config, presets, fitted_presets, game_area
    from endfield_pcap.vision.pixels import Observation, observe
    from endfield_pcap.vision.tracking import SlotTracker
    from endfield_pcap.vision.engine import VisionEngine
    frames = {}; cases = []

    def frame(pixels):
        raw = pixels.tobytes(); key = hashlib.sha256(raw + str(pixels.shape).encode()).hexdigest()[:20]
        frames[key] = dict(width=pixels.shape[1], height=pixels.shape[0], channels=pixels.shape[2], zlib=base64.b64encode(zlib.compress(raw, 9)).decode())
        return key

    for config in [None, [], {}, {'layout': 'invalid'}, {'layout': 'custom'}, {'target_hwnd': '-1'}, {'target_hwnd': '12_345'},
                   {'target_hwnd': True}, {'target_hwnd': 123.9}, {'target_hwnd': 'invalid'},
                   {'layout': 'custom', 'regions': presets()['keyboard']},
                   {'layout': 'custom', 'regions': [dict(energy=[0, 0, 1, True], hp=[0, 0, 1, 1], portrait=[0, 0, 1, 1])] * 4}]:
        cases.append(dict(kind='config', config=config, expected=normalize_config(config)))
    for width, height in [(2048, 1152), (1920, 1080), (2560, 1080), (3840, 2160), (1280, 1024), (800, 600), (512, 288), (1, 1), (100, 2000)]:
        candidates = fitted_presets((0, 0, width, height))
        cases.append(dict(kind='layout', area=[0, 0, width, height], expected=[dict(name=n, identity=i, regions=r) for n, i, r in candidates]))
    rng = random.Random(20261029)
    for prefix in [0, 1, 3, 4, 5, 10, 20, 30, 37, 38, 39, 40]:
        for style in ['hp', 'dim', 'red', 'death', 'empty', 'scenery']:
            energy = np.full((4, 40, 3), 60, dtype=np.uint8); energy[:, 1:prefix] = [235, 235, 235]
            hp = np.full((7, 40, 3), [30, 150, 210], dtype=np.uint8); portrait = np.full((26, 26, 3), 40, dtype=np.uint8)
            if style == 'dim': energy[:] = 130
            if style == 'red': energy[:, prefix:] = [125, 25, 25]
            if style in ['death', 'empty']: hp[:] = 0; portrait[:] = 0
            if style == 'death':
                for y in range(26):
                    for x in range(26):
                        if abs(x / 25 - y / 25) < .075 or abs(x / 25 + y / 25 - 1) < .075: portrait[y, x] = 240
            if style == 'scenery': energy = rng.randbytes(4 * 40 * 3); energy = np.frombuffer(energy, np.uint8).reshape(4, 40, 3)
            cases.append(dict(kind='pixels', energy=frame(energy), hp=frame(hp), portrait=frame(portrait), expected=asdict(observe(energy, hp, portrait))))
    for width in [0, 1, 11]:
        pixels = np.zeros((2, width, 3), np.uint8)
        cases.append(dict(kind='pixels', energy=frame(pixels), hp=frame(pixels), portrait=frame(pixels), expected=asdict(observe(pixels, pixels, pixels))))
    for iteration in range(100):
        tracker = SlotTracker(); ops = []; outputs = []; now = 0.; progress = 0.
        for step in range(60):
            now += rng.choice([.01, .05, .1, .2, .75, 1.01]); progress = max(0., min(1., progress + rng.choice([-.2, 0., .005, .01, .02, .3])))
            if step % 11 == 0: op = dict(op='invalid', now=now); tracker.invalid(now); result = tracker.payload(now)
            else:
                obs = Observation(readable=rng.randrange(5) != 0, progress=progress, ready=progress >= .965,
                    consumed=progress < .08, dead=step % 19 == 0, empty=step % 23 == 0)
                op = dict(op='feed', now=now, frame_id=step // 2 if iteration % 2 else step, observation=asdict(obs))
                result = tracker.feed(obs, now, op['frame_id'])
            ops.append(op); outputs.append(result)
        cases.append(dict(kind='tracker', operations=ops, expected=outputs))
    # Stable slow movement must establish a remaining-time estimate, then carry it across missing frames.
    for speed in [.02, .1, .5]:
        tracker = SlotTracker(); ops = []; outputs = []
        for step in range(25):
            obs = Observation(True, min(1., .1 + step * .05 * speed))
            op = dict(op='feed', now=step * .05, frame_id=step, observation=asdict(obs)); ops.append(op); outputs.append(tracker.feed(obs, op['now'], step))
        for now in [1.3, 2., 5., 50.]:
            tracker.invalid(now); ops.append(dict(op='invalid', now=now)); outputs.append(tracker.payload(now))
        cases.append(dict(kind='tracker', operations=ops, expected=outputs))

    def render(width, height, name, values, bands=False):
        pixels = np.full((height, width, 4), 30, dtype=np.uint8)
        if bands:
            trim = height // 10; pixels[:trim] = 0; pixels[-trim:] = 0
        area = game_area(pixels, (0, 0, width, height)); regions = next(rows for n, _, rows in fitted_presets(area) if n == name)
        ax, ay, aw, ah = area
        def region(rect):
            x, y, w, h = rect; left, top = round(ax + x * aw), round(ay + y * ah); right, bottom = round(ax + (x + w) * aw), round(ay + (y + h) * ah)
            return pixels[max(0, top):min(height, max(top + 1, bottom)), max(0, left):min(width, max(left + 1, right)), :3]
        for row, value in zip(regions, values):
            energy, hp, portrait = (region(row[key]) for key in ['energy', 'hp', 'portrait'])
            energy[:] = 60; hp[:] = [30, 150, 210]; portrait[:] = 40
            if value == 'dim': energy[:] = 130
            elif value == 'empty': hp[:] = 0; portrait[:] = 0
            elif value == 'missing': energy[:] = 0; hp[:] = 0
            else: energy[:, 1:round(energy.shape[1] * value)] = 235
        return pixels
    for width, height in [(2048, 1152), (1920, 1080), (2560, 1080), (1280, 1024), (800, 600), (512, 288)]:
        for name in ['keyboard', 'gamepad', 'gamepad_expanded']:
            for bands in [False, True]:
                config = dict(layout='auto'); engine = VisionEngine(config); operations = []; outputs = []
                for index, values in enumerate([[1., .3, 0., 'empty'], [1., .3, 0., 'empty'], ['dim', .4, 0., 'empty'], ['missing', .5, 'missing', 'empty'], [0., .6, 1., 'empty']]):
                    pixels = render(width, height, name, values, bands); key = frame(pixels); now = index * .1
                    operations.append(dict(frame=key, client=[0, 0, width, height], now=now, frame_id=index))
                    outputs.append(engine.analyze(pixels, (0, 0, width, height), now, index))
                operations.append(dict(invalid=True, now=2., reason='画面未更新')); outputs.append(engine.invalid(2., '画面未更新'))
                cases.append(dict(kind='engine', config=config, operations=operations, expected=outputs))
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/vision.json'
    output.write_text(json.dumps(dict(frames=frames, cases=cases), ensure_ascii=True, separators=(',', ':'), allow_nan=False), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), frames=len(frames), dependencies=dependencies), indent=2), encoding='utf8')
    print('Vision fixtures:', len(cases), 'shared compressed frames:', len(frames))


if __name__ == '__main__': main()
