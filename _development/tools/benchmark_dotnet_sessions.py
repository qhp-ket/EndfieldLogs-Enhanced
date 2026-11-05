"""同机比较真实增量引擎与历史入口；仅生成合成日志，结果写入本地验证目录。"""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return {'int': str(value)}
    if isinstance(value, float):
        return {'f64': struct.pack('>d', value).hex()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return {key: canonical(item) for key, item in value.items()}


def summary(snapshot):
    if snapshot is None:
        return None
    result = {key: snapshot['battle'].get(key) for key in ('total_damage', 'duration_ms', 'time_source')}
    result['participants'] = [{key: row.get(key) for key in ('character_key', 'total_damage', 'total_rd', 'hit_count')}
                              for row in snapshot.get('participants', [])]
    return canonical(result)


def configure(root):
    sys.path.insert(0, str(root / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    return configure_paths(root)


def reference_receipt(root, manifest):
    payload = json.loads(manifest.read_text(encoding='utf-8-sig'))
    dependencies = {}
    for relative, entry in payload['files'].items():
        relevant = (relative.startswith(('_internal/packages/parser_core/parser_core/',
                                         '_internal/src/endfield_pcap/history/', '_internal/src/endfield_pcap/analysis/live/'))
                    and relative.endswith('.py'))
        relevant |= relative in ('_internal/data/runtime-data.zip',
                                '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log',
                                '_internal/src/endfield_pcap/runtime/environment.py',
                                '_internal/src/endfield_pcap/runtime/paths.py')
        if relevant:
            raw = (root / relative).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            newline_equivalent = (relative.endswith('.py')
                                  and hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() == entry['sha256'])
            if digest != entry['sha256'] and not newline_equivalent:
                raise ValueError('Fixed benchmark reference changed: ' + relative)
            dependencies[relative] = dict(actual_sha256=digest, reference_sha256=entry['sha256'],
                                          checkout_crlf_only=digest != entry['sha256'] and newline_equivalent)
    return dict(head=payload['head'], manifest=str(manifest),
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(), dependencies=dependencies)


def worker(args):
    handles = configure(args.qt_root)
    config = json.loads(args.worker.read_text(encoding='utf8'))
    result = dict(implementation='qt', runtime=sys.version)

    def measure(phase, action):
        print('PHASE ' + phase, flush=True)
        start = time.perf_counter()
        value = action()
        return (time.perf_counter() - start) * 1000, value

    if config['mode'] == 'history':
        from endfield_pcap.history.index import HistoryIndex
        from endfield_pcap.history.importer import trace_record_snapshot
        if warmup_path := config.get('warmup_history'):
            def warm_history():
                # Separate records: the production reader caches snapshots on each row.
                index = HistoryIndex(Path(config['cache'] + '-warmup'))
                index_ms, records = measure('warmup_index', lambda: index.records(Path(warmup_path), trace=True))
                cpu = time.process_time()
                analysis_ms, snapshot = measure('warmup_analyze', lambda: trace_record_snapshot(records[0]))
                return dict(record_count=len(records), index_ms=index_ms, analysis_ms=analysis_ms,
                            cpu_ms=(time.process_time() - cpu) * 1000, summary=summary(snapshot))
            result['warmup'] = warm_history()
        index = HistoryIndex(Path(config['cache']))
        result['index_cold_ms'], records = measure('index_cold', lambda: index.records(Path(config['history']), trace=True))
        result['record_count'] = len(records)
        result['ranges'] = [[row.source_start_line, row.source_end_line, row.source_byte_start,
                             row.source_byte_end, row.last_hit_hint] for row in records]
        result['index_cached_ms'], records = measure('index_cached', lambda: index.records(Path(config['history']), trace=True))
        result['selections'] = []
        repeats = config.get('history_repeats', 1)
        if not isinstance(repeats, int) or repeats < 1:
            raise ValueError('history_repeats must be positive')
        for repeat in range(repeats):
            if repeat:
                _, records = measure('index_repeat', lambda: index.records(Path(config['history']), trace=True))
            for position in dict.fromkeys([0, len(records) // 2, len(records) - 1]):
                if records[position].snapshot:
                    raise ValueError('Measured history record already has a cached report')
                cpu = time.process_time()
                elapsed, snapshot = measure('analyze_' + str(position), lambda: trace_record_snapshot(records[position]))
                cpu_ms = (time.process_time() - cpu) * 1000
                selection = dict(position=position, elapsed_ms=elapsed, cpu_ms=cpu_ms, summary=summary(snapshot))
                if repeats > 1:
                    selection['repeat'] = repeat
                result['selections'].append(selection)
                # Full evidence exports are opt-in and run after the measured analysis.
                if directory := config.get('report_directory'):
                    print('PHASE export_' + str(position), flush=True)
                    destination = Path(directory)
                    destination.mkdir(parents=True, exist_ok=True)
                    suffix = f'-repeat-{repeat}' if repeats > 1 else ''
                    (destination / f'report-{position}{suffix}.json').write_text(json.dumps(canonical(snapshot)), encoding='utf8')
                del snapshot
    else:
        events = None
        if config.get('format') == 'jsonl':
            from parser_core.trace_jsonl import TraceEvent, TraceJsonlReader
            from parser_core.realtime.events import EventBattleParser, LiveEventBatch
            reader = TraceJsonlReader()
            events = []
            with Path(config['live']).open('rb') as source:
                while chunk := source.read(65536):
                    events.extend(item for item in reader.feed(chunk) if isinstance(item, TraceEvent))
            if reader.header is None or reader.pending_bytes:
                raise ValueError('Incomplete trace input')
            result['initialize_ms'], engine = measure('initialize', lambda: EventBattleParser(allow_empty=True,
                reference_date=date.fromisoformat(config['date']), timezone_offset_minutes=reader.header.timezone_offset_minutes))
        else:
            import parser_core.ingestion.stream as ingestion
            original = ingestion._raw_battle_ingestion
            ingestion._raw_battle_ingestion = lambda text: original(text, reference_date=date.fromisoformat(config['date']))
            from parser_core.realtime.incremental import IncrementalBattleParser
            result['initialize_ms'], engine = measure('initialize', lambda: IncrementalBattleParser(allow_empty=True))
        lines = Path(config['live']).read_text(encoding='utf8').splitlines(keepends=True) if events is None else []
        cumulative = []
        result['updates'] = []
        count = len(lines) if events is None else len(events)
        for offset in range(0, count, config['batch']):
            consumed = min(offset + config['batch'], count)
            if events is None:
                cumulative.extend(lines[offset:consumed])
                action = lambda: engine.snapshot(cumulative, summary=True)
            else:
                batch = LiveEventBatch(1, consumed, offset, tuple(events[offset:consumed]))
                action = lambda: engine.snapshot_events(batch, summary=True)
            print('PHASE updates', flush=True)
            cpu = time.process_time()
            start = time.perf_counter()
            snapshot = action()
            elapsed = (time.perf_counter() - start) * 1000
            cpu_ms = (time.process_time() - cpu) * 1000
            result['updates'].append(dict(lines=consumed, elapsed_ms=elapsed, cpu_ms=cpu_ms, summary=summary(snapshot)))
        result['cached_ms'], _ = measure('cached', lambda: engine.snapshot(cumulative, summary=True) if events is None
            else engine.snapshot_events(LiveEventBatch(1, count, count, ()), summary=True))
        result['format'] = 'legacy' if events is None else 'jsonl'
        result['diagnostics'] = engine.diagnostics
    args.result.write_text(json.dumps(result, indent=2), encoding='utf8')


def workload(reference, output, live_cycles, battles, history_cycles):
    source = reference / '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log'
    original = source.read_text(encoding='utf8').splitlines()
    template = [line for line in original if line.startswith('[')]

    def stamp(milliseconds):
        hours, remainder = divmod(milliseconds, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, fraction = divmod(remainder, 1000)
        return f'[{hours % 24:02}:{minutes:02}:{seconds:02}.{fraction:03}]'

    def cycle(index, origin):
        rows = []
        for line in template:
            parts = re.match(r'\[(\d+):(\d+):(\d+)\.(\d+)\]', line)
            h, m, s, ms = map(int, parts.groups())
            relative = ((h - 10) * 3600 + m * 60 + s) * 1000 + ms
            line = stamp(origin + relative) + line[parts.end():]
            line = line.replace('9007199254740993', str(9007199254740993 + index))
            line = line.replace('actionId=11', 'actionId=' + str(11 + index))
            rows.append(line + '\n')
        return rows

    def battle(index, cycles):
        origin = 10 * 3600000 + index * (cycles * 3000 + 2000)
        rows = [stamp(origin) + f' OFFICIAL_TIMER_START gameId=benchmark source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs={index + 1}\n']
        for number in range(cycles):
            rows.extend(cycle(index * cycles + number, origin + number * 3000))
        rows.append(stamp(origin + cycles * 3000) + f' OFFICIAL_TIMER_END gameId=benchmark source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime={cycles * 3000}\n')
        return ''.join(rows)

    live = output / 'live_20261029.log'
    history = output / 'trace_20261029.log'
    live.write_text(battle(0, live_cycles), encoding='utf8', newline='')
    history.write_text(''.join(battle(index, history_cycles) for index in range(battles)), encoding='utf8', newline='')
    return dict(live=str(live), history=str(history), date='2026-10-29'), dict(
        source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        live_cycles=live_cycles, history_battles=battles, history_cycles=history_cycles,
        files={path.name: dict(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
               for path in (live, history)})


def measure(command, result, environment, psutil):
    samples = []
    launched = time.perf_counter()
    console_path = result.with_suffix('.console.txt')
    with console_path.open('w', encoding='utf8') as console:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=console, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            parent = psutil.Process(process.pid)
            while process.poll() is None:
                if time.perf_counter() - launched > 600:
                    raise TimeoutError('Session benchmark exceeded 600 seconds')
                rss = private = cpu = 0
                try:
                    children = [parent, *parent.children(recursive=True)]
                except psutil.Error:
                    break
                for child in children:
                    try:
                        memory = child.memory_info()
                        times = child.cpu_times()
                        rss += memory.rss
                        private += getattr(memory, 'private', 0)
                        cpu += times.user + times.system
                    except psutil.Error:
                        pass
                phases = [line[6:] for line in console_path.read_text(encoding='utf8').splitlines() if line.startswith('PHASE ')]
                samples.append(dict(seconds=time.perf_counter() - launched, phase=phases[-1] if phases else 'startup',
                                    rss=rss, private=private, cpu=cpu))
                time.sleep(.025)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
    if process.returncode:
        raise RuntimeError(f'Benchmark failed: {result.with_suffix(".console.txt")}')
    data = json.loads(result.read_text(encoding='utf8'))
    data['external'] = dict(wall_ms=(time.perf_counter() - launched) * 1000,
                            peak_rss_mib=max(row['rss'] for row in samples) / 1024**2,
                            peak_private_mib=max(row['private'] for row in samples) / 1024**2, samples=samples)
    result.write_text(json.dumps(data, indent=2), encoding='utf8')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt-root', type=Path, required=True)
    parser.add_argument('--reference-manifest', type=Path)
    parser.add_argument('--dotnet', type=Path, default=ROOT.parent / '.toolchains/dotnet/dotnet.exe')
    parser.add_argument('--tools', type=Path, default=ROOT / '_internal/dotnet/Tools/bin/Release/net10.0/EndfieldLogs.Tools.dll')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--live-cycles', type=int, default=120)
    parser.add_argument('--battles', type=int, default=80)
    parser.add_argument('--history-cycles', type=int, default=10)
    parser.add_argument('--batch', type=int, default=64)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    args.qt_root = args.qt_root.resolve()
    if args.worker:
        return worker(args)
    if args.output is None or min(args.rounds, args.live_cycles, args.battles, args.history_cycles, args.batch) <= 0:
        parser.error('--output and positive workload sizes are required')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    handles = configure(args.qt_root)
    import psutil
    manifest = (args.reference_manifest or args.qt_root / '_development/verification/application-layers/qt-layered-c9f01b7-manifest.json').resolve()
    receipt = reference_receipt(args.qt_root, manifest)
    config, metadata = workload(args.qt_root, args.output, args.live_cycles, args.battles, args.history_cycles)
    metadata['reference'] = receipt
    source_inputs = [ROOT / relative for relative in (
        '_internal/dotnet/Runtime/History/HistoryCatalog.cs', '_internal/dotnet/Runtime/History/HistoryAnalyzer.cs',
        '_internal/dotnet/Core/History/TraceBattleSplitter.cs', '_internal/dotnet/Core/Compatibility/PythonTextLines.cs',
        '_internal/dotnet/Core/Catalog/ResourceFiles.cs', '_internal/dotnet/Core/Compatibility/EvidenceJson.cs',
        '_internal/dotnet/Core/Realtime/LiveBattleEngine.cs')]
    source_inputs += list(args.tools.resolve().parent.glob('EndfieldLogs.*.dll'))
    (args.output / 'source-inputs.json').write_text(json.dumps(
        {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_inputs}, indent=2), encoding='utf8')
    config['batch'] = args.batch
    environment = dict(os.environ, DOTNET_ROOT=str(args.dotnet.resolve().parent))
    rounds = []
    for number in range(args.rounds):
        for mode in ('history', 'live'):
            pair = {}
            for name in (('qt', 'csharp') if number % 2 == 0 else ('csharp', 'qt')):
                stem = f'{name}-{mode}-{number+1}'
                settings = args.output / (stem + '.input.json')
                settings.write_text(json.dumps(dict(config, mode=mode, cache=str(args.output / (stem + '-cache')))), encoding='utf8')
                result = args.output / (stem + '.json')
                command = ([sys.executable, '-B', str(Path(__file__).resolve()), '--qt-root', str(args.qt_root),
                            '--worker', str(settings), '--result', str(result)] if name == 'qt' else
                           [str(args.dotnet.resolve()), str(args.tools.resolve()), 'benchmark-session', str(ROOT), str(settings), str(result)])
                print('Running ' + stem, flush=True)
                pair[name] = measure(command, result, environment, psutil)
                rounds.append(dict(implementation=name, mode=mode, round=number+1, result=pair[name]))
            if mode == 'history':
                equal = pair['qt']['ranges'] == pair['csharp']['ranges'] and [row['summary'] for row in pair['qt']['selections']] == [row['summary'] for row in pair['csharp']['selections']]
            else:
                equal = [row['summary'] for row in pair['qt']['updates']] == [row['summary'] for row in pair['csharp']['updates']]
            if not equal:
                raise ValueError('Benchmark sanity comparison differs; inspect ' + mode + ' results')
    summary_data = dict(workload=metadata, rounds=rounds, sanity_equal=True)
    summary_data['medians'] = []
    for name in ('qt', 'csharp'):
        for mode in ('history', 'live'):
            rows = [row['result'] for row in rounds if row['implementation'] == name and row['mode'] == mode]
            fields = ('index_cold_ms', 'index_cached_ms') if mode == 'history' else ('initialize_ms', 'cached_ms')
            medians = {key: statistics.median(row[key] for row in rows) for key in fields}
            for key in ('wall_ms', 'peak_rss_mib', 'peak_private_mib'):
                medians[key] = statistics.median(row['external'][key] for row in rows)
            for phase in ('index_cold', 'index_cached', 'updates'):
                peaks = [max(selected) / 1024**2 for row in rows
                         if (selected := [item['rss'] for item in row['external']['samples'] if item['phase'] == phase])]
                if peaks:
                    medians[phase + '_peak_rss_mib'] = statistics.median(peaks)
                    medians[phase + '_sampled_rounds'] = len(peaks)
            if mode == 'live':
                medians['updates_p50_ms'] = statistics.median(statistics.median(item['elapsed_ms'] for item in row['updates']) for row in rows)
                medians['last_update_ms'] = statistics.median(row['updates'][-1]['elapsed_ms'] for row in rows)
            summary_data['medians'].append(dict(implementation=name, mode=mode, **medians))
    (args.output / 'summary.json').write_text(json.dumps(summary_data, indent=2), encoding='utf8')
    print(json.dumps(summary_data['medians'], indent=2), flush=True)


if __name__ == '__main__':
    main()
