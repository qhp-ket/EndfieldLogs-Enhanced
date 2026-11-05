"""同机串行比较公开合成历史、长报告及原生界面；详细输出留在验证目录。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

import benchmark_dotnet_sessions as sessions
from verify_benchmark_identity import desktop_runtime_directory, verify_desktop_identity

ROOT = Path(__file__).resolve().parents[2]
WINDOW_PROTOCOL = 'EndfieldLogs.InterfaceBenchmark.NoInputWindows.v1'


def require_non_interactive_desktop(desktop):
    # Compatibility marker in the CLR user-string heap. Reject older binaries
    # before starting them; actual loaded module identity is checked separately.
    assembly = desktop_runtime_directory(desktop) / 'EndfieldLogs-Enhanced.dll'
    if WINDOW_PROTOCOL.encode('utf-16-le') not in assembly.read_bytes():
        raise ValueError('Desktop does not support non-interactive benchmark windows; rebuild it before measuring')


def interface_controls(config):
    """Use explicit appearance and the same scroll workload as the WPF worker."""
    if config.get('main_window_path') or config.get('live_window_path'):
        raise ValueError('Integrated product diagnostics require a separate harness; this paired worker uses non-interactive page windows')
    if config.get('history_cell_probe') or config.get('history_layout_probe'):
        raise ValueError('Table-only WPF probes cannot be paired with the Qt record list; run the probe standalone')
    theme = config.get('theme', 'light')
    if theme not in ('light', 'dark'):
        raise ValueError('Interface benchmarks require an explicit light or dark theme')
    font = config.get('font_percent', 100)
    steps = config.get('history_scroll_steps', 20)
    if type(font) is not int or not 80 <= font <= 180:
        raise ValueError('font_percent must be an integer from 80 to 180')
    if type(steps) is not int or not 20 <= steps <= 2000:
        raise ValueError('history_scroll_steps must be an integer from 20 to 2000')
    history_only = config.get('history_only', False)
    if type(history_only) is not bool:
        raise ValueError('history_only must be a boolean')
    return dict(theme=theme, font_percent=font, history_scroll_steps=steps, history_only=history_only)


def history_scroll_targets(count, steps):
    if type(count) is not int or count < 1:
        raise ValueError('History benchmark requires at least one indexed record')
    # C# uses a cast to int, rather than nearest-integer rounding, at twenty stops.
    return [int((count - 1) * (step % 20) / 19) for step in range(steps)]


def history_display_controls(config):
    value = config.get('history_display')
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'viewport_dip', 'row_min_height_dip'}:
        raise ValueError('history_display requires viewport_dip and row_min_height_dip')
    size, height = value['viewport_dip'], value['row_min_height_dip']
    if (not isinstance(size, list) or len(size) != 2 or any(type(item) is not int for item in size)
            or not 400 <= size[0] <= 1000 or not 300 <= size[1] <= 600
            or type(height) is not int or not 32 <= height <= 200):
        raise ValueError('History viewport must be 400–1000 by 300–600 DIP; row minimum 32–200 DIP')
    return dict(viewport_dip=list(size), row_min_height_dip=height)


def configure_qt_history_display(page, display, app):
    from PySide6.QtCore import QSize, Qt

    table = page.record_list
    width, height = display['viewport_dip']
    natural = [table.sizeHintForRow(index) for index in range(table.count())]
    table.setMinimumSize(0, 0)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setFixedSize(width + 24, height + 8)
    for _ in range(3):
        app.processEvents()
        table.setFixedSize(table.width() + width - table.viewport().width(),
                           table.height() + height - table.viewport().height())
    for index, original_height in enumerate(natural):
        item = table.item(index)
        desired = max(original_height, display['row_min_height_dip'])
        item.setSizeHint(QSize(width, desired))
        # Preserve the production delegate's border margins; sizeHint includes them.
        actual = table.sizeHintForRow(index)
        if actual != desired:
            item.setSizeHint(QSize(width, max(1, desired + desired - actual)))
    page.container.layout().activate()
    page.container.adjustSize()
    for _ in range(3):
        app.processEvents()
        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
    app.processEvents()
    return dict(natural_row_min_dip=min(natural), natural_row_max_dip=max(natural))


def qt_history_geometry(table, target, page):
    from PySide6.QtGui import QFontInfo, QFontMetrics

    viewport = table.viewport()
    clip = viewport.visibleRegion().boundingRect()
    if clip.isEmpty():
        raise ValueError('History viewport is completely clipped')
    dpi = viewport.devicePixelRatioF()
    rows = []
    for index in range(table.count()):
        item = table.item(index)
        bounds = table.visualItemRect(item)
        if not bounds.intersects(clip):
            continue
        font = QFontInfo(item.font().resolve(table.font()))
        rows.append(dict(index=index, height_px=bounds.height() * dpi,
                         fully_visible=clip.contains(bounds), text_lines=item.text().splitlines(),
                         font_family=font.family(), font_size_px=font.pixelSize() * dpi,
                         text_fits_row=QFontMetrics(item.font().resolve(table.font())).height() * len(item.text().splitlines()) <= bounds.height()))
    return dict(target=target, dpi_scale=[dpi, dpi], page_client_px=[page.width() * dpi, page.height() * dpi],
                viewport_px=[clip.width() * dpi, clip.height() * dpi], rows=rows)


def validate_history_comparison(qt, csharp):
    """Reject unlike display workloads before producing performance summaries."""
    import math

    issues = []
    if qt.get('history_display') != csharp.get('history_display'):
        issues.append('history display controls differ')
    counts = [row.get('history_records') for row in (qt, csharp)]
    if any(type(count) is not int or count < 1 for count in counts):
        return ['both workers must report a positive history record count']
    if qt.get('history_records') != csharp.get('history_records'):
        issues.append('history record counts differ')
    samples = [row.get('history_geometry_samples') for row in (qt, csharp)]
    if any(not isinstance(value, list) or len(value) != 20 for value in samples):
        return issues + ['both workers must report twenty history geometry samples']
    for stop, (left, right) in enumerate(zip(*samples)):
        prefix = f'history stop {stop}: '
        if not isinstance(left, dict) or not isinstance(right, dict):
            issues.append(prefix + 'geometry sample missing')
            continue
        if (left.get('target') != history_scroll_targets(counts[0], 20)[stop]
                or right.get('target') != history_scroll_targets(counts[1], 20)[stop]):
            issues.append(prefix + 'scroll targets differ')
        for field, tolerance in (('dpi_scale', 1e-6), ('page_client_px', 1), ('viewport_px', 1)):
            values = (left.get(field), right.get(field))
            if any(not isinstance(value, list) or len(value) != 2 for value in values):
                issues.append(prefix + field + ' missing')
            elif any(type(a) not in (int, float) or type(b) not in (int, float)
                     or not math.isfinite(a) or not math.isfinite(b) or a <= 0 or b <= 0
                     or abs(a - b) > tolerance for a, b in zip(*values)):
                issues.append(prefix + field + ' differs')
        rows = (left.get('rows'), right.get('rows'))
        if any(not isinstance(value, list) or not value for value in rows):
            issues.append(prefix + 'visible record rows missing')
            continue
        if any(not isinstance(row, dict) or type(row.get('index')) is not int
               or not 0 <= row['index'] < count or type(row.get('fully_visible')) is not bool
               or not isinstance(row.get('font_family'), str) or not row['font_family'].strip()
               for count, items in zip(counts, rows) for row in items):
            issues.append(prefix + 'visible row metadata missing')
            continue
        if [row.get('index') for row in rows[0]] != [row.get('index') for row in rows[1]]:
            issues.append(prefix + 'visible row indices differ')
            continue
        for a, b in zip(*rows):
            row_prefix = prefix + f'row {a.get("index")}: '
            if a.get('text_fits_row') is not True or b.get('text_fits_row') is not True:
                issues.append(row_prefix + 'text is vertically clipped or unverified')
            if a.get('fully_visible') != b.get('fully_visible'):
                issues.append(row_prefix + 'clipping differs')
            if a.get('font_family', '').casefold() != b.get('font_family', '').casefold():
                issues.append(row_prefix + 'font families differ')
            for field in ('height_px', 'font_size_px'):
                av, bv = a.get(field), b.get(field)
                if (type(av) not in (int, float) or type(bv) not in (int, float)
                        or not math.isfinite(av) or not math.isfinite(bv) or av <= 0 or bv <= 0 or abs(av - bv) > 1):
                    issues.append(row_prefix + field + ' differs')
            texts = (a.get('text_lines'), b.get('text_lines'))
            if any(not isinstance(lines, list) or len(lines) != 2
                   or any(not isinstance(text, str) for text in lines) for lines in texts):
                issues.append(row_prefix + 'two rendered text lines required')
            elif [' '.join(text.split()) for text in texts[0]] != [' '.join(text.split()) for text in texts[1]]:
                issues.append(row_prefix + 'displayed information differs')
    return issues


def prepare_qt_benchmark_window(window):
    """Set input protection before native creation/show; preserve widget rendering."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import Qt

    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    window.setWindowFlag(Qt.WindowType.WindowTransparentForInput)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnBottomHint)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.EnableWindow.restype = wintypes.BOOL
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetCapture.restype = wintypes.HWND
    handle = int(window.winId())
    if user32.GetWindowLongPtrW(handle, -20) & 0x08000020 != 0x08000020:
        raise RuntimeError('Qt benchmark window did not apply input-transparent/no-activate styles')
    user32.EnableWindow(handle, False)

    def check():
        process = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(process))
        if process.value == os.getpid() or user32.GetCapture():
            raise RuntimeError('Interface benchmark took foreground focus or captured input')

    return check


