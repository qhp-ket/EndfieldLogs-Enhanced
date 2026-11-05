"""同机串行测量 Qt 与 C# 三浮窗；输出包含整个子进程树的采样。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from verify_benchmark_identity import desktop_runtime_directory

ROOT = Path(__file__).resolve().parents[2]


def measure(command, output, environment, psutil):
    for suffix in ('.ready', '.phase'):
        output.with_suffix(output.suffix + suffix).unlink(missing_ok=True)
    launched = time.perf_counter()
    samples, ready = [], None
    with output.with_suffix('.console.txt').open('w', encoding='utf8') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            parent = psutil.Process(process.pid)
            while process.poll() is None:
                elapsed = time.perf_counter() - launched
                if elapsed > 60:
                    raise TimeoutError('Overlay benchmark did not finish in 60 seconds')
                if ready is None and output.with_suffix(output.suffix + '.ready').exists():
                    ready = elapsed * 1000
                phase_path = output.with_suffix(output.suffix + '.phase')
                phase = phase_path.read_text(encoding='utf8') if phase_path.exists() else 'warmup'
                try:
                    tree = [parent, *parent.children(recursive=True)]
                except psutil.NoSuchProcess:
                    break
                rss = private = cpu = 0
                for child in tree:
                    try:
                        memory = child.memory_info()
                        rss += memory.rss
                        private += getattr(memory, 'private', 0)
                        times = child.cpu_times()
                        cpu += times.user + times.system
                    except psutil.Error:
                        pass
                samples.append(dict(seconds=elapsed, phase=phase, rss=rss, private=private,
                                    cpu=cpu, processes=len(tree)))
                time.sleep(.05)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
    if process.returncode:
        raise RuntimeError(f'Benchmark failed ({process.returncode}): {output.with_suffix(".console.txt")}')
    result = json.loads(output.read_text(encoding='utf8'))
    result['external'] = dict(launch_to_first_image_ms=ready, max_processes=max(row['processes'] for row in samples),
                              peak_rss_mib=max(row['rss'] for row in samples)/1024**2,
                              peak_private_mib=max(row['private'] for row in samples)/1024**2)
    for phase in ('idle', 'update'):
        selected = [row for row in samples if row['phase'] == phase]
        result['external'][phase + '_rss_mib'] = statistics.median(row['rss'] for row in selected)/1024**2
        result['external'][phase + '_private_mib'] = statistics.median(row['private'] for row in selected)/1024**2
        result['external'][phase + '_cpu_percent_tree'] = 100*(selected[-1]['cpu']-selected[0]['cpu'])/(selected[-1]['seconds']-selected[0]['seconds'])
        result['external'][phase + '_processes'] = max(row['processes'] for row in selected)
    result['external']['samples'] = samples
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt-root', type=Path, required=True)
    parser.add_argument('--qt-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--workload', choices=('damage', 'combo'), default='damage')
    parser.add_argument('--warmup-frames', type=int, default=400,
                        help='20 Hz changing snapshots before the measured 200 frames; 0 retains the cold-update comparison')
    args = parser.parse_args()
    args.qt_root = args.qt_root.resolve()
    sys.path.insert(0, str(args.qt_root/'_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    dll_handles = configure_paths(args.qt_root)
    import psutil
    args.output.mkdir(parents=True, exist_ok=True)
    keys = ('chr_0004_pelica', 'chr_0005_chen', 'chr_0003_endminf', 'chr_0006_wolfgd')
    messages = [dict(type='analysis_summary', schema_version=1, stream_id='benchmark', sequence=sequence,
                     snapshot=dict(battle=dict(total_damage=100000+sequence*100, total_dps=10000, duration_ms=10000+sequence*50),
                                   participants=[dict(character_key=key, character_name=key, total_damage=25000+sequence*25,
                                                      total_rd=25000+sequence*25, crit_rate=.25) for key in keys],
                                   snapshot_quality=dict(status='verified'))) for sequence in range(201 + args.warmup_frames)]
    if args.workload == 'combo':
        messages = [dict(type='combo_snapshot', schema_version=2, stream_id='benchmark', sequence=sequence,
                         snapshot=dict(status='观测中', slots=[
                             dict(slot=index, character_key=key, display_name=key,
                                  status='ready' if (sequence+index*20) % 101 == 100 else 'cooldown',
                                  progress=((sequence+index*20) % 101)/100,
                                  estimated_remaining_ms=(100-(sequence+index*20) % 101)*150)
                             for index, key in enumerate(keys)])) for sequence in range(201 + args.warmup_frames)]
    snapshots = args.output.resolve() / 'snapshots.json'
    snapshots.write_text(json.dumps(messages, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    snapshot_hash = hashlib.sha256(snapshots.read_bytes()).hexdigest()
    environment = dict(os.environ, DOTNET_ROOT=str(ROOT.parent/'.toolchains/dotnet'))
    inputs = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
              for base, pattern in ((ROOT/'_internal/dotnet', '*.cs'),
                                    (args.qt_root/'_internal/src/endfield_pcap/overlays', '*.py'))
              for path in base.rglob(pattern) if not {'bin', 'obj', '__pycache__'}.intersection(path.parts)}
    inputs.update({str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (Path(__file__), ROOT/'_development/tools/benchmark_native_overlays.py', args.desktop)})
    inputs.update({str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in desktop_runtime_directory(args.desktop).iterdir() if path.suffix.lower() in ('.dll', '.json')})
    inputs[str(args.qt_python.resolve())] = hashlib.sha256(args.qt_python.read_bytes()).hexdigest()
    for key in keys:
        relative = Path('_internal/data/ui/characters') / (key + '.png')
        portraits = [base / relative for base in (ROOT, args.qt_root)]
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in portraits]
        if hashes[0] != hashes[1]:
            raise RuntimeError(f'Qt and C# use different portrait resources: {key}')
        inputs.update({str(path.resolve()): digest for path, digest in zip(portraits, hashes)})
    (args.output/'inputs.json').write_text(json.dumps(inputs, indent=2), encoding='utf8')
    rounds = []
    for number in range(args.rounds):
        commands = {
            'qt': [str(args.qt_python.resolve()), '-B', str(ROOT/'_development/tools/benchmark_native_overlays.py'),
                   '--root', str(args.qt_root.resolve()), '--platform', 'windows', '--snapshots', str(snapshots),
                   '--warmup-frames', str(args.warmup_frames)],
            'csharp': [str(args.desktop.resolve()), '--benchmark-overlays', str(snapshots)]}
        for name in (('qt', 'csharp') if number % 2 == 0 else ('csharp', 'qt')):
            output = (args.output/f'{name}-{number+1}.json').resolve()
            command = commands[name] + (['--output', str(output)] if name == 'qt' else [str(output), str(args.warmup_frames)])
            result = measure(command, output, environment, psutil)
            if result.get('input_sha256') != snapshot_hash or result.get('prepared_snapshots') != len(messages):
                raise RuntimeError(f'{name} did not use the shared prepared workload')
            active = 'damage' if args.workload == 'damage' else 'combo_skill'
            if result.get('warmup_frames') != args.warmup_frames or result.get('rendering', {}).get(active, {}).get('frames') != 200:
                raise RuntimeError(f'{name} did not paint every submitted {active} snapshot')
            if not 19.5 <= result.get('actual_update_hz', 0) <= 20.5:
                raise RuntimeError(f'{name} did not sustain the requested 20 Hz update rate')
            if any(result.get('rendering', {}).get(module, {}).get('frames') != 0 for module in ('damage', 'combo_skill', 'uid_mask') if module != active):
                raise RuntimeError(f'{name} repainted unchanged windows')
            rounds.append(dict(implementation=name, round=number+1, result=result))
            print(name, number+1, {key: result[key] for key in ('rss_mib', 'idle_cpu_percent', 'update_cpu_percent', 'latency_p50_ms')}, flush=True)
    summary = {}
    for name in commands:
        results = [row['result'] for row in rounds if row['implementation'] == name]
        summary[name] = {key: statistics.median(row[key] for row in results)
                         for key in ('rss_mib', 'idle_cpu_percent', 'update_cpu_percent', 'latency_p50_ms', 'latency_p95_ms', 'apply_p50_ms', 'apply_total_ms', 'update_seconds', 'actual_update_hz')}
        summary[name]['external'] = {key: statistics.median(row['external'][key] for row in results)
                                     for key in results[0]['external'] if key != 'samples'}
        summary[name]['rendering'] = {module: {key: statistics.median(row['rendering'][module][key] for row in results)
                                               for key in results[0]['rendering'][module]}
                                     for module in results[0]['rendering']}
        summary[name]['dimensions'] = {key: results[0][key] for key in ('actual_dimensions', 'natural_dimensions', 'dpi_scales', 'physical_image_dimensions')}
        summary[name]['render_backends'] = results[0].get('render_backends', {'all': 'Qt native paint event'})
        for result in results:
            if any(result[key] != results[0][key] for key in ('actual_dimensions', 'dpi_scales', 'physical_image_dimensions')):
                raise RuntimeError(f'{name} dimensions or DPI changed between rounds')
    for key in ('actual_dimensions', 'dpi_scales', 'physical_image_dimensions'):
        if summary['qt']['dimensions'][key] != summary['csharp']['dimensions'][key]:
            raise RuntimeError(f'Qt and C# used different {key}')
    unchanged = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected for path, expected in inputs.items())
    summary['workload'] = dict(type=args.workload, input_sha256=snapshot_hash, prepared_snapshots=len(messages), source_unchanged=unchanged,
                               warmup_frames=args.warmup_frames, measured_frames=200,
                               limitations=['Qt paint event completion and C# native drawing submission are separate CPU-side endpoints; excludes GPU completion, physical presentation and OBS',
                                            'Same window dimensions; internal natural layout dimensions are recorded separately',
                                            'CPU is measured for the full process tree as percent of one core'])
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    if not unchanged:
        raise RuntimeError('Benchmark inputs changed during measurement')


if __name__ == '__main__':
    main()
