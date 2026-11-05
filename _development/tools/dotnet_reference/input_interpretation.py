"""Fixed input intention, projection and tooltip reference; no capture hardware or combat calculations."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    reference = args.reference.resolve()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    relative = '_internal/src/endfield_pcap/inputlog/interpret.py'
    digest = hashlib.sha256((reference / relative).read_bytes()).hexdigest()
    if digest != manifest['files'][relative]['sha256']:
        raise ValueError('Fixed input reference changed')
    sys.path.insert(0, str(reference / '_internal/src'))
    from endfield_pcap.inputlog.interpret import Interpreter, normalize_settings, project, tooltip
    cases = []
    base = 1793188800000000000

    def add(name, settings, events, *, start=1793188800000., duration=10000., offset=0.):
        machine = Interpreter(settings)
        steps = []
        for event in events:
            machine.feed(deepcopy(event))
            steps.append(deepcopy(machine.actions))
        actions = machine.close()
        projected = project(actions, start, duration, {0: 'chr_0001_test', 2: 'chr_0003_test'}, offset)
        expected = dict(settings=normalize_settings(settings), steps=steps, actions=actions, projected=projected,
                        tooltips=[tooltip(item) for item in projected])
        config = dict(settings=settings, events=events, start_wall_ms=start, duration_ms=duration, offset_ms=offset)
        cases.append(dict(name=name, config_json=json.dumps(config, ensure_ascii=True), expected=expected))

    def event(ms, code, phase, device='keyboard', **extra):
        return dict(type='input', wall_ns=base + round(ms * 1e6), mono_ns=round(ms * 1e6), device=device,
                    code=code, phase=phase, **extra)

    for hold in [1, 50, 280, 10000]:
        for elapsed in [0, hold - .001, hold, hold + .001]:
            add('tap-hold-boundary', dict(hold_ms=hold), [event(0, 'K:49', 'down'), event(elapsed, 'K:49', 'up')])
    for settings in [None, [], {}, {'bindings': []}, {'bindings': None}, {'hold_ms': '999999999999999999999999'},
                     {'hold_ms': -3}, {'hold_ms': True}, {'hold_ms': 'invalid'}, {'hold_ms': 1.9},
                     {'bindings': [None, {}, dict(action='skill', keys=['K:49', 'K:49'], slot=True, gesture='tap_hold')]},
                     {'bindings': [dict(action='combo', keys=['😀' * 40], slot=3)]},
                     {'show_axes': 'false', 'show_other': [], 'show_motion': [1]}]:
        add('normalization', settings, [event(0, 'K:49', 'down'), event(300, 'K:49', 'up')])
    for keys in [('K:49', 'K:ALT'), ('K:ALT', 'K:49')]:
        for end in ['up', 'gap', 'focus', 'baseline', 'end', 'interrupt']:
            closing = event(500, keys[0], 'up') if end == 'up' else dict(type=end, wall_ns=base + 500000000, mono_ns=500000000,
                active=False, states={}, reason='synthetic')
            add('combination-and-interrupt', {}, [event(0, keys[0], 'down'), event(100, keys[1], 'down'), closing])
    add('baseline-does-not-create-intent', {}, [dict(type='baseline', wall_ns=base, states={'keyboard': ['K:49']}, keyboard_vks=['K:49']),
        event(10, 'K:49', 'down'), event(20, 'K:49', 'up'), event(30, 'K:49', 'down'), event(80, 'K:49', 'up')])
    add('mapped-joystick-duplicate', dict(bindings=[dict(action='combo', keys=['J:0'])]),
        [event(0, 'J:0', 'down', mapped_device=True), event(100, 'J:0', 'up', mapped_device=True)])
    for offset in [-1000, -100, 0, 100, 1000]:
        add('overlap-projection', {}, [event(0, 'K:49', 'down'), event(300, 'K:49', 'up'), event(400, 'K:69', 'down')],
            start=1793188800100., duration=100., offset=offset)
    rng = random.Random(20261029)
    codes = ['K:49', 'K:50', 'K:51', 'K:52', 'K:69', 'K:ALT', 'K:112', 'P:LB', 'P:WEST', 'P:RB', 'P:UP', 'J:0']
    for iteration in range(200):
        events = []
        clock = 0
        for step in range(35):
            clock += rng.randrange(-2, 30)
            kind = rng.randrange(12)
            if kind < 9:
                events.append(event(clock, rng.choice(codes), rng.choice(['down', 'up', 'repeat']), rng.choice(['keyboard', 'pad']), mapped_device=kind == 0))
            else:
                events.append(dict(type=rng.choice(['gap', 'focus', 'interrupt', 'end']), wall_ns=base + clock * 1000000,
                    mono_ns=clock * 1000000, active=False, device=rng.choice([None, 'keyboard', 'pad'])))
        add('random-device-intentions', {'hold_ms': rng.choice([1, 50, 280])}, events)
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/input-interpretation.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases),
        dependencies={relative: digest}), indent=2), encoding='utf8')
    print('Input interpretation fixtures:', len(cases))


if __name__ == '__main__':
    main()
