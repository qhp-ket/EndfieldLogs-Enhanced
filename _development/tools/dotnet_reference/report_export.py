"""Freeze complete reports from trace ingestion, quality states and canonical fingerprints."""
import argparse
import base64
import copy
from datetime import date, datetime
import hashlib
import importlib
import itertools
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
    output = args.output or Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/report-export.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, info in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference / relative).read_bytes()).hexdigest()
            if digest != info['sha256']:
                raise ValueError('Fixed report export reference changed: ' + relative)
            dependencies[relative] = digest
    with tempfile.TemporaryDirectory() as folder:
        os.environ['ENDFIELD_LOGS_DATA_ROOT'] = folder
        files, binary_files = {}, {}
        if args.bundled:
            relative = '_internal/data/runtime-data.zip'
            archive_path = args.reference / relative
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed runtime bundle changed')
            dependencies[relative] = digest
            with zipfile.ZipFile(archive_path) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    target = (Path(folder) / entry.filename).resolve()
                    if not target.is_relative_to(Path(folder).resolve()):
                        raise ValueError('Unsafe fixed resource path')
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
        report = importlib.import_module('parser_core.reporting.battle')
        quality = importlib.import_module('parser_core.snapshot_quality')
        integrity = importlib.import_module('parser_core.integrity')
        cases = []
        offset_minutes = int(datetime(2026, 10, 29).astimezone().utcoffset().total_seconds() / 60)

        def add(kind, label, config):
            try:
                if kind == 'report':
                    text = '\n'.join(config['lines'])
                    stream = ingestion._raw_battle_ingestion('', reference_date=date.fromisoformat(config['date']),
                        loadout_override_by_char=config.get('loadouts'))
                    next(stream)
                    state = stream.send(enumerate(config['lines'], 1))
                    stream.close()
                    result = report._build_raw_battle_report(state, text, file_name=config.get('file_name'),
                        include_rdps_debug=config.get('debug', False), allow_empty=config.get('allow_empty', False))
                elif kind == 'quality':
                    result = quality.build_snapshot_quality(config['report'], include_evidence=config['include_evidence'])
                else:
                    payload = config['payload']
                    result = dict(json=integrity.build_canonical_json(payload), sha256=integrity.build_canonical_sha256(payload))
            except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
                result = dict(error=type(error).__name__)
            cases.append(dict(name=f'{len(cases):04d}-{label}', kind=kind, config_json=json.dumps(config), expected=canonical(result)))

        a, b, enemy = 'chr_0001_test', 'chr_0002_test', 'eny_0001_test'
        def hit(stamp='00:00:01.100', value=60, char=a, target=enemy, seq=1, extra=''):
            return f'[{stamp}] HP_V2 #{seq} src={char} atk={char} tgt={target} skill={char}_normal_skill hit={value} {extra}'
        def add_report(label, lines, **changes):
            add('report', label, dict(lines=lines, date='2026-10-29', file_name='synthetic.log', offset_minutes=offset_minutes, **changes))
        add_report('no-events', [])
        add_report('no-events-allowed', [], allow_empty=True)
        add_report('unrelated-allowed', ['[00:00:01.000] SYNTHETIC_CONTEXT'], allow_empty=True)
        for debug in [False, True]:
            add_report('single-hit', [hit()], debug=debug)
            add_report('multi-role', [hit(), hit('00:00:01.200', 40, b, seq=2), hit('00:00:02.200', 75, seq=3, extra='crit=1')], debug=debug)
            add_report('raw-identity-tag', ['[00:00:01.000] IDENTITY_INFERENCE synthetic', hit()], debug=debug)
            add_report('midnight', [hit('23:59:59.900'), hit('00:00:00.100', 40, seq=2)], debug=debug)
            add_report('buff-no-effects', [f'[00:00:01.000] BUFF_START uid=7 id=unknown_buff owner={a} ownerId=11 src={a} srcId=11',
                       hit(), '[00:00:01.150] BUFF_END uid=7', hit('00:00:01.300', 40, seq=2)], debug=debug)
            add_report('casts-and-atb', [f'[00:00:01.000] SKILL_CAST_START skill={a}_normal_skill owner={a} ownerId=11 inst=cast',
                hit(), f'[00:00:01.110] ATB_UPDATE owner={a} ownerId=11 atb=2 delta=1 recoverySpeed=3 tick=100 reason=AddValue',
                '[00:00:01.300] SKILL_CAST_END inst=cast', hit('00:00:02.000', 40, seq=2)], debug=debug)
        for elapsed, passed, game in itertools.product([1, 400, 5000], [0, 1], ['challenge', 'dung_raid_weekly_battletower']):
            lines = [f'[00:00:01.000] OFFICIAL_TIMER_START gameId={game} source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7',
                     hit(), hit('00:00:01.200', 40, seq=2),
                     f'[00:00:01.500] OFFICIAL_TIMER_END gameId={game} source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass={passed} passTime={elapsed}']
            add_report('official-completion', lines, debug=True)
            add_report('official-without-hits', [lines[0], lines[-1]])
        add_report('reset-previous-battle', [hit('00:00:00.500'),
            '[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7',
            hit('00:00:01.100', 40, seq=2),
            '[00:00:01.500] OFFICIAL_TIMER_END gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=400'], debug=True)
        add_report('empty-official-scope', [hit('00:00:00.500'),
            '[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7'])
        for loadouts in [{a: dict(character_key=a, character_name='甲', slot=1)},
                         {b: dict(character_key=b, character_name='乙', slot=0), a: dict(character_key=a, slot=2)}]:
            add_report('ready-loadout', ['[00:00:00.100] SYNTHETIC_CONTEXT'], loadouts=loadouts)
            add_report('loadout-and-damage', [hit(), hit('00:00:02.000', 40, seq=2)], loadouts=loadouts, debug=True)
        for hp in ['hp=0', 'hp=100', '']:
            add_report('hp-clear', [hit(extra=hp), hit('00:00:02.000', 40, seq=2, extra=hp)])
        rng = random.Random(771001)
        for _ in range(25):
            rows = [hit(f'00:00:{1+i//4:02d}.{(i%4)*200:03d}', rng.randrange(0, 10000), rng.choice([a, b]),
                        rng.choice([enemy, 'eny_0002_other']), i+1, rng.choice(['crit=1', 'crit=0', ''])) for i in range(rng.randrange(1, 14))]
            add_report('ordered-damage-series', rows, debug=True)
        for name in ['rdps_snapshot_contract', 'ink_recording_contract', 'synthetic_combo_skill', 'synthetic_combo_ultimate',
                     'synthetic_corrosion_packet', 'synthetic_fire_corrosion']:
            relative = '_internal/packages/parser_core/tests/fixtures/' + name + '.log'
            data = (args.reference / relative).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != metadata['files'][relative]['sha256']:
                raise ValueError('Fixed synthetic trace changed: ' + relative)
            dependencies[relative] = digest
            add_report(name, data.decode('utf8').splitlines(), debug=True)
        verified = dict(battle=dict(duration_ms=1000, time_source='game_timer', timer_integrity_ok=True,
            timer_integrity_reasons=[], timer_window_valid=True, timer_start_inferred=False),
            rdps_preflight=dict(ok=True, blocker_count=0, blockers=[]),
            rdps_damage_basis=dict(rdps_preflight_ok=True, rdps_strict_ok=True, rdps_conservation_ok=True, hit_count=1))
        for include in [False, True]:
            for payload in [{}, verified, dict(battle={}), dict(verified, rdps_preflight=None), dict(verified, rdps_damage_basis=None)]:
                add('quality', 'availability', dict(report=payload, include_evidence=include))
            for field, values in [('duration_ms', [None, 0, -1, 1, 1., True, '1', float('nan'), float('inf')]),
                                  ('timer_integrity_ok', [None, False, True, 0, 1]), ('timer_window_valid', [None, False, True, 0, 1]),
                                  ('timer_start_inferred', [None, False, True, 0, 1])]:
                for value in values:
                    payload = copy.deepcopy(verified)
                    payload['battle'][field] = value
                    add('quality', 'timing-types', dict(report=payload, include_evidence=include))
            for field, values in [('hit_count', [None, 0, -1, 1, 0., 1., False, True]), ('rdps_strict_ok', [None, False, True, 0, 1]),
                                  ('missing_packet_hit_count', [0, 1]), ('unresolved_damage_actor_count', [0, 1])]:
                for value in values:
                    payload = copy.deepcopy(verified)
                    payload['rdps_damage_basis'][field] = value
                    add('quality', 'damage-types', dict(report=payload, include_evidence=include))
            payload = copy.deepcopy(verified)
            payload['rdps_preflight']['blockers'] = [dict(uid=2**63, negative=-2**63, safe=2**53-1, value=float('inf'))]
            add('quality', 'wide-evidence', dict(report=payload, include_evidence=include))
        for payload in [dict(z=1, a='中文😀', nul='\0\n\t', quote='"\\/'), [0, -0., 1., 1e-7, 2**64, float('nan'), float('inf')],
                        {'😀': 1, '\ue000': 2, 'nested': dict(z=0, a=[True, None, 'x'])}]:
            add('integrity', 'canonical-json', dict(payload=payload))
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(files=files, binary_files=binary_files, cases=cases) if args.bundled else cases
        output.write_text(json.dumps(payload, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
        output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=metadata['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
        print('Complete report fixtures:', len(cases))


if __name__ == '__main__':
    main()
