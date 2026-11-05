"""Freeze cumulative live snapshots, ephemeral timers and prefix replay from the fixed Python engine."""
import argparse
import base64
from datetime import date, datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from types import ModuleType
import zipfile

from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundled', action='store_true')
    args = parser.parse_args()
    if args.bundled and args.output is None:
        parser.error('--bundled requires a local --output')
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/live-engine.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed live engine reference changed: ' + relative)
            dependencies[relative] = digest
    cases = []
    files, binary_files = {}, {}
    with tempfile.TemporaryDirectory() as folder:
        os.environ['ENDFIELD_LOGS_DATA_ROOT'] = folder
        if args.bundled:
            relative = '_internal/data/runtime-data.zip'
            archive_path = args.reference / relative
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed runtime archive changed')
            dependencies[relative] = digest
            with zipfile.ZipFile(archive_path) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    target = (Path(folder) / entry.filename).resolve()
                    if not target.is_relative_to(Path(folder).resolve()):
                        raise ValueError('Unsafe resource path')
                    data = archive.read(entry)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    if entry.filename.endswith('.json'):
                        files['_internal/' + entry.filename] = data.decode('utf8')
                    else:
                        binary_files['_internal/' + entry.filename] = base64.b64encode(data).decode('ascii')
        package = ModuleType('parser_core')
        package.__path__ = [str(args.reference / prefix)]
        sys.modules['parser_core'] = package
        ingestion = importlib.import_module('parser_core.ingestion.stream')
        original = ingestion._raw_battle_ingestion
        ingestion._raw_battle_ingestion = lambda text: original(text, reference_date=date(2026, 10, 29))
        incremental = importlib.import_module('parser_core.realtime.incremental')
        offset_minutes = int(datetime(2026, 10, 29).astimezone().utcoffset().total_seconds() / 60)

        def add(label, steps):
            engine = incremental.IncrementalBattleParser(allow_empty=True)
            snapshots = []
            for step in steps:
                if step.get('reset'):
                    engine = incremental.IncrementalBattleParser(allow_empty=True)
                snapshots.append(canonical(engine.snapshot(step['lines'], step.get('timer'), summary=step.get('summary', False))))
            cases.append(dict(name=f'{len(cases):04d}-{label}', config_json=json.dumps(dict(steps=steps,
                date='2026-10-29', offset_minutes=offset_minutes)), expected=snapshots))

        def hit(ms=1100, value=60, index=1, char='chr_0001_test'):
            return f'[00:00:{ms//1000:02d}.{ms%1000:03d}] HP_V2 #{index} src={char} atk={char} tgt=eny_0001_test skill={char}_normal_skill hit={value}\n'
        start = '[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7\n'
        end = '[00:00:02.000] OFFICIAL_TIMER_END gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=1000\n'
        tick = '[00:00:01.600] LIVE_TIMER_TICK elapsedMs=600\n'
        for summary in [False, True]:
            def step(lines, **extra):
                return dict(lines=lines, summary=summary, **extra)
            add('append-repeat-and-timer', [step([]), step([start]), step([start, hit()]), step([start, hit()]),
                step([start, hit()], timer=tick), step([start, hit(), hit(1500, 40, 2)], timer=tick),
                step([start, hit(), hit(1500, 40, 2), end])])
            add('replace-prefix', [step([hit(), hit(1500, 40, 2)]), step([hit(1100, 25)]), step([hit(1100, 25), hit(1800, 30, 2)])])
            add('partial-final-line', [step([hit()[:45]]), step([hit()[:45], hit()[45:]]), step([hit(), hit(1500, 40, 2)])])
            add('reset-session', [step([start, hit(), end]), step([hit(3000, 9)], reset=True), step([], reset=True)])
            add('late-damage', [step([hit(), hit(2000, 40, 2)]), step([hit(), hit(2000, 40, 2), hit(1500, 10, 3)])])
            buff = '[00:00:01.000] BUFF_START uid=7 id=unknown_buff owner=chr_0001_test ownerId=11 src=chr_0001_test srcId=11\n'
            add('late-buff', [step([hit(), hit(2000, 40, 2)]), step([hit(), hit(2000, 40, 2), buff]),
                step([hit(), hit(2000, 40, 2), buff, '[00:00:02.100] BUFF_END uid=7\n'])])
            add('midnight', [step([hit().replace('00:00:01.100', '23:59:59.900')]),
                step([hit().replace('00:00:01.100', '23:59:59.900'), hit(100, 40, 2)])])
            rng = random.Random(20261029)
            for index in range(12):
                lines, steps = [], []
                for position in range(8):
                    lines = lines + [hit(1100 + position*150, rng.randrange(1, 10**6), position+1,
                        char=rng.choice(['chr_0001_test', 'chr_0002_test']))]
                    steps.append(step(lines))
                add('chunked-battle', steps)
            if args.bundled:
                for name in ['rdps_snapshot_contract', 'ink_recording_contract', 'synthetic_combo_skill', 'synthetic_combo_ultimate',
                             'synthetic_corrosion_packet', 'synthetic_fire_corrosion']:
                    relative = '_internal/packages/parser_core/tests/fixtures/' + name + '.log'
                    data = (args.reference / relative).read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    if digest != metadata['files'][relative]['sha256']:
                        raise ValueError('Fixed synthetic trace changed: ' + relative)
                    dependencies[relative] = digest
                    lines = data.decode('utf8').splitlines(keepends=True)
                    limits = sorted({1, *range(max(1, len(lines)//5), len(lines), max(1, len(lines)//5)), len(lines)})
                    steps = [step(lines[:limit]) for limit in limits]
                    steps.extend([step(lines), step(lines, reset=True)])
                    add(name, steps)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(files=files, binary_files=binary_files, cases=cases) if args.bundled else cases
    output.write_text(json.dumps(payload, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases),
        dependencies=dependencies), indent=2), encoding='utf8')
    print('Live engine fixtures:', len(cases))


if __name__ == '__main__':
    main()
