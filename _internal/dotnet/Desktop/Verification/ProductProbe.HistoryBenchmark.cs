using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Threading;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Services;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    [DllImport("user32.dll")]
    private static extern uint GetGuiResources(nint process, uint flags);

    // Separate async frame keeps diagnostic locals from rooting closed windows between cycles.
    private static async Task<WeakReference> HistoryCycle(MainWindow window, string key, int expectedMarks, string expectedSummary)
    {
        await window.History.LoadAsync([key], openDetails: true);
        window.Poll();
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        var analysis = Application.Current.Windows.OfType<BattleAnalysisWindow>().Single();
        var summary = window.Summary.Snapshot ?? throw new InvalidOperationException("循环加载缺少摘要");
        var projected = PythonSortedJson.Serialize(new EvidenceObject(summary.Fields
            .Where(pair => pair.Key is "battle" or "participants" or "snapshot_quality" or "quality_summary").ToDictionary()));
        if (analysis.Timeline.Marks.Count != expectedMarks || projected != expectedSummary || analysis.Plot.Series.Metric != "rdmg")
            throw new InvalidOperationException("循环加载的报告内容变化");
        var tabs = Descendants<System.Windows.Controls.TabControl>(analysis).First();
        tabs.SelectedIndex = 1;
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        tabs.SelectedIndex = 2;
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        tabs.SelectedIndex = 0;
        analysis.SetDetails(true);
        analysis.Timeline.SelectMarks([analysis.Timeline.Marks[^1]]);
        analysis.DetailsPages.SelectedIndex = 2;
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        var reference = new WeakReference(analysis);
        analysis.Close();
        window.ReturnLive();
        return reference;
    }

    // Opt-in diagnostic: includes the controller cache, home summary and actual details window.
    // Hardware services are replaced, but indexing, analysis and MainWindow.Poll are production paths.
    internal static int RunHistoryBenchmark(string input, string output)
    {
        var config = JsonNode.Parse(File.ReadAllText(input))!;
        var root = ProductApplication.ResolveRoot();
        var temporary = Directory.CreateTempSubdirectory("endfield-main-history-benchmark-");
        var codec = new SettingsCodec(new(root));
        var settings = new SettingsStore(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")) with
        {
            CheckUpdatesOnStart = false, StartCaptureOnLaunch = false, StartInputRecordingOnLaunch = false,
            Overlays = [], ThemeMode = config["theme"]?.GetValue<string>() ?? "dark",
        }, codec, Path.Combine(temporary.FullName, "settings.json"));
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var resources = new ResourceFiles(Path.Combine(root, "_internal"));
        MainWindow window = new(settings, resources, independentFactory: (store, streams, diagnostic) =>
            new IndependentServiceController(new Recorder(), new(() => new Capture(), "missing-game.exe"), streams, store, temporary.FullName, diagnostic));
        Dictionary<string, object?> result = [];
        List<object> phases = [];
        int exit = 1;
        void Memory(string phase)
        {
            using var process = Process.GetCurrentProcess();
            phases.Add(new { phase, rss_bytes = process.WorkingSet64, private_bytes = process.PrivateMemorySize64,
                allocated_bytes = GC.GetTotalAllocatedBytes(), managed_estimate_bytes = GC.GetTotalMemory(false), handles = process.HandleCount,
                gdi = GetGuiResources(process.Handle, 0), user = GetGuiResources(process.Handle, 1),
                gc_committed_bytes = GC.GetGCMemoryInfo().TotalCommittedBytes,
                gen0 = GC.CollectionCount(0), gen1 = GC.CollectionCount(1), gen2 = GC.CollectionCount(2) });
        }
        Memory("initialized");
        window.Loaded += async (_, _) =>
        {
            try
            {
                var ready = Stopwatch.StartNew();
                while (window.History.Busy)
                {
                    if (ready.Elapsed.TotalSeconds > 30) throw new TimeoutException("历史列表准备超时");
                    await Task.Delay(20); window.Poll();
                }
                var source = config["live"]!.GetValue<string>();
                var sources = config["batch_sources"] is JsonArray batch
                    ? batch.Select(item => Path.GetFullPath(item!.GetValue<string>())).ToArray() : [Path.GetFullPath(source)];
                await window.History.ImportFilesAsync(sources); window.Poll();
                var records = sources.Select(path => window.History.Records.Single(row => row.FilePath == path)).ToArray();
                var record = records[^1];
                window.History.Select(records.Select(row => row.Key), record.Key);
                Memory("indexed");
                using var process = Process.GetCurrentProcess();
                var cpu = process.TotalProcessorTime;
                var allocated = GC.GetTotalAllocatedBytes();
                var watch = Stopwatch.StartNew();
                await window.History.LoadAsync(records.Select(row => row.Key), openDetails: config["open_details"]?.GetValue<bool>() ?? true);
                window.Poll();
                await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                result["load_and_display_ms"] = watch.Elapsed.TotalMilliseconds;
                result["load_cpu_ms"] = (process.TotalProcessorTime - cpu).TotalMilliseconds;
                result["load_allocated_bytes"] = GC.GetTotalAllocatedBytes() - allocated;
                Memory("displayed");
                var summary = window.Summary.Snapshot ?? throw new InvalidOperationException("缺少历史摘要");
                var analysis = app.Windows.OfType<BattleAnalysisWindow>().SingleOrDefault();
                result["summary_json"] = PythonSortedJson.Serialize(new EvidenceObject(summary.Fields
                    .Where(pair => pair.Key is "battle" or "participants" or "snapshot_quality" or "quality_summary").ToDictionary()));
                result["summary_has_timeline"] = summary.Get("timeline_events") is EvidenceArray;
                result["timeline_marks"] = analysis?.Timeline.Marks.Count;
                result["record_summaries"] = records.Select(row => window.History.Records.Single(item => item.Key == row.Key))
                    .Select(row => new { row.TotalDamage, row.DurationMs, row.AnalysisLoaded, row.Players }).ToArray();
                result["rdmg_default"] = analysis is null || analysis.Plot.Series.Metric == "rdmg";
                result["passed"] = window.History.DisplayedKey == record.Key && summary.Get("battle") is EvidenceObject
                    && (analysis is null || analysis.Timeline.Marks.Count > 0) && (bool)result["rdmg_default"]!;
                // Evidence export happens after all measurements. Full cache read remains an isolation boundary.
                if (config["report_output"]?.GetValue<string>() is { } reportOutput)
                    File.WriteAllText(reportOutput, PythonSortedJson.Serialize(window.History.ReadSnapshot()!));
                var cycles = config["report_cycles"]?.GetValue<int>() ?? 0;
                if (cycles > 0)
                {
                    if (analysis is null || cycles > 100) throw new ArgumentException("循环检查需要打开详情，次数为 1–100");
                    var marks = analysis.Timeline.Marks.Count;
                    List<WeakReference> closedWindows = [new(analysis)];
                    analysis.Close(); analysis = null;
                    window.ReturnLive();
                    await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
                    Memory("cycles_start");
                    List<object> samples = [];
                    for (var cycle = 0; cycle < cycles; cycle++)
                    {
                        var cycleClock = Stopwatch.StartNew();
                        closedWindows.Add(await HistoryCycle(window, record.Key, marks, (string)result["summary_json"]!));
                        await Task.Delay(500);
                        await Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
                        var open = app.Windows.OfType<BattleAnalysisWindow>().Count();
                        if (open != 0 || window.History.Busy || window.History.DisplayedKey is not null)
                            throw new InvalidOperationException("关闭报告后状态未清理");
                        samples.Add(new { cycle = cycle + 1, milliseconds = cycleClock.Elapsed.TotalMilliseconds,
                            closed_windows_alive = closedWindows.Count(reference => reference.IsAlive), open_analysis_windows = open });
                        Memory("cycle_" + (cycle + 1));
                    }
                    result["report_cycles"] = samples;
                    result["history_cache_retained"] = true;
                    // Idle CPU is measured after all report work has settled, without forcing collection.
                    var idleCpu = process.TotalProcessorTime; var idleClock = Stopwatch.StartNew();
                    await Task.Delay(5000);
                    result["idle_cpu_ms"] = (process.TotalProcessorTime - idleCpu).TotalMilliseconds;
                    result["idle_elapsed_ms"] = idleClock.Elapsed.TotalMilliseconds;
                    result["closed_windows_alive_after_idle"] = closedWindows.Count(reference => reference.IsAlive);
                    Memory("cycles_idle");
                }
                result["boundary"] = "Actual MainWindow/HistoryController/home summary/details. Dispatcher ContextIdle, not physical presentation. Synthetic input; capture/input/vision disabled. No forced GC.";
                exit = (bool)result["passed"]! ? 0 : 1;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally
            {
                foreach (var analysis in app.Windows.OfType<BattleAnalysisWindow>().ToArray()) analysis.Close();
                window.Close();
                var closing = Stopwatch.StartNew();
                while (!window.ServicesDisposed && closing.Elapsed.TotalSeconds < 15) await Task.Delay(20);
                result["services_disposed"] = window.ServicesDisposed;
                result["memory_phases"] = phases;
                InterfaceBenchmark.AddAssemblyIdentity(result);
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
