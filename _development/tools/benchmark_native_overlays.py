"""Measure a synthetic three-window workload, including the entire process tree."""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    launched = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', choices=('windows', 'offscreen'), default='offscreen')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--snapshots', type=Path)
    parser.add_argument('--warmup-frames', type=int, default=0)
    parser.add_argument('--theme', choices=('light', 'dark'), default='light')
    args = parser.parse_args()
    args.root = args.root.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.root / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    dll_handles = configure_paths(args.root)
    os.environ['QT_QPA_PLATFORM'] = args.platform
    import psutil
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from endfield_pcap.settings import default_overlay_entries
    from endfield_pcap.overlays.manager import OverlayManager
    from endfield_pcap.overlays import window as overlay_window

    original_canvas = overlay_window.OverlayCanvas
    rendering, window_types = {}, {}
    measuring = False

    class MeasuredCanvas(original_canvas):
        def paintEvent(self, event):
            started = time.perf_counter()
            super().paintEvent(event)
            if measuring:
                rendering[window_types[id(self)]].append(1000 * (time.perf_counter() - started))

    overlay_window.OverlayCanvas = MeasuredCanvas

    app = QApplication([])
    manager = OverlayManager(1, use_in_process_snapshots=True)
    manager.sync_entries([replace(entry, enabled=True, overlay_theme=args.theme) for entry in default_overlay_entries()])
    app.processEvents()
    sizes = {'damage': (800, 380), 'combo_skill': (540, 180), 'uid_mask': (220, 32)}
    for window in manager._windows.values():
        if window.content_size:
            # Hold the benchmark dimensions constant while data changes.
            window.content_size.timer.stop()
            window.canvas.naturalSizeChanged.disconnect(window.content_size.fit)
        window.resize(*sizes[window.entry.source_value])
    damage = next(w for w in manager._windows.values() if w.entry.source_value == 'damage')
    rendering = {window.entry.source_value: [] for window in manager._windows.values()}
    window_types = {id(window.canvas): window.entry.source_value for window in manager._windows.values()}
    keys = ('chr_0004_pelica', 'chr_0005_chen', 'chr_0003_endminf', 'chr_0006_wolfgd')

    def message(sequence):
        snapshot = dict(battle=dict(total_damage=100000+sequence*100, total_dps=10000,
                                   duration_ms=10000+sequence*50),
                        participants=[dict(character_key=key, character_name=key,
                                           total_damage=25000+sequence*25,
                                           total_rd=25000+sequence*25, crit_rate=.25) for key in keys],
                        snapshot_quality=dict(status='verified'))
        return dict(type='analysis_summary', schema_version=1,
                    stream_id='benchmark', sequence=sequence, snapshot=snapshot)

    input_bytes = args.snapshots.read_bytes() if args.snapshots else None
    messages = json.loads(input_bytes) if input_bytes is not None else [message(sequence) for sequence in range(201)]
    if args.warmup_frames < 0 or len(messages) < args.warmup_frames + 2:
        raise ValueError('The overlay workload requires a warmup and update snapshots')

    def send(sequence):
        payload = messages[sequence]
        for message in payload.get('messages', [payload]):
            if message['type'] == 'combo_snapshot':
                manager.apply_combo_snapshot(message)
            else:
                manager.apply_analysis_summary(message)

    process = psutil.Process()

    def sample():
        tree = [process, *process.children(recursive=True)]
        memory = cpu = 0
        for child in tree:
            try:
                memory += child.memory_info().rss
                times = child.cpu_times()
                cpu += times.user + times.system
            except psutil.Error:
                pass
        return dict(rss=memory, cpu=cpu, processes=len(tree))

    try:
        send(0)
        app.processEvents()
        damage.canvas.grab()
        ready_ms = 1000*(time.perf_counter()-launched)
        args.output.with_suffix(args.output.suffix+'.ready').write_text('ready', encoding='utf8')
        QTest.qWait(1800)
        warm_start, warm_clock = sample(), time.perf_counter()
        for sequence in range(1, args.warmup_frames + 1):
            submitted = time.perf_counter()
            send(sequence)
            app.processEvents()
            QTest.qWait(max(0, round(1000*(warm_clock + sequence*.05-time.perf_counter()))))
        if args.warmup_frames:
            QTest.qWait(2000)
        warm_end = sample()
        warm_seconds = time.perf_counter() - warm_clock
        first, started = sample(), time.perf_counter()
        args.output.with_suffix(args.output.suffix+'.phase').write_text('idle', encoding='utf8')
        QTest.qWait(3000)
        idle = sample()
        idle_cpu = 100*(idle['cpu']-first['cpu'])/(time.perf_counter()-started)
        latencies, apply_times = [], []
        measuring = True
        started = time.perf_counter()
        args.output.with_suffix(args.output.suffix+'.phase').write_text('update', encoding='utf8')
        for sequence in range(args.warmup_frames + 1, len(messages)):
            submitted = time.perf_counter()
            send(sequence)
            apply_times.append(1000 * (time.perf_counter() - submitted))
            app.processEvents()
            if any(window.canvas.paint_revision != window.canvas.layout_revision for window in manager._windows.values()):
                raise RuntimeError('Snapshot did not reach the native paint event')
            latencies.append(1000*(time.perf_counter()-submitted))
            QTest.qWait(max(0, round(1000*(started + (sequence-args.warmup_frames)*.05-time.perf_counter()))))
        final = sample()
        update_seconds = time.perf_counter()-started
        measuring = False
        args.output.with_suffix(args.output.suffix+'.phase').write_text('complete', encoding='utf8')
        physical_image = damage.canvas.grab()
        result = dict(platform=args.platform, theme=args.theme, windows=len(manager._windows), dimensions=sizes,
                      actual_dimensions={window.entry.source_value: [window.width(), window.height()] for window in manager._windows.values()},
                      natural_dimensions={window.entry.source_value: [window.canvas.natural_size.width(), window.canvas.natural_size.height()] for window in manager._windows.values()},
                      dpi_scales={window.entry.source_value: window.devicePixelRatioF() for window in manager._windows.values()},
                      physical_image_dimensions=[physical_image.width(), physical_image.height()],
                      first_backing_images_ms=ready_ms,
                      rss_mib=final['rss']/1024**2, processes=final['processes'],
                      idle_cpu_percent=idle_cpu,
                      update_cpu_percent=100*(final['cpu']-idle['cpu'])/update_seconds,
                      update_seconds=update_seconds, actual_update_hz=len(latencies)/update_seconds,
                      latency_p50_ms=statistics.median(latencies),
                      latency_p95_ms=sorted(latencies)[max(0, int(.95 * len(latencies)) - 1)],
                      apply_p50_ms=statistics.median(apply_times), apply_total_ms=sum(apply_times),
                      prepared_snapshots=len(messages),
                      warmup_frames=args.warmup_frames, warmup_seconds=warm_seconds,
                      warmup_cpu_ms=1000*(warm_end['cpu']-warm_start['cpu']),
                      input_sha256=hashlib.sha256(input_bytes).hexdigest() if input_bytes is not None else None,
                      rendering={key: dict(frames=len(times), paint_ms=sum(times)) for key, times in rendering.items()},
                      boundary='prepared snapshot -> native paint event completed; 20 Hz, 4 participants; '
                               'CPU percent of one core; excludes snapshot construction, physical scanout and capture/analysis')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf8')
        print(json.dumps(result, indent=2))
    finally:
        overlay_window.OverlayCanvas = original_canvas
        manager.close_all()
        app.processEvents()


if __name__ == '__main__':
    main()
