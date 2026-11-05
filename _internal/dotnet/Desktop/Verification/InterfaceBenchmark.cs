using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Visible production controls using public synthetic long-session/history fixtures.</summary>
internal static partial class InterfaceBenchmark
{
    // Report loaded modules after timed work; the external harness checks their
    // locations against the requested executable before accepting any result.
    internal static void AddAssemblyIdentity(IDictionary<string, object?> result)
    {
        result["process_path"] = Environment.ProcessPath;
        foreach (var (name, assembly) in new[]
        {
            ("core", typeof(ResourceFiles).Assembly),
            ("runtime", typeof(HistoryController).Assembly),
            ("desktop", typeof(InterfaceBenchmark).Assembly),
        })
        {
            result[name + "_assembly_path"] = assembly.Location;
            result[name + "_module_id"] = assembly.ManifestModule.ModuleVersionId;
        }
    }

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        if (root is T found) yield return found;
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
            foreach (var child in Descendants<T>(VisualTreeHelper.GetChild(root, index))) yield return child;
    }
    internal static int Run(string input, string output)
    {
        var config = JsonNode.Parse(File.ReadAllText(input))!;
        if (config["live_window_path"]?.GetValue<bool>() == true) return ProductProbe.RunLiveBenchmark(input, output);
        if (config["main_window_path"]?.GetValue<bool>() == true) return ProductProbe.RunHistoryBenchmark(input, output);
        var root = ProductApplication.ResolveRoot();
        var temporary = Directory.CreateTempSubdirectory("endfield-interface-benchmark-");
        var codec = new SettingsCodec(new(root));
        var settings = new SettingsStore(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")) with { CheckUpdatesOnStart = false, FontPercent = config["font_percent"]?.GetValue<int>() ?? 100 }, codec,
            Path.Combine(temporary.FullName, "settings.json"));
        var resources = new ResourceFiles(Path.Combine(root, "_internal"));
        var index = new HistoryIndex(Path.Combine(temporary.FullName, "cache"));
        var analyzer = new HistoryAnalyzer(resources);
        using var history = new HistoryController(settings, index, analyzer.AnalyzeAsync);
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        List<string> diagnostics = [];
        var page = new HistoryPage(history, _ => throw new InvalidOperationException("Unexpected manual background task"), diagnostics.Add, history.ReturnLive);
        Window window = new() { Title = "Endfield Logs · 界面性能验证", Width = 1200, Height = 800, Content = page };
        BenchmarkWindow.Prepare(window);
        Ui.ApplyAppearance(window, config["theme"]?.GetValue<string>() ?? "light", config["font_percent"]?.GetValue<int>() ?? 100);
        Dictionary<string, object?> result = new() { ["no_input_window"] = true, ["window_protocol"] = BenchmarkWindow.Protocol };
        result["history_display"] = config["history_display"]?.DeepClone();
        List<object>? memoryPhases = config["memory_phases"]?.GetValue<bool>() == true ? [] : null;
        void Memory(string phase)
        {
            if (memoryPhases is null) return;
            using var process = Process.GetCurrentProcess();
            var gc = GC.GetGCMemoryInfo();
            memoryPhases.Add(new
            {
                phase, rss_bytes = process.WorkingSet64, private_bytes = process.PrivateMemorySize64,
                peak_rss_bytes = process.PeakWorkingSet64, managed_estimate_bytes = GC.GetTotalMemory(false),
                allocated_bytes = GC.GetTotalAllocatedBytes(), heap_bytes = gc.HeapSizeBytes,
                committed_bytes = gc.TotalCommittedBytes, fragmented_bytes = gc.FragmentedBytes,
                gen0 = GC.CollectionCount(0), gen1 = GC.CollectionCount(1), gen2 = GC.CollectionCount(2),
                handles = process.HandleCount,
            });
        }
        Memory("initialized");
        var exit = 1;
        BattleAnalysisWindow? analysis = null;
        async Task<double> Measure(Action action)
        {
            var timer = Stopwatch.StartNew(); action();
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            var elapsed = timer.Elapsed.TotalMilliseconds;
            BenchmarkWindow.Check();
            return elapsed;
        }
        window.Loaded += async (_, _) =>
        {
            try
            {
                var watch = Stopwatch.StartNew();
                await history.ImportFilesAsync([config["history"]!.GetValue<string>()]);
                diagnostics.AddRange(history.Drain().SelectMany(row => row.Errors));
                result["history_index_ms"] = watch.Elapsed.TotalMilliseconds;
                result["history_bind_ms"] = await Measure(page.RefreshRows);
                var table = Descendants<HistoryList>(page).Single();
                if (config["history_cell_probe"]?.GetValue<bool>() == true || config["history_layout_probe"]?.GetValue<bool>() == true) table.SetRecordLayout(false);
                if (config["history_display"] is { } display) await ConfigureHistoryDisplay(window, page, table, display);
                result["history_records"] = table.Items.Count;
                List<double> scrolls = []; List<long> historyScrollAllocations = [];
                var scrollSteps = config["history_scroll_steps"]?.GetValue<int>() ?? 20;
                if (scrollSteps is < 20 or > 2000) throw new ArgumentException("历史滚动次数应在 20–2000 之间");
                for (var step = 0; step < scrollSteps; step++)
                {
                    var row = table.Items[(int)((table.Items.Count - 1) * (step % 20) / 19d)];
                    var bytes = GC.GetAllocatedBytesForCurrentThread();
                    scrolls.Add(await Measure(() => table.ScrollIntoView(row)));
                    historyScrollAllocations.Add(GC.GetAllocatedBytesForCurrentThread() - bytes);
                }
                result["history_scroll_ms"] = scrolls;
                result["history_text_cache"] = new { table.TextCache.Count, table.TextCache.Hits, table.TextCache.Creations };
                result["history_scroll_allocated_bytes"] = historyScrollAllocations;
                result["history_realized_rows"] = Descendants<ListViewItem>(table).Count();
                // A separate validation pass cannot change the timed scroll samples.
                if (config["history_cell_probe"]?.GetValue<bool>() != true && config["history_layout_probe"]?.GetValue<bool>() != true)
                {
                    List<object> geometry = [];
                    for (var step = 0; step < 20; step++)
                    {
                        var target = (int)((table.Items.Count - 1) * step / 19d);
                        table.ScrollIntoView(table.Items[target]);
                        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                        BenchmarkWindow.Check();
                        geometry.Add(HistoryGeometry(table, target, page));
                    }
                    result["history_geometry_samples"] = geometry;
                }
                result["history_sort_ms"] = await Measure(() => CollectionViewSource.GetDefaultView(table.ItemsSource).SortDescriptions.Add(new(nameof(HistoryRow.Started), ListSortDirection.Ascending)));
                Memory("history_visible");
                if (config["history_only"]?.GetValue<bool>() == true)
                {
                    result["history_keyboard_focus_tested"] = false;
                    if (config["history_cell_probe"]?.GetValue<bool>() == true)
                    {
                        result["history_cell_checks"] = await VerifyHistoryCells(table, history);
                        var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
                        image.Render(window);
                        PngBitmapEncoder historyEncoder = new(); historyEncoder.Frames.Add(BitmapFrame.Create(image));
                        using var file = File.Create(Path.ChangeExtension(output, ".cells.png")); historyEncoder.Save(file);
                    }
                    result["history_row_heights"] = Descendants<ListViewItem>(table).Select(row => row.ActualHeight).Distinct().ToArray();
                    result["font_size"] = table.FontSize;
                    if (config["history_layout_probe"]?.GetValue<bool>() == true)
                    {
                        var row = Descendants<ListViewItem>(table).First();
                        var cell = Descendants<HistoryCell>(row).First();
                        result["history_row_layout"] = new
                        {
                            row.MinHeight, row.ActualHeight, row.FontSize, font_family = row.FontFamily.Source,
                            line_spacing = row.FontFamily.LineSpacing,
                            cell_height = cell.ActualHeight, cell_border = row.BorderThickness.ToString(),
                            text_height = cell.ActualHeight,
                            visual_nodes = Descendants<DependencyObject>(row).Count(),
                        };
                        result["history_row_template"] = System.Windows.Markup.XamlWriter.Save(row.Template);
                        result["history_cell_template"] = cell.GetType().FullName;
                    }
                    result["diagnostics"] = diagnostics;
                    result["passed"] = diagnostics.Count == 0 && history.Records.All(row => !row.AnalysisLoaded)
                        && (int)result["history_realized_rows"]! < Math.Min(100, table.Items.Count);
                    result["boundary"] = "Actual indexed history ListView, repeated ScrollIntoView to ContextIdle; no report analysis, profiler or forced GC in timing runs.";
                    exit = (bool)result["passed"]! ? 0 : 1;
                    return;
                }
                var source = config["live"]!.GetValue<string>();
                var longRecord = (await Task.Run(() => index.Records(source, trace: true))).Single();
                watch.Restart(); var report = await analyzer.AnalyzeAsync(longRecord);
                result["long_report_analysis_ms"] = watch.Elapsed.TotalMilliseconds;
                Memory("report_ready");
                watch.Restart(); analysis = new(report, settings, resources: resources);
                BenchmarkWindow.Prepare(analysis);
                result["analysis_construct_ms"] = watch.Elapsed.TotalMilliseconds;
                Memory("analysis_constructed");
                result["analysis_first_display_ms"] = await Measure(analysis.Show);
                Memory("analysis_visible");
                var timeline = analysis.Timeline;
                result["default_fits_viewport"] = timeline.ActualWidth <= analysis.DiagramScroll.ViewportWidth + 1;
                var zoom = Descendants<Slider>(analysis).Single(item => item.Maximum == 10);
                await Measure(() => zoom.Value = config["zoom"]?.GetValue<double>() ?? 8);
                if (config["label_width"] is { } labelWidth) await Measure(() => timeline.ResizeLabels(labelWidth.GetValue<double>()));
                if (config["plot_width"] is { } plotWidth) await Measure(() => zoom.Value = plotWidth.GetValue<double>() / Math.Max(120, analysis.DiagramScroll.ViewportWidth - timeline.LabelWidth - 10));
                var coordinates = timeline.Marks.Select(mark => (mark.Start, mark.End)).ToArray();
                result["timeline_total_marks"] = timeline.Marks.Count;
                result["timeline_extent"] = timeline.ActualWidth;
                result["timeline_label_width"] = timeline.LabelWidth;
                result["timeline_plot_width"] = timeline.ActualWidth - timeline.LabelWidth - 10;
                if (config["input_samples"] is { } inputSamples)
                {
                    var count = inputSamples.GetValue<int>();
                    var role = timeline.Marks.First().Owner;
                    var raw = Enumerable.Range(0, count).Select(index => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
                    {
                        ["time_ms"] = new EvidenceReal(timeline.Duration * index / count),
                        ["device"] = new EvidenceText("mouse"), ["code"] = new EvidenceText("X"), ["value"] = new EvidenceInteger(index % 2000 - 1000)
                    })).ToArray();
                    var actions = Enumerable.Range(0, count / 10).Select(index => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
                    {
                        ["start_ms"] = new EvidenceReal(timeline.Duration * index * 10 / count),
                        ["end_ms"] = new EvidenceReal(timeline.Duration * (index * 10 + 2) / count),
                        ["action"] = new EvidenceText(index % 3 == 0 ? "combo" : "skill"), ["character_key"] = new EvidenceText(role),
                        ["tooltip"] = new EvidenceText("合成输入意图 " + index)
                    })).ToArray();
                    result["input_bind_ms"] = await Measure(() => timeline.SetInputEvidence(new(new Dictionary<string, EvidenceValue>
                        { ["raw"] = new EvidenceArray(raw), ["actions"] = new EvidenceArray(actions) })));
                    result["input_raw_count"] = timeline.InputLayout.Raw.Count;
                    result["input_span_count"] = timeline.InputLayout.Spans.Count;
                }
                result["timeline_paint_ms"] = await Measure(timeline.InvalidateVisual);
                List<double> moves = []; List<long> scrollAllocations = []; var scroll = analysis.DiagramScroll;
                List<object> contentRenders = [];
                timeline.RenderMeasured = (ms, bytes) => contentRenders.Add(new { step = moves.Count, milliseconds = ms, allocated_bytes = bytes });
                var curveRenders = analysis.Plot.ContentRenderCount;
                for (var step = 0; step < 20; step++)
                {
                    var position = scroll.ScrollableWidth * step / 19;
                    var allocated = GC.GetAllocatedBytesForCurrentThread();
                    moves.Add(await Measure(() => { scroll.ScrollToHorizontalOffset(position); timeline.SetReference(timeline.Duration * step / 19); }));
                    scrollAllocations.Add(GC.GetAllocatedBytesForCurrentThread() - allocated);
                }
                result["timeline_scroll_ms"] = moves;
                result["timeline_scroll_allocated_bytes"] = scrollAllocations;
                timeline.RenderMeasured = null;
                result["timeline_scroll_content_renders"] = contentRenders;
                Memory("timeline_scrolled");
                if (config["input_samples"] is not null)
                {
                    await Measure(scroll.ScrollToBottom);
                    List<double> inputScrolls = []; List<object> inputRenders = [];
                    timeline.RenderMeasured = (ms, bytes) => inputRenders.Add(new { milliseconds = ms, allocated_bytes = bytes });
                    for (var step = 0; step < 20; step++)
                    {
                        var position = scroll.ScrollableWidth * step / 19;
                        inputScrolls.Add(await Measure(() => scroll.ScrollToHorizontalOffset(position)));
                    }
                    timeline.RenderMeasured = null;
                    result["input_track_scroll_ms"] = inputScrolls;
                    result["input_track_content_renders"] = inputRenders;
                    result["input_track_viewport_top"] = scroll.VerticalOffset;
                    result["input_track_visible"] = scroll.VerticalOffset + scroll.ViewportHeight >= timeline.ActualHeight - 1;
                    await Measure(scroll.ScrollToTop);
                }
                result["curve_content_renders_during_scroll"] = analysis.Plot.ContentRenderCount - curveRenders;
                result["timeline_final_painted_marks"] = timeline.MarkAreas.Select(item => item.Mark).Distinct().Count();
                result["timeline_viewport_width"] = scroll.ViewportWidth;
                // No scrolling or data changes: isolate the synchronized reference line path.
                List<double> hover = []; var hoverAllocated = GC.GetAllocatedBytesForCurrentThread();
                for (var step = 0; step < 100; step++)
                {
                    var stamp = timeline.Duration * (step % 20) / 19;
                    hover.Add(await Measure(() => { timeline.SetReference(stamp); analysis.Plot.SetReference(stamp); }));
                }
                result["timeline_reference_ms"] = hover;
                result["timeline_reference_allocated_bytes"] = GC.GetAllocatedBytesForCurrentThread() - hoverAllocated;
                var selectable = timeline.MarkAreas.Select(area => area.Mark).Distinct().ToArray();
                List<double> selections = []; var selectionRenders = timeline.ContentRenderCount;
                var selectionAllocated = GC.GetAllocatedBytesForCurrentThread();
                for (var step = 0; step < 60 && selectable.Length > 0; step++)
                    selections.Add(await Measure(() => timeline.SelectMarks([selectable[step % selectable.Length]])));
                result["timeline_selection_ms"] = selections;
                result["timeline_selection_allocated_bytes"] = GC.GetAllocatedBytesForCurrentThread() - selectionAllocated;
                result["timeline_selection_content_renders"] = timeline.ContentRenderCount - selectionRenders;
                result["timeline_zoom_ms"] = await Measure(() => zoom.Value = 2);
                result["timeline_zoom_restore_ms"] = await Measure(() => zoom.Value = 1);
                result["coordinates_preserved"] = coordinates.SequenceEqual(timeline.Marks.Select(mark => (mark.Start, mark.End)));
                var tabs = Descendants<TabControl>(analysis).First();
                result["skills_page_ms"] = await Measure(() => tabs.SelectedIndex = 1);
                result["enemy_page_ms"] = await Measure(() => tabs.SelectedIndex = 2);
                await Measure(() => tabs.SelectedIndex = 0);
                result["details_ms"] = await Measure(() => { analysis.SetDetails(true); timeline.SelectMarks([timeline.Marks[^1]]); analysis.DetailsPages.SelectedIndex = 2; });
                Memory("details_visible");
                result["rdmg_default"] = analysis.Plot.Series.Metric == "rdmg";
                result["diagnostics"] = diagnostics;
                result["boundary"] = "actual WPF windows/Dispatcher; index-only 400 battle list and 7200-hit report; UI completion through ContextIdle, excludes physical scanout";
                result["passed"] = diagnostics.Count == 0 && history.Records.All(row => !row.AnalysisLoaded)
                    && (bool)result["coordinates_preserved"]! && (bool)result["rdmg_default"]!
                    && (bool)result["default_fits_viewport"]!
                    && (int)result["history_realized_rows"]! < Math.Min(100, table.Items.Count);
                RenderTargetBitmap bitmap = new((int)analysis.ActualWidth, (int)analysis.ActualHeight, 96, 96, PixelFormats.Pbgra32);
                bitmap.Render(analysis); PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
                using (var image = File.Create(Path.ChangeExtension(output, ".png"))) encoder.Save(image);
                Memory("screenshot_saved");
                exit = (bool)result["passed"]! ? 0 : 1;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally
            {
                analysis?.Close(); window.Close();
                Memory("windows_closed");
                if (memoryPhases is not null) result["memory_phases"] = memoryPhases;
                AddAssemblyIdentity(result);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
                File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
                app.Shutdown(exit);
            }
        };
        app.Run(window);
        try { temporary.Delete(true); } catch (IOException) { }
        return exit;
    }
}