def summarize(results, history_only):
    def percentile(values, percent):
        ordered = sorted(values)
        position = (len(ordered) - 1) * percent
        lower = int(position)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)

    fields = ['history_index_ms', 'history_bind_ms']
    actions = ['history_scroll']
    if not history_only:
        fields += ['long_report_analysis_ms', 'analysis_construct_ms', 'analysis_first_display_ms',
                   'timeline_paint_ms', 'timeline_zoom_ms', 'timeline_zoom_restore_ms',
                   'skills_page_ms', 'enemy_page_ms', 'timeline_extent', 'timeline_viewport_width']
        actions += ['timeline_scroll', 'timeline_reference']
    summary = {}
    for name, rounds in results.items():
        comparable = [key for key in fields if key != 'history_bind_ms' or not any(row.get('history_display') for row in rounds)]
        summary[name] = {key: statistics.median(row[key] for row in rounds) for key in comparable}
        if any(row.get('history_display') for row in rounds):
            summary[name]['history_display'] = rounds[0]['history_display']
            summary[name]['history_bind_comparable'] = False
        for action in actions:
            summary[name][action + '_p50_ms'] = statistics.median(statistics.median(row[action + '_ms']) for row in rounds)
            summary[name][action + '_p95_ms'] = statistics.median(percentile(row[action + '_ms'], .95) for row in rounds)
        summary[name]['peak_rss_mib'] = statistics.median(row['external']['peak_rss_mib'] for row in rounds)
    return summary


