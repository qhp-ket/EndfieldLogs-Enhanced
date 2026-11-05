"""Fixed input archives, trace associations, loadout ownership and battle-local evidence."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(); reference = args.reference.resolve()
    manifest = json.loads(args.manifest.read_text(encoding='utf8')); dependencies = {}
    for name in ('history', 'interpret', 'storage'):
        relative = f'_internal/src/endfield_pcap/inputlog/{name}.py'
        digest = hashlib.sha256((reference / relative).read_bytes()).hexdigest()
        if digest != manifest['files'][relative]['sha256']: raise ValueError('Fixed reference changed: ' + relative)
        dependencies[relative] = digest
    sys.path.insert(0, str(reference / '_internal/src'))
    import endfield_pcap.inputlog.history as history
    from endfield_pcap.inputlog.interpret import normalize_settings
    class FixedDateTime(datetime):
        @classmethod
        def fromtimestamp(cls, stamp, tz=None):
            return datetime.fromtimestamp(stamp, timezone(timedelta(hours=8))).replace(tzinfo=None)
    # Naive trace dates are interpreted in the Windows reference machine's UTC+8 zone.
    history.datetime = FixedDateTime
    cases = []; base = 1793116800000000000
    header = dict(type='session', schema_version=1, session_id='synthetic', wall_ns=base)
    def event(ms, phase='down', code='K:49', **extra):
        return dict(type='input', wall_ns=base + ms * 1000000, mono_ns=ms * 1000000, kind='key', device='keyboard', code=code, phase=phase, **extra)
    trace = '[00:00:00.000] LOADOUT reason=squad\n[00:00:00.000] LOADOUT slot=0 char=chr_0001_test\n'
    battle = dict(battle_start_at='2026-10-28T00:00:00.000', duration_ms=1000)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); source = root / 'trace_20261028.log'; path = root / 'trace_20261028.input.jsonl'
        def add(kind, events, settings=None, source_text=trace, battle_data=battle, offset=0., manual=None, verify=True, raw=None):
            source.write_text(source_text, encoding='utf8', newline='')
            data = raw if raw is not None else ('\n'.join(json.dumps(item, ensure_ascii=False) for item in events) + '\n').encode('utf8')
            path.write_bytes(data); history.clear_cache()
            config = dict(data=data.hex(), source=source_text, settings=settings, battle=battle_data, offset_ms=offset, manual_slots=manual or {}, verify=verify)
            try:
                if kind == 'archive':
                    item = history.InputArchive(path, settings); counts = Counter()
                    selected = item.raw_range(base, base + 1000000000, normalize_settings(settings), counts)
                    expected = dict(header=item.header, warnings=item.warnings, devices=item.devices, input_counts=dict(item.input_counts),
                        digest=item.digest, actions=item.actions, wall_ordered=item.wall_ordered, raw=selected, selected_counts=counts, verify=item.verify_trace(source))
                else:
                    expected = history.load_evidence([path], source, battle_data, settings, offset_ms=offset, manual_slots=manual, verify=verify)
                    expected['paths'] = ['$input']
            except (ValueError, KeyError, TypeError) as error:
                expected = dict(error=str(error))
            cases.append(dict(kind=kind, name='input-' + kind, config_json=json.dumps(config, ensure_ascii=True), expected=expected))
        for elapsed in [0, 50, 279, 280, 500, 1000]:
            events = [header, event(0), event(elapsed, 'up'), dict(type='end', wall_ns=base + 1100000000)]
            for mode in [{}, dict(show_other=True), dict(show_motion=True, show_axes=True, show_other=True)]:
                add('archive', events, mode); add('evidence', events, mode)
        events = [header, event(0, seq=1), event(100, 'repeat', seq=4), event(200, 'up', seq=5)]
        add('archive', events); add('archive', events + [event(400, seq=5)])
        add('archive', [dict(type='session', schema_version=99)])
        add('archive', [], raw=b'')
        add('archive', [], raw=json.dumps(header).encode() + b'\n' + json.dumps(event(0)).encode() + b'\n{invalid\n' + json.dumps(event(500, 'up')).encode())
        add('archive', [header, event(500), event(100, 'up'), dict(type='diagnostic', reason='input_state_sampling_fallback', wall_ns=base + 600000000)])
        add('archive', [header, event(0), dict(type='gap', seq=3, start_wall_ns=base + 200000000, count=4)])
        proof = dict(type='trace_digest', bytes=len(trace.encode()), sha256=hashlib.sha256(trace.encode()).hexdigest())
        add('archive', [header, event(0), event(100, 'up'), proof], source_text=trace + 'appended')
        add('archive', [header, proof], source_text='short')
        add('archive', [header, dict(proof, sha256='0' * 64)])
        for offset in [-100, 0, 100]:
            for manual in [None, {0: 'chr_0002_test'}]:
                add('evidence', [header, event(100), event(500, 'up')], dict(show_other=True), offset=offset, manual=manual)
        rng = random.Random(20261031)
        for _ in range(40):
            clock = 0; events = [header]
            for seq in range(1, 18):
                clock += rng.randrange(20, 80)
                e = event(clock, rng.choice(['down', 'up', 'repeat']), rng.choice(['K:49', 'K:50', 'K:ALT', 'K:69']), seq=seq)
                e['kind'] = rng.choice(['key', 'motion', 'axis']); events.append(e)
            events.append(dict(type='end', wall_ns=base + 1500000000, seq=18))
            add('archive', events, dict(show_other=True)); add('evidence', events, dict(show_other=True), verify=False)
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/input-evidence.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), offset_minutes=480, dependencies=dependencies), indent=2), encoding='utf8')
    print('Input evidence fixtures:', len(cases))


if __name__ == '__main__': main()
