using System.Collections.Concurrent;
using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class MainWindow : Window
{
    private readonly SettingsStore settings;
    private readonly ResourceFiles resources;
    private readonly CaptureController capture;
    private readonly IndependentServiceController independent;
    private readonly OverlayManager overlays;
    private readonly HistoryController history;
    private readonly HistoryPage historyPage;
    private readonly BattleSummaryView summary = new();
    private readonly TextBlock notice = Ui.Text("");
    internal HomePage Home { get; }
    private readonly TextBox diagnostic = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    private readonly Button captureButton, inputButton, newRecordingButton;
    internal MainNavigation Navigation { get; } = new();
    private readonly ConcurrentQueue<string> messages = new();
    private readonly DispatcherTimer timer;
    private EvidenceObject? liveSnapshot;
    private string? lastError;
    private bool wasRunning, closing, cleaned, remoteCombo, rotatingRecording;
    private readonly List<BattleAnalysisWindow> analysisWindows = [];
    internal HistoryController History => history;
    internal BattleSummaryView Summary => summary;
    internal bool ServicesDisposed => cleaned;
    internal OverlayManager Overlays => overlays;
    internal MainWindow(SettingsStore settings, ResourceFiles resources, Func<SettingsStore, CaptureController>? captureFactory = null,
        Func<SettingsStore, Action<IReadOnlySet<string>>, Action<string>, IndependentServiceController>? independentFactory = null)
    {
        this.settings = settings; this.resources = resources;
        updates = new(settings, Notify);
        Title = "Endfield Logs - Enhanced"; Width = 1200; Height = 800; MinWidth = 780; MinHeight = 500; WindowStartupLocation = WindowStartupLocation.CenterScreen;
        capture = captureFactory?.Invoke(settings) ?? new(resources, settings);
        independent = independentFactory?.Invoke(settings, capture.SetStreams, QueueNotice) ?? ServiceComposition.Independent(settings, capture.SetStreams, QueueNotice);
        overlays = new(settings, QueueNotice);
        overlays.RequirementsChanged += _ => UpdateRequirements();
        var analyzer = new HistoryAnalyzer(resources);
        history = new(settings, new(Path.Combine(settings.Context.ApplicationRoot, ".dev-gui", "history-index")), analyzer, capture.IsWriting);
        historyPage = new(history, Track, Notify, ReturnLive, summary, () => settings.Current.Service.LogDirectory);
        historyPage.SourceRenamed += (oldPath, newPath) =>
        {
            foreach (var window in analysisWindows.ToArray()) Track(window.RelocateInputAsync(oldPath, newPath));
            if (history.ReadSummarySnapshot() is { } report) { summary.SetSnapshot(report, historical: true); overlays.ShowHistory(report, history.Record?.Label ?? "已加载"); }
        };
        DockPanel root = new(); Content = root;
        notice.Padding = new(6); DockPanel.SetDock(notice, Dock.Bottom); root.Children.Add(notice);
        root.Children.Add(Navigation);
        Home = new(settings.Context.ApplicationRoot, () => Guard(ToggleCapture), () => Guard(independent.ToggleInput),
            () => Track(NewRecordingAsync()), HideGui, ShowInputSettings, () => Navigation.Select(MainPage.Overlays));
        captureButton = Home.CaptureButton; inputButton = Home.InputButton; newRecordingButton = Home.NewRecordingButton;
        Navigation.AddPage(MainPage.Home, "首页", "\uE80F", Home);
        Navigation.AddPage(MainPage.Overlays, "悬浮窗", "\uE737", new OverlaysPage(settings, overlays, Notify, ShowVisionSettings), newGroup: true);
        Navigation.AddPage(MainPage.History, "战斗日志", "\uE81C", historyPage);
        Navigation.AddPage(MainPage.Logs, "运行日志", "\uE8A5", diagnostic, newGroup: true);
        Navigation.AddPage(MainPage.Settings, "设置", "\uE713", new SettingsPage(settings, ApplySettings, Notify, updates, active =>
        { shell?.SuspendHotkeys(active); if (!active) ApplySettings(); }));
        Navigation.PageChanged += key => { if (key == MainPage.History) Track(history.RefreshAsync()); };
        ApplySettings();
        InitializeShell();
        independent.SetRequirements(["analysis_summary"]);
        timer = new DispatcherTimer(TimeSpan.FromMilliseconds(100), DispatcherPriority.Background, (_, _) => Poll(), Dispatcher);
        Loaded += (_, _) =>
        {
            Track(history.RefreshAsync());
            overlays.Sync();
            if (settings.Current.OverlayMigrationCount > 0) Notify($"已迁移悬浮窗配置，移除 {settings.Current.OverlayMigrationCount} 个旧格式条目，可按需导入原生皮肤。");
            if (settings.Current.StartCaptureOnLaunch) Guard(capture.Start);
            if (settings.Current.CheckUpdatesOnStart) Track(updates.ScheduleAsync());
        };
        Closing += OnClosing;
    }
    internal void Notify(string text)
    { notice.Text = text; diagnostic.AppendText($"[{DateTime.Now:HH:mm:ss}] {text}\n"); if (diagnostic.Text.Length > 64 * 1024) diagnostic.Text = diagnostic.Text[^48_000..]; diagnostic.ScrollToEnd(); }
    private void QueueNotice(string text) => messages.Enqueue(text);
    private void Guard(Action action) { try { action(); } catch (Exception error) { Notify(error.Message); } }
    internal void Track(Task task) => _ = ObserveAsync(task);
    private async Task ObserveAsync(Task task)
    { try { await task; } catch (OperationCanceledException) when (closing) { } catch (Exception error) { if (!closing) QueueNotice(error.Message); } }
    private void ToggleCapture()
    { if (capture.Running) Track(capture.StopAsync()); else { liveSnapshot = null; overlays.ClearLive(); if (history.DisplayedKey is null) summary.SetSnapshot(null); capture.Start(); } }
    private async Task NewRecordingAsync()
    {
        if (rotatingRecording || closing || !capture.Running || capture.Poll().Status?.Running != true) return;
        rotatingRecording = true; newRecordingButton.IsEnabled = false;
        try
        {
            var active = !capture.Poll().Recording;
            var paths = await capture.SetRecordingAsync(active);
            if (closing) return;
            await independent.SetRecording(active, paths?.TracePath);
            overlays.SetRecording(active);
            Notify(active ? "已开始记录：" + Path.GetFileName(paths!.TracePath) : "已停止记录，抓包与实时分析继续运行。");
            Track(history.RefreshAsync());
        }
        finally { rotatingRecording = false; }
    }
    private void UpdateRequirements() => independent.SetRequirements(overlays.Requirements.Concat(["analysis_summary"]).Concat(remoteCombo ? ["combo_snapshot"] : Array.Empty<string>()));
    internal void ReturnLive()
    { history.ReturnLive(); summary.SetSnapshot(liveSnapshot); overlays.ReturnLive(); historyPage.UpdateState(); }
    internal void ApplySettings()
    {
        Ui.ApplyAppearance(this, settings.Current.ThemeMode, settings.Current.FontPercent);
        foreach (var window in analysisWindows) window.ApplyAppearance();
        shell?.Configure(settings.Current.ToggleGuiHotkey, settings.Current.ToggleOverlaysHotkey, settings.Current.ToggleRecordingHotkey);
        independent.RefreshGameExecutable();
        independent.ApplyInputPreference();
    }
    internal void Poll()
    {
        if (closing) return;
        try
        {
            while (messages.TryDequeue(out var message)) Notify(message);
            var state = capture.Poll();
            if (remoteCombo != state.ComboRequested) { remoteCombo = state.ComboRequested; UpdateRequirements(); }
            foreach (var line in state.Diagnostics) Notify(line);
            if (state.Error is { Length: > 0 } error && error != lastError) Notify("抓包故障：" + error);
            lastError = state.Error;
            captureButton.Content = state.Stopping ? "正在停止…" : state.Running ? "停止抓包" : "启动抓包"; captureButton.IsEnabled = !state.Stopping;
            newRecordingButton.Content = state.Recording ? "停止记录" : "开始记录";
            newRecordingButton.IsEnabled = !rotatingRecording && state.Running && !state.Stopping && state.Status?.Running == true;
            Home.RecordingStatus.Text = state.Recording ? "记录中" : "未记录";
            overlays.SetRecording(state.Recording);
            Home.CaptureHint.Text = !state.Running ? state.Error is null ? "已停止" : "已停止：" + state.Error
                : state.Status is { } status ? $"抓包：{status.Flow.State}  ·  已收 {status.PacketsSeen:N0} 包  ·  丢弃 {status.QueueDrops:N0}" : "正在启动抓包…";
            Home.UpdateCapture(state);
            if (state.Running)
            { independent.SetSession(state.Status?.Flow.SessionId); independent.SetMembers(state.Members); _ = independent.SetRecording(state.Recording, state.TracePath); }
            else if (wasRunning)
            {
                independent.CaptureStopped(); Track(history.RefreshAsync());
                liveSnapshot = null; overlays.ClearLive(); if (history.DisplayedKey is null) summary.SetSnapshot(null);
            }
            wasRunning = state.Running;
            foreach (var frame in state.Frames.Where(frame => frame.Type == "analysis_summary"))
            { liveSnapshot = frame.Snapshot; overlays.Receive(frame.ToEvidence()); if (history.DisplayedKey is null) summary.SetSnapshot(liveSnapshot); }
            var services = independent.Poll();
            visionSettings?.Refresh();
            if (services.ComboSnapshot is { } combo) { overlays.Receive(combo); capture.PublishCombo(combo); }
            inputButton.Content = independent.InputEnabled ? "禁用输入记录" : "启用输入记录";
            Home.UpdateInput(services.InputStatus);
            if (independent.InputEnabled && !services.InputRunning && services.InputStatus.Get("status") is not EvidenceText { Value: "error" }) Home.InputStatus.Text = "已启用 · 等待开始记录伤害日志";
            Home.VisionStatus.Text = services.VisualStatus;
            foreach (var update in history.Drain())
            {
                historyPage.RefreshRows(); foreach (var errorText in update.Errors) Notify(errorText);
                if (update.Kind == "analysis" && history.ReadSummarySnapshot() is { } snapshot)
                { summary.SetSnapshot(snapshot, historical: true); overlays.ShowHistory(snapshot, history.Record?.Label ?? "已加载"); }
                if (update.OpenDetails && history.ReadOnlySnapshot() is { } report)
                {
                    BattleAnalysisWindow window = new(report, settings, history.Record, Notify, resources) { Owner = this }; analysisWindows.Add(window);
                    window.Closed += (_, _) => analysisWindows.Remove(window); window.Show();
                }
            }
            historyPage.UpdateState();
        }
        catch (Exception error) { if (error.Message != lastError) Notify(error.Message); lastError = error.Message; }
    }
    private async void OnClosing(object? sender, CancelEventArgs args)
    {
        if (cleaned) return;
        args.Cancel = true; if (closing) return; closing = true; timer.Stop(); IsEnabled = false;
        shell?.Dispose(); updates.Dispose();
        visionSettings?.Close();
        foreach (var window in analysisWindows.ToArray()) window.Close();
        try
        {
            history.Dispose();
            overlays.Dispose();
            await Task.WhenAll(independent.DisposeAsync().AsTask(), capture.DisposeAsync().AsTask());
        }
        catch (Exception error) { Notify("退出清理：" + error.Message); }
        // Cleanup may complete synchronously. Defer the second close until WPF leaves the first Closing event.
        finally { cleaned = true; _ = Dispatcher.BeginInvoke(new Action(Close)); }
    }
}
