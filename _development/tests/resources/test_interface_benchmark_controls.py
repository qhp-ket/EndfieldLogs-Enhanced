"""Validate paired benchmark controls and summaries without importing Qt or launching a process."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from benchmark_dotnet_interface import history_scroll_targets, interface_controls, summarize, validate_history_comparison, history_display_controls


class InterfaceBenchmarkControlTests(unittest.TestCase):
    def test_appearance_and_history_workload_are_explicit(self):
        self.assertEqual(interface_controls({}), dict(theme='light', font_percent=100, history_scroll_steps=20, history_only=False))
        self.assertEqual(interface_controls(dict(theme='dark', font_percent=150, history_scroll_steps=40, history_only=True)),
                         dict(theme='dark', font_percent=150, history_scroll_steps=40, history_only=True))

    def test_rejects_ambiguous_or_incompatible_paired_controls(self):
        for config in ({'theme': 'system'}, {'font_percent': True}, {'font_percent': 79},
                       {'font_percent': 181}, {'font_percent': 115.0}, {'history_scroll_steps': True},
                       {'history_scroll_steps': 19}, {'history_scroll_steps': 2001},
                       {'history_only': 'true'}, {'history_cell_probe': True}, {'history_layout_probe': True}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                interface_controls(config)

    def test_integrated_paths_cannot_bypass_non_interactive_worker(self):
        for config in ({'main_window_path': True}, {'live_window_path': True}):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, 'separate harness'):
                interface_controls(config)

    def test_scroll_targets_match_wpf_truncation_and_repeat_all_twenty_stops(self):
        targets = history_scroll_targets(4, 40)
        self.assertEqual(len(targets), 40)
        self.assertEqual(targets[:20], targets[20:])
        # Nearest-integer rounding would pick row 1 at stop 4, and row 2 at stop 10.
        self.assertEqual([targets[i] for i in (0, 4, 7, 10, 13, 19)], [0, 0, 1, 1, 2, 3])
        self.assertEqual(history_scroll_targets(1, 20), [0] * 20)
        with self.assertRaises(ValueError):
            history_scroll_targets(0, 20)

    def test_history_only_summary_needs_no_report_or_timeline_results(self):
        rows = [dict(history_index_ms=number, history_bind_ms=number * 2,
                     history_scroll_ms=[1, 3], external={'peak_rss_mib': 50 + number}) for number in (1, 2, 9)]
        result = summarize({'qt': rows, 'csharp': rows}, history_only=True)
        self.assertEqual(result['qt']['history_index_ms'], 2)
        self.assertEqual(result['qt']['history_scroll_p50_ms'], 2)
        self.assertAlmostEqual(result['qt']['history_scroll_p95_ms'], 2.9)
        self.assertEqual(result['qt']['peak_rss_mib'], 52)
        self.assertNotIn('long_report_analysis_ms', result['qt'])
        self.assertFalse(any(key.startswith('timeline_') for key in result['qt']))

    def test_full_interface_summary_keeps_existing_timeline_metrics(self):
        row = dict(history_index_ms=1, history_bind_ms=2, history_scroll_ms=[1, 3],
                   timeline_scroll_ms=[2, 6], timeline_reference_ms=[1, 5], external={'peak_rss_mib': 50})
        for name in ('long_report_analysis_ms', 'analysis_construct_ms', 'analysis_first_display_ms',
                     'timeline_paint_ms', 'timeline_zoom_ms', 'timeline_zoom_restore_ms',
                     'skills_page_ms', 'enemy_page_ms', 'timeline_extent', 'timeline_viewport_width'):
            row[name] = 10
        result = summarize({'qt': [row], 'csharp': [row]}, history_only=False)
        self.assertEqual(result['qt']['timeline_scroll_p50_ms'], 4)
        self.assertAlmostEqual(result['qt']['timeline_reference_p95_ms'], 4.8)
        self.assertEqual(result['qt']['long_report_analysis_ms'], 10)


class HistoryComparisonTests(unittest.TestCase):
    def report(self):
        return dict(history_records=40, history_geometry_samples=[
            dict(target=target, dpi_scale=[1.75, 1.75], page_client_px=[2100, 1400], viewport_px=[900, 700],
                 rows=[dict(index=target, height_px=70, fully_visible=True, text_lines=['战斗名称', '待加载'],
                            font_family='Microsoft YaHei UI', font_size_px=24.5, text_fits_row=True)])
            for target in history_scroll_targets(40, 20)])

    def test_accepts_same_actual_workload_with_only_raster_rounding(self):
        qt, cs = self.report(), self.report()
        cs['history_geometry_samples'][0]['viewport_px'][0] += .5
        row = cs['history_geometry_samples'][0]['rows'][0]
        row['font_size_px'] += .5
        row['font_family'] = row['font_family'].upper()
        self.assertEqual(validate_history_comparison(qt, cs), [])

    def test_rejects_different_viewport_dpi_client_size_and_scroll_position(self):
        for field in ('viewport_px', 'dpi_scale', 'page_client_px', 'target'):
            with self.subTest(field=field):
                qt, cs = self.report(), self.report()
                sample = cs['history_geometry_samples'][9]
                if field == 'target':
                    sample[field] += 1
                else:
                    sample[field][0] += 2
                self.assertTrue(validate_history_comparison(qt, cs))

    def test_rejects_fewer_rows_smaller_text_clipping_or_missing_information(self):
        changes = [dict(height_px=50), dict(font_size_px=14), dict(font_family='Arial'),
                   dict(fully_visible=False), dict(text_lines=['战斗名称']),
                   dict(text_lines=['战斗名称', '另一种内容']), dict(index=2), dict(text_fits_row=False)]
        for change in changes:
            with self.subTest(change=change):
                qt, cs = self.report(), self.report()
                cs['history_geometry_samples'][0]['rows'][0].update(change)
                self.assertTrue(validate_history_comparison(qt, cs))
        qt, cs = self.report(), self.report()
        cs['history_geometry_samples'][0]['rows'].append(copy.deepcopy(cs['history_geometry_samples'][0]['rows'][0]))
        self.assertTrue(validate_history_comparison(qt, cs))

    def test_rejects_old_partial_or_invalid_measurements(self):
        for broken in ({}, {'history_records': 40}, {'history_records': None}, {'history_records': 0}):
            with self.subTest(broken=broken):
                self.assertTrue(validate_history_comparison(self.report(), broken))
        for field in ('index', 'font_family', 'font_size_px', 'text_lines', 'fully_visible'):
            with self.subTest(field=field):
                qt, cs = self.report(), self.report()
                del cs['history_geometry_samples'][0]['rows'][0][field]
                self.assertTrue(validate_history_comparison(qt, cs))
        for value in (float('nan'), float('inf'), -1):
            qt, cs = self.report(), self.report()
            cs['history_geometry_samples'][0]['viewport_px'][0] = value
            self.assertTrue(validate_history_comparison(qt, cs))

    def test_display_controls_validate_and_do_not_relabel_binding_as_comparable(self):
        display = dict(viewport_dip=[720, 448], row_min_height_dip=64)
        self.assertEqual(history_display_controls({'history_display': display}), display)
        self.assertIsNone(history_display_controls({}))
        for broken in (False, {}, dict(display, viewport_dip=[1, 2]), dict(display, row_min_height_dip=True)):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                history_display_controls({'history_display': broken})
        row = dict(history_index_ms=1, history_bind_ms=2, history_scroll_ms=[1, 2],
                   history_display=display, external={'peak_rss_mib': 50})
        result = summarize({'qt': [row], 'csharp': [row]}, history_only=True)
        self.assertFalse(result['qt']['history_bind_comparable'])
        self.assertNotIn('history_bind_ms', result['qt'])


if __name__ == '__main__':
    unittest.main()