def qt_worker(args):
    handles = sessions.configure(args.qt_root)
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme
    from endfield_pcap.history.index import HistoryIndex
    from endfield_pcap.history.importer import trace_record_snapshot
    from endfield_pcap.gui.pages.history.view import BattleLogPage
    from endfield_pcap.gui.battle.detail import BattleDetailDialog
    from endfield_pcap.application.settings import BattleDisplaySettings
    from endfield_pcap.gui.shared.typography import apply_fonts
    config = json.loads(args.input.read_text(encoding='utf8'))
    controls = interface_controls(config)
    display = history_display_controls(config)
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei UI', 10))
    setTheme(Theme.DARK if controls['theme'] == 'dark' else Theme.LIGHT)
    result = dict(boundary='actual Qt widgets; processEvents/repaint completion, excludes physical scanout',
                  controls=controls, no_input_window=True, history_display=display)
    input_checks = []

    def measure(action, target=None):
        started = time.perf_counter()
        value = action()
        if target is not None:
            # Flush this update once, before queued update events can already paint it.
            target.repaint()
        app.processEvents()
        elapsed = (time.perf_counter() - started) * 1000
        for check in input_checks:
            check()
        return elapsed, value

    with tempfile.TemporaryDirectory(prefix='endfield-qt-interface-') as directory:
        index = HistoryIndex(Path(directory))
        page = BattleLogPage()
        apply_fonts(page, controls['font_percent'] / 100)
        page.resize(1200, 800)
        input_checks.append(prepare_qt_benchmark_window(page))
        page.show()
        app.processEvents()
        input_checks[-1]()
        # Match HistoryController/HistoryPresenter: the production list is newest first.
        result['history_index_ms'], records = measure(lambda: sorted(index.records(Path(config['history']), trace=True),
                                                                     key=lambda record: record.started_at_ms, reverse=True))
        result['history_bind_ms'], _ = measure(lambda: page.set_records(records), page)
        result['history_records'] = len(records)
        if display:
            result['history_display_setup'] = configure_qt_history_display(page, display, app)
            input_checks[-1]()
        targets = history_scroll_targets(len(records), controls['history_scroll_steps'])
        result['history_scroll_targets'] = targets
        result['history_scroll_ms'] = []
        for position in targets:
            row = page.record_list.item(position)
            elapsed, _ = measure(lambda: page.record_list.scrollToItem(row), page.record_list.viewport())
            result['history_scroll_ms'].append(elapsed)
        result['history_row_heights'] = sorted({page.record_list.visualItemRect(page.record_list.item(position)).height() for position in set(targets)})
        result['font_size'] = page.record_list.fontInfo().pixelSize()
        result['history_viewport_px'] = [page.record_list.viewport().width() * page.devicePixelRatioF(),
                                         page.record_list.viewport().height() * page.devicePixelRatioF()]
        result['history_geometry_samples'] = []
        for position in history_scroll_targets(len(records), 20):
            page.record_list.scrollToItem(page.record_list.item(position))
            app.processEvents()
            input_checks[-1]()
            result['history_geometry_samples'].append(qt_history_geometry(page.record_list, position, page))
        if controls['history_only']:
            result['passed'] = all(not record.analysis_loaded for record in records)
            page.close()
            app.processEvents()
            args.result.write_text(json.dumps(result, indent=2), encoding='utf8')
            return
        long_record, = index.records(Path(config['live']), trace=True)
        result['long_report_analysis_ms'], report = measure(lambda: trace_record_snapshot(long_record))
        result['analysis_construct_ms'], dialog = measure(lambda: BattleDetailDialog(report, '公开合成长报告',
            display_settings=BattleDisplaySettings(gui_font_percent=config.get('font_percent', 100))))
        dialog.resize(1200, 800)
        input_checks.append(prepare_qt_benchmark_window(dialog))
        result['analysis_first_display_ms'], _ = measure(dialog.show, dialog)
        timeline = dialog.timeline
        result['default_fits_viewport'] = timeline.horizontalScrollBar().maximum() < 40
        zoom = float(config.get('zoom', 8))
        measure(lambda: dialog.zoom_slider.setValue(round(zoom * 100)), dialog)
        if 'label_width' in config:
            timeline._role_column_width = config['label_width'] * 17 / 30
            timeline._track_column_width = config['label_width'] - timeline._role_column_width
            timeline.render_timeline()
            app.processEvents()
        if 'plot_width' in config:
            timeline._zoom = config['plot_width'] / max(240, timeline.viewport().width() - timeline.LEFT - 24)
            timeline.render_timeline()
            app.processEvents()
        result['timeline_total_marks'] = len(timeline._blocks)
        result['timeline_extent'] = timeline.sceneRect().width()
        result['timeline_label_width'] = timeline.LEFT
        result['timeline_plot_width'] = timeline._time_extent[2]
        result['timeline_viewport_width'] = timeline.viewport().width()
        result['timeline_paint_ms'], _ = measure(timeline.viewport().update, timeline.viewport())
        result['timeline_scroll_ms'] = []
        for step in range(20):
            def move():
                timeline.horizontalScrollBar().setValue(round(timeline.horizontalScrollBar().maximum() * step / 19))
                timeline._hover_ms = report['battle']['duration_ms'] * step / 19
                timeline.viewport().update()
            elapsed, _ = measure(move, timeline.viewport())
            result['timeline_scroll_ms'].append(elapsed)
        result['timeline_reference_ms'] = []
        for step in range(100):
            def reference():
                timeline._hover_ms = report['battle']['duration_ms'] * (step % 20) / 19
                timeline.viewport().update()
            elapsed, _ = measure(reference, timeline.viewport())
            result['timeline_reference_ms'].append(elapsed)
        result['timeline_zoom_ms'], _ = measure(lambda: dialog.zoom_slider.setValue(200), dialog)
        result['timeline_zoom_restore_ms'], _ = measure(lambda: dialog.zoom_slider.setValue(100), dialog)
        result['skills_page_ms'], _ = measure(lambda: dialog.tabs.setCurrentIndex(1), dialog)
        result['enemy_page_ms'], _ = measure(lambda: dialog.tabs.setCurrentIndex(2), dialog)
        result['rdmg_default'] = dialog.curve_combo.currentData() == 'rdmg'
        result['passed'] = all(not row.analysis_loaded for row in records) and result['rdmg_default']
        dialog.grab().save(str(args.result.with_suffix('.png')))
        dialog.close()
        page.close()
        app.processEvents()
    args.result.write_text(json.dumps(result, indent=2), encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qt-root', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--desktop', type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--qt-worker', action='store_true')
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    args.qt_root = args.qt_root.resolve()
    if args.qt_worker:
        return qt_worker(args)
    if args.output is None or args.desktop is None or args.rounds <= 0:
        parser.error('--output, --desktop and positive --rounds required')
    args.output = args.output.resolve()
    config = args.input.resolve()
    settings = json.loads(config.read_text(encoding='utf8'))
    controls = interface_controls(settings)
    history_display_controls(settings)
    require_non_interactive_desktop(args.desktop)
    args.output.mkdir(parents=True, exist_ok=False)
    handles = sessions.configure(args.qt_root)
    import psutil
    environment = dict(os.environ, DOTNET_ROOT=str(ROOT.parent / '.toolchains/dotnet'))
    sources = [*Path(__file__).resolve().parent.glob('benchmark_dotnet*interface*.py')]
    sources += list(desktop_runtime_directory(args.desktop).glob('EndfieldLogs*.dll'))
    sources += [path for path in (ROOT / '_internal/dotnet/Desktop').rglob('*.cs')
                if not {'bin', 'obj'}.intersection(path.parts)]
    sources += list((args.qt_root / '_internal/src/endfield_pcap/gui').rglob('*.py'))
    sources += [Path(settings[key]) for key in (('history',) if controls['history_only'] else ('history', 'live'))]
    (args.output / 'source-inputs.json').write_text(json.dumps({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}, indent=2), encoding='utf8')
    results = {'qt': [], 'csharp': []}
    for number in range(args.rounds):
        for name in (('qt', 'csharp') if number % 2 == 0 else ('csharp', 'qt')):
            output = args.output / f'{name}-{number+1}.json'
            command = ([sys.executable, '-B', str(Path(__file__).resolve()), '--qt-worker', '--qt-root', str(args.qt_root),
                        '--input', str(config), '--result', str(output)] if name == 'qt' else
                       [str(args.desktop.resolve()), '--benchmark-interface', str(config), str(output)])
            result = sessions.measure(command, output, environment, psutil)
            if name == 'csharp':
                verify_desktop_identity(result, args.desktop)
                output.write_text(json.dumps(result, indent=2), encoding='utf8')
            if not result.get('passed'):
                raise RuntimeError('Interface functional checks failed: ' + str(output))
            if result.get('no_input_window') is not True:
                raise RuntimeError('Interface worker does not support windows without input: ' + str(output))
            if name == 'csharp' and result.get('window_protocol') != WINDOW_PROTOCOL:
                raise RuntimeError('Interface worker window protocol mismatch: ' + str(output))
            for setting, measured in (('plot_width', 'timeline_plot_width'), ('label_width', 'timeline_label_width')):
                if not controls['history_only'] and setting in settings and abs(result[measured] - settings[setting]) > 1:
                    raise RuntimeError(f'{name} did not use the controlled {setting}: {result[measured]}')
            if len(result['history_scroll_ms']) != controls['history_scroll_steps']:
                raise RuntimeError(f'{name} did not use the controlled history scroll count')
            results[name].append(result)
            action = 'history_scroll_ms' if controls['history_only'] else 'timeline_scroll_ms'
            print(name, number+1, 'scroll median ms', statistics.median(result[action]),
                  'RSS MiB', result['external']['peak_rss_mib'], flush=True)
        issues = validate_history_comparison(results['qt'][-1], results['csharp'][-1])
        comparison = dict(passed=not issues, issues=issues)
        (args.output / f'history-comparison-{number+1}.json').write_text(json.dumps(comparison, indent=2), encoding='utf8')
        if issues:
            raise RuntimeError('History display workloads differ; performance summary rejected. See history-comparison-' + str(number+1) + '.json')
    summary = summarize(results, controls['history_only'])
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
