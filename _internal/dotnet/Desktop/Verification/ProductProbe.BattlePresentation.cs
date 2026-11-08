using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    private static async Task VerifyBattlePresentation(Application app, Window owner, SettingsStore settings, string output, Action<string, bool> check)
    {
        var small = WindowPlacement.Fit(new(-1024, -100, 640, 480), new(1200, 800), new(800, 500), new(4000, -1000));
        check("analysis_fit_small_secondary_work_area", small.Width == 600 && small.Height == 420 && small.Left >= -1024 && small.Right <= -384 && small.Top >= -100 && small.Bottom <= 380);
        var temporary = Directory.CreateTempSubdirectory("endfield-wpf-frames-");
        var path = Path.Combine(temporary.FullName, "data", "local_semantics", "skill_frame_rules.json"); Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, """{"schema_version":1,"frames_per_second":30,"skills":{"chr_0001_test_normal_skill":{"duration_frames":60,"exclusive_frames":10,"damage_windows":[{"start_frame":10,"end_frame":20,"conditional":true,"action":"HpDamage"}],"unplaced_damage_actions":["callback"]},"chr_0001_test_combo_skill":{"duration_frames":60},"chr_0001_test_ultimate_skill":{"duration_frames":60}}}""");
        var report = (EvidenceObject)EvidenceJson.Parse("""
            {"battle":{"duration_ms":5000,"dungeon_name":"展示配置验证"},"participants":[{"character_key":"chr_0001_test","character_name":"记录名","total_damage":100},{"character_key":"b","character_name":"另一角色","total_damage":2}],
             "casts":[{"character_key":"chr_0001_test","skill_key":"chr_0001_test_normal_skill","ts_ms_from_start":100},{"character_key":"chr_0001_test","skill_key":"chr_0001_test_combo_skill","ts_ms_from_start":1000,"end_ms_from_start":1400},{"character_key":"chr_0001_test","skill_key":"chr_0001_test_ultimate_skill","ts_ms_from_start":3000}],
             "timeline_events":[{"event_type":"damage","lane_type":"skill","event_key":"chr_0001_test_normal_skill","source_character_key":"chr_0001_test","ts_ms_from_start":500,"actual_start_ms_from_start":100,"value":90},{"event_type":"damage","lane_type":"skill","event_key":"chr_0001_test_combo_skill","source_character_key":"chr_0001_test","ts_ms_from_start":1100,"actual_start_ms_from_start":1000,"value":10}],
             "role_skill_stats":[{"character_key":"chr_0001_test","character_name":"记录名","skill_key":"chr_0001_test_normal_skill","skill_name":"完整战技名称","total_damage":90,"cast_count":3,"avg_damage":30,"max_damage":60},{"character_key":"chr_0001_test","character_name":"记录名","skill_key":"chr_0001_test_combo_skill","skill_name":"连携","total_damage":10,"cast_count":1,"avg_damage":10,"max_damage":10},{"character_key":"b","character_name":"另一角色","skill_key":"unknown","skill_name":"未知技能记录","total_damage":2,"cast_count":1,"avg_damage":2,"max_damage":2}]}
            """);
        var canonical = PythonSortedJson.Serialize(report);
        BattleAnalysisWindow window = new(report, settings, resources: new ResourceFiles(temporary.FullName)) { Owner = owner };
        try
        {
            window.Show(); await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle); window.UpdateLayout();
            var work = OverlayScreen.WorkArea(new WindowInteropHelper(window).Handle, VisualTreeHelper.GetDpi(window).DpiScaleX);
            check("analysis_initial_window_inside_monitor", window.Left >= work.Left - 1 && window.Top >= work.Top - 1 && window.Left + window.ActualWidth <= work.Right + 1 && window.Top + window.ActualHeight <= work.Bottom + 1);
            check("analysis_default_zoom_fits_window", window.Timeline.ActualWidth <= window.DiagramScroll.ViewportWidth + 1);
            var skill = window.Timeline.Marks.Single(mark => mark.Skill?.RawSkill == "chr_0001_test_normal_skill");
            var complete = window.Timeline.Marks.Single(mark => mark.Skill?.RawSkill == "chr_0001_test_combo_skill");
            var noHit = window.Timeline.Marks.Single(mark => mark.Skill?.RawSkill == "chr_0001_test_ultimate_skill");
            check("frame_fallback_default_off_and_complete_cast_wins", !window.Timeline.ShowFrameReference && window.Timeline.DisplayBounds(skill) == (100, 100) && complete.FrameReference is null);
            System.Windows.Threading.DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(20) };
            timer.Tick += (_, _) =>
            {
                var dialog = app.Windows.OfType<Window>().FirstOrDefault(candidate => candidate.Title == "显示设置"); if (dialog is null) return; timer.Stop();
                Descendants<CheckBox>(dialog).Single(box => Equals(box.Content, "固定起止配置回退")).IsChecked = true;
                Descendants<Button>(dialog).Single(button => Equals(button.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            };
            timer.Start(); try { Descendants<Button>(window).Single(button => Equals(button.Content, "显示设置")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); } finally { timer.Stop(); }
            window.UpdateLayout();
            check("display_panel_enables_exact_frame_fallback", window.Timeline.ShowFrameReference && window.Timeline.DisplayBounds(skill) == (500, 2500)
                && window.Timeline.DisplayBounds(complete) == (1000, 1400) && window.Timeline.DisplayBounds(noHit) == (3000, 3000)
                && Descendants<TextBlock>(window).Any(text => text.Text == "固定起止回退已开启" && text.IsVisible));
            check("fallback_keeps_logged_underline_and_raw_coordinates", window.Timeline.MarkAreas.Count(area => area.Mark == skill) >= 2 && skill.Start == 100 && skill.End == 100
                && BattleDetails.Description(skill, false).Contains("条件分支", StringComparison.Ordinal) && BattleDetails.Description(skill, true).Contains("未对齐实战时间", StringComparison.Ordinal));
            var rawBox = (TextBox)((TabItem)window.DetailsPages.Items[3]).Content;
            var overviewBox = (TextBox)((TabItem)window.DetailsPages.Items[0]).Content;
            var hitGrid = (DataGrid)((TabItem)window.DetailsPages.Items[2]).Content;
            window.Timeline.SelectMarks([skill]);
            check("collapsed_details_keep_selection_without_materializing_pages", !window.DetailsExpanded
                && rawBox.Text.Length == 0 && overviewBox.Text.Length == 0 && hitGrid.ItemsSource is null);
            window.SetDetails(true);
            check("opening_overview_materializes_only_visible_page", overviewBox.Text.Contains(skill.Name, StringComparison.Ordinal)
                && rawBox.Text.Length == 0 && hitGrid.ItemsSource is null);
            window.DetailsPages.SelectedIndex = 2;
            check("opening_hits_materializes_complete_selected_evidence", hitGrid.Items.OfType<BattleAnalysisWindow.HitRow>().Single().Damage == 90 && rawBox.Text.Length == 0);
            var inspected = hitGrid.Items.OfType<BattleAnalysisWindow.HitRow>().Single(); hitGrid.SelectedItem = inspected;
            check("hidden_raw_page_does_not_serialize_selected_hit", rawBox.Text.Length == 0);
            window.DetailsPages.SelectedIndex = 3;
            check("raw_tab_preserves_selected_hit_canonical_evidence", rawBox.Text == PythonSortedJson.Serialize(inspected.Evidence));
            window.SetDetails(false); window.Timeline.SelectMarks([complete]);
            check("closed_new_selection_drops_old_raw_text", rawBox.Text.Length == 0);
            window.SetDetails(true);
            check("reopened_raw_tab_uses_latest_selection", rawBox.Text == string.Join("\n\n", complete.Evidence.Distinct().Select(row => PythonSortedJson.Serialize(row))));
            window.DetailsPages.SelectedIndex = 0;
            window.Timeline.SelectMarks([skill]); window.SetDetails(true); window.UpdateLayout(); Screenshot(window, Path.ChangeExtension(output, ".frame-reference.png")); window.SetDetails(false);
            var metric = Descendants<ComboBox>(window).Single(combo => combo.Items.Contains("累计 rDMG"));
            metric.SelectedIndex = 1; window.UpdateLayout();
            var curveDamage = window.Plot.Series.Points.Last().Values.Values.Sum();
            var zoom = Descendants<Slider>(window).Single(slider => slider.Maximum == 10);
            window.Timeline.SetFrameReference(false);
            zoom.Value = 8; window.UpdateLayout();
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
            check("curve_zoom_preserves_values_and_metric", window.Plot.Series.Metric == "dmg" && curveDamage == 100
                && window.Plot.Series.Points.Last().Values.Values.Sum() == curveDamage);
            window.DiagramScroll.ScrollToHorizontalOffset(noHit.Start / window.Timeline.Duration * (window.Timeline.ActualWidth - window.Timeline.LabelWidth - 10) - 100);
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
            window.UpdateLayout();
            check("timeline_viewport_culls_drawing_keeps_all_evidence", window.Timeline.PinnedLabelLeft > 0
                && window.Timeline.MarkAreas.All(area => area.Mark != skill)
                && window.Timeline.MarkAreas.Any(area => area.Mark == noHit)
                && window.Timeline.Marks.Contains(skill) && canonical == PythonSortedJson.Serialize(report));
            metric.SelectedIndex = 3; window.UpdateLayout();
            check("curve_metric_switch_invalidates_previous_projection", window.Plot.Series.Metric == "dps"
                && window.Plot.Series.Points.Last().Values.Values.Sum() == 20);
            metric.SelectedIndex = 0; window.Timeline.SetFrameReference(true);
            Descendants<Button>(window).Single(button => Equals(button.Content, "适合窗口")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
            window.UpdateLayout();
            check("fit_button_resets_zoom_and_scroll", zoom.Value == 1 && window.DiagramScroll.HorizontalOffset == 0
                && window.Timeline.ActualWidth <= window.DiagramScroll.ViewportWidth + 1);
            metric.SelectedIndex = 1; window.UpdateLayout();
            await VerifyTimelineRendering(window, check);
            await VerifyInputViewport(report, check);
            metric.SelectedIndex = 0;
            var tabs = Descendants<TabControl>(window).First(); tabs.SelectedIndex = 1; window.UpdateLayout();
            var table = window.SkillsPage.Table;
            check("skill_composition_eight_columns_and_numeric_default_sort", table.Columns.Count == 8 && table.Items.OfType<SkillCompositionPage.SkillRow>().Select(row => row.Damage).SequenceEqual([90d, 10d, 2d])
                && table.Items.OfType<SkillCompositionPage.SkillRow>().First() is { Category: "战技", Count: 3, Percent: 90, Average: 30, Maximum: 60 });
            check("skill_composition_cached_portrait_and_full_tooltip", table.Items.OfType<SkillCompositionPage.SkillRow>().First() is { Portrait: not null } row && row.Tooltip.Contains("chr_0001_test_normal_skill", StringComparison.Ordinal));
            var sorted = CollectionViewSource.GetDefaultView(table.ItemsSource); sorted.SortDescriptions.Clear(); sorted.SortDescriptions.Add(new(nameof(SkillCompositionPage.SkillRow.Damage), ListSortDirection.Ascending));
            check("skill_composition_sort_uses_numbers", sorted.Cast<SkillCompositionPage.SkillRow>().Select(row => row.Damage).SequenceEqual([2d, 10d, 90d]));
            window.SkillsPage.Character.SelectedValue = "b"; window.UpdateLayout();
            check("skill_composition_filter_keeps_own_denominator", table.Items.Count == 1 && table.Items[0] is SkillCompositionPage.SkillRow { Owner: "b", Percent: 100 });
            window.SkillsPage.Character.SelectedValue = ""; window.UpdateLayout(); Screenshot(window, Path.ChangeExtension(output, ".skills.png"));
            check("presentation_never_mutates_canonical_report", canonical == PythonSortedJson.Serialize(report));
        }
        finally { window.Close(); temporary.Delete(true); }
    }
    private static async Task VerifyTimelineRendering(BattleAnalysisWindow window, Action<string, bool> check)
    {
        static byte[] Pixels(FrameworkElement view)
        {
            var width = (int)Math.Ceiling(view.ActualWidth); var height = (int)Math.Ceiling(view.ActualHeight);
            // Crop the actual window: attached controls retain their ancestor layout/scroll clips.
            var host = Window.GetWindow(view); var at = view.TranslatePoint(new(), host);
            RenderTargetBitmap bitmap = new((int)Math.Ceiling(host.ActualWidth), (int)Math.Ceiling(host.ActualHeight), 96, 96, PixelFormats.Pbgra32); bitmap.Render(host);
            byte[] bytes = new byte[width * height * 4];
            bitmap.CopyPixels(new Int32Rect((int)Math.Floor(at.X), (int)Math.Floor(at.Y), width, height), bytes, width * 4, 0); return bytes;
        }
        var timeline = window.Timeline; var plot = window.Plot;
        timeline.SetReference(null); plot.SetReference(null);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        var emptyTimeline = Pixels(timeline); var emptyPlot = Pixels(plot);
        var timelineRenders = timeline.ContentRenderCount; var curveRenders = plot.ContentRenderCount;
        var marks = timeline.MarkAreas.ToArray(); var spans = timeline.InputSpans.ToArray();
        var stamp = timeline.Duration * .4;
        timeline.SetReference(stamp); plot.SetReference(stamp);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        bool OnlyReference(FrameworkElement view, byte[] before, byte[] after, double top)
        {
            var width = (int)Math.Ceiling(view.ActualWidth); var changed = 0; var outside = 0; var minX = width; var maxX = -1; var minY = int.MaxValue; var maxY = -1;
            var x = timeline.LabelWidth + .4 * Math.Max(1, view.ActualWidth - timeline.LabelWidth - 10);
            for (var offset = 0; offset < before.Length; offset += 4)
                if (!before.AsSpan(offset, 4).SequenceEqual(after.AsSpan(offset, 4)))
                {
                    var px = offset / 4 % width; var py = offset / 4 / width;
                    var timeLabel = view is BattleTimeline && py < 48 && px >= x && px < x + 130;
                    if (!timeLabel && (Math.Abs(px - x) > 2 || py < top - 1)) outside++;
                    minX = Math.Min(minX, px); maxX = Math.Max(maxX, px); minY = Math.Min(minY, py); maxY = Math.Max(maxY, py);
                    changed++;
                }
            if (changed <= 5 || outside > 0) throw new InvalidOperationException($"{view.GetType().Name}: changed={changed}, outside={outside}, bounds={minX},{minY}–{maxX},{maxY}, expected x={x}, top={top}, actual={view.RenderSize}, duration={timeline.Duration}, offset={timeline.PinnedLabelLeft}, points={plot.Series.Points.Count}, drawing={(VisualTreeHelper.GetChild(view, 0) as DrawingVisual)?.Drawing?.Bounds}");
            return true;
        }
        check("reference_line_changes_only_its_pixels_in_timeline_and_curve",
            OnlyReference(timeline, emptyTimeline, Pixels(timeline), timeline.StickyHeaderTop + 30)
            && OnlyReference(plot, emptyPlot, Pixels(plot), 24));
        for (var step = 0; step < 30; step++) { timeline.SetReference(timeline.Duration * step / 29); plot.SetReference(timeline.Duration * step / 29); }
        timeline.SetReference(null); plot.SetReference(null);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        check("hover_keeps_retained_report_and_hit_indexes", timeline.ContentRenderCount == timelineRenders && plot.ContentRenderCount == curveRenders
            && marks.SequenceEqual(timeline.MarkAreas) && spans.SequenceEqual(timeline.InputSpans));
        check("reference_clear_restores_exact_report_pixels", emptyTimeline.SequenceEqual(Pixels(timeline)) && emptyPlot.SequenceEqual(Pixels(plot)));
        // Selection must retain painter order: overlapping blocks, hit/stack markers and input
        // evidence stay above/below the same decoration as in a complete report redraw.
        var selectionMatches = true; var selectionVisible = false;
        foreach (var mark in timeline.MarkAreas.Select(area => area.Mark).Distinct().ToArray())
        {
            var before = Pixels(timeline); var renders = timeline.ContentRenderCount;
            var areas = timeline.MarkAreas.ToArray(); var inputAreas = timeline.InputSpans.ToArray();
            timeline.SelectMarks([mark]);
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
            var selectedPixels = Pixels(timeline);
            check("selection_retains_report_and_hit_indexes_" + Array.IndexOf(timeline.Marks.ToArray(), mark),
                timeline.ContentRenderCount == renders && areas.SequenceEqual(timeline.MarkAreas) && inputAreas.SequenceEqual(timeline.InputSpans));
            selectionVisible |= !before.SequenceEqual(selectedPixels);
            timeline.InvalidateVisual();
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
            selectionMatches &= selectedPixels.SequenceEqual(Pixels(timeline));
        }
        check("selection_decoration_matches_complete_redraw_pixels", selectionMatches && selectionVisible);
        check("damage_hover_nearest_point_keeps_boundary_and_tie_semantics", new[] { -1d, 0, 500, 1000, 4999, 6000 }
            .All(time => plot.Nearest(time) == plot.Series.Points.MinBy(point => Math.Abs(point.TimeMs - time))));

        var series = plot.Series; var axisRenders = plot.AxisRenderCount;
        curveRenders = plot.ContentRenderCount;
        foreach (var offset in new[] { 27.25, 150.5, 0 })
        {
            plot.SetViewport(offset);
            await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        }
        check("curve_scroll_retains_data_and_drawing_moves_only_axis", ReferenceEquals(series, plot.Series)
            && plot.ContentRenderCount == curveRenders && plot.AxisRenderCount == axisRenders
            && emptyPlot.SequenceEqual(Pixels(plot)));
        plot.SetViewport(27.25);
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        var shifted = Pixels(plot);
        plot.InvalidateVisual();
        await window.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle);
        check("curve_scroll_retained_pixels_equal_complete_redraw", shifted.SequenceEqual(Pixels(plot)));
        plot.SetViewport(0);

        // A long enclosing interval must not hide short intervals or change their painter order.
        (double Start, double End)[] intervals = [(0, 1000), (800, 805), (5, 5), (12, 15), (5, 600), (900, 900)];
        TimelineIntervalIndex<(double Start, double End)> index = new(intervals, value => value); List<(double Start, double End)> found = [];
        var same = true;
        foreach (var time in new[] { -4d, 0, 5, 10, 15, 500, 802, 900, 1001 })
        { index.Query(time, time + 4, found); same &= found.SequenceEqual(intervals.Where(value => value.End >= time && value.Start <= time + 4)); }
        check("timeline_range_index_keeps_overlaps_points_and_painter_order", same);
    }
}
