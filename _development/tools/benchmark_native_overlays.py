"""Measure a synthetic three-window workload, including the entire process tree."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', choices=('windows', 'offscreen'), default='offscreen')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    dll_handles = configure_paths(ROOT)
    os.environ['QT_QPA_PLATFORM'] = args.platform
    import psutil
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from endfield_pcap.gui.config import default_overlay_entries
    from endfield_pcap.overlays.manager import OverlayManager

    app = QApplication([])
    manager = OverlayManager(1, use_in_process_snapshots=True)
    manager.sync_entries([replace(entry, enabled=True) for entry in default_overlay_entries()])
    app.processEvents()
    sizes = {'damage': (800, 380), 'combo_skill': (540, 180), 'uid_mask': (220, 32)}
    for window in manager._windows.values():
        if window.content_size:
            # Hold the benchmark dimensions constant while data changes.
            window.content_size.timer.stop()
            window.canvas.naturalSizeChanged.disconnect(window.content_size.fit)
        window.resize(*sizes[window.entry.source_value])
    damage = next(w for w in manager._windows.values() if w.entry.source_value == 'damage')
    keys = ('chr_0004_pelica', 'chr_0005_chen', 'chr_0003_endminf', 'chr_0006_wolfgd')

    def send(sequence):
        snapshot = dict(battle=dict(total_damage=100000+sequence*100, total_dps=10000,
                                   duration_ms=10000+sequence*50),
                        participants=[dict(character_key=key, character_name=key,
                                           total_damage=25000+sequence*25,
                                           total_rd=25000+sequence*25, crit_rate=.25) for key in keys],
                        snapshot_quality=dict(status='verified'))
        manager.apply_analysis_summary(dict(type='analysis_summary', schema_version=1,
                                            stream_id='benchmark', sequence=sequence, snapshot=snapshot))

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
        QTest.qWait(1800)
        first, started = sample(), time.perf_counter()
        QTest.qWait(3000)
        idle = sample()
        idle_cpu = 100*(idle['cpu']-first['cpu'])/(time.perf_counter()-started)
        latencies = []
        started = time.perf_counter()
        for sequence in range(1, 61):
            submitted = time.perf_counter()
            send(sequence)
            app.processEvents()
            damage.canvas.grab()
            latencies.append(1000*(time.perf_counter()-submitted))
            QTest.qWait(max(0, round(50-1000*(time.perf_counter()-submitted))))
        final = sample()
        result = dict(platform=args.platform, windows=len(manager._windows), dimensions=sizes,
                      rss_mib=final['rss']/1024**2, processes=final['processes'],
                      idle_cpu_percent=idle_cpu,
                      update_cpu_percent=100*(final['cpu']-idle['cpu'])/(time.perf_counter()-started),
                      latency_p50_ms=statistics.median(latencies),
                      latency_p95_ms=sorted(latencies)[56],
                      boundary='synthetic snapshot -> native backing image; 20 Hz, 4 participants; '
                               'CPU percent of one core; excludes physical scanout and capture/analysis')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf8')
        print(json.dumps(result, indent=2))
    finally:
        manager.close_all()
        app.processEvents()


if __name__ == '__main__':
    main()
