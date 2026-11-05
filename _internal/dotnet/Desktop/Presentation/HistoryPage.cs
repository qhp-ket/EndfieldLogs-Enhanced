using System.IO;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Runtime.History;
using Microsoft.Win32;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed record HistoryRow(HistoryRecord Record)
{
    public string Name => Record.Label;
    public string Started => DateTimeOffset.FromUnixTimeMilliseconds(Record.StartedAtMs).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss");
    public string Players => string.Join("、", Record.Players.Select(player => player.DisplayName));
    public double? Damage => Record.AnalysisLoaded || !Record.IsTrace ? Record.TotalDamage : null;
    public double? Dps => Record.AnalysisLoaded || !Record.IsTrace ? Record.Dps : null;
    public double? Duration => Record.DurationMs > 0 ? Record.DurationMs / 1000d : null;
    public string Description => Record.AnalysisLoaded || !Record.IsTrace ? $"伤害 {Record.TotalDamage:N2}   DPS {Record.Dps:N2}   时长 {Record.DurationMs / 1000d:N2} 秒" : "待加载 · 点击加载后分析所选战斗";
    public string Full => $"{Record.Label}\n{Record.FilePath}\n{Description}";
}

/// <summary>Index rows stay lightweight; only explicit loading asks Runtime for a complete report.</summary>
internal sealed class HistoryPage : DockPanel
{
    private readonly HistoryController history;
    private readonly Action<Task> track;
    private readonly Action<string> notify;
    private readonly Action returnLive;
    private readonly HistoryList table = new();
    private readonly TextBlock state = Ui.Text("");
    private readonly TextBlock sourceState = Ui.Text("悬浮窗：实时日志");
    private readonly BattleSummaryView summary;
    private readonly Button loadButton, analysisButton, renameButton, importButton, removeButton, exportButton;
    private readonly Func<string>? logDirectory;
    private HistoryRecord? selectedRecord;
    internal HistoryList RecordsTable => table;
    private bool refreshing;
    internal event Action<string, string>? SourceRenamed;
    public HistoryPage(HistoryController history, Action<Task> track, Action<string> notify, Action returnLive, BattleSummaryView? summary = null, Func<string>? logDirectory = null)
    {
        this.history = history; this.track = track; this.notify = notify; this.returnLive = returnLive;
        this.summary = summary ?? new(); this.logDirectory = logDirectory;
        StackPanel body = new() { Margin = new(0, 14, 8, 20) }; body.Children.Add(this.summary);
        Grid split = new() { Margin = new(0, 20, 0, 0) };
        split.ColumnDefinitions.Add(new() { Width = new(260), MinWidth = 210 }); split.ColumnDefinitions.Add(new() { Width = new(12) }); split.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        split.RowDefinitions.Add(new() { Height = GridLength.Auto }); split.RowDefinitions.Add(new() { Height = GridLength.Auto });
        StackPanel actions = new();
        Button Command(string text, Action action, bool primary = false)
        {
            var button = Ui.Button(text, () => { try { action(); } catch (Exception error) { notify(error.Message); } }, primary);
            button.HorizontalAlignment = HorizontalAlignment.Stretch; button.Margin = new(0, 0, 0, 10); actions.Children.Add(button); return button;
        }
        loadButton = Command("加载选中记录", () => track(history.LoadAsync(history.SelectedRecords.Select(row => row.Key))), true);
        analysisButton = Command("战斗时间轴 / 技能构成…", () => track(history.LoadAsync(history.SelectedRecords.Select(row => row.Key), openDetails: true)));
        analysisButton.ToolTip = "按需分析最后选中的一场记录；保留多选和当前记录状态。";
        renameButton = Command("重命名文件…", Rename); Command("打开所在文件夹", OpenFolder);
        importButton = Command("导入 trace 日志…", Import);
        var importHint = Ui.Text("引用原文件，不复制；完整统计在点击加载后计算"); importHint.Margin = new(0, 0, 0, 12); actions.Children.Add(importHint);
        exportButton = Command("导出官网兼容日志…", Export);
        exportButton.ToolTip = "仅导出当前选中的一场战斗及其完整证据；多选时使用最后选中项。另存为官网上传器可读取的 .log。";
        removeButton = Command("从列表移除选中记录", () => { history.Remove(history.SelectedRecords.Select(row => row.Key)); RefreshRows(); if (history.DisplayedKey is null) returnLive(); });
        var removeHint = Ui.Text("Ctrl / Shift 多选；加载后仅展示最后选中项。移除不会删除原始日志文件，重新导入 trace 可恢复。"); removeHint.Margin = new(0, 0, 0, 12); actions.Children.Add(removeHint);
        Command("返回实时日志", returnLive); actions.Children.Add(sourceState);
        PageCard operations = new("记录操作", actions); split.Children.Add(operations);
        GridSplitter divider = new() { Width = 6, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Stretch, Background = System.Windows.Media.Brushes.Transparent, ResizeBehavior = GridResizeBehavior.PreviousAndNext };
        Grid.SetColumn(divider, 1); split.Children.Add(divider);
        DockPanel listing = new(); DockPanel toolbar = new() { Margin = new(0, 0, 0, 14) };
        state.HorizontalAlignment = HorizontalAlignment.Right; state.VerticalAlignment = VerticalAlignment.Center; SetDock(state, Dock.Right); toolbar.Children.Add(state);
        WrapPanel listActions = new(); listActions.Children.Add(Ui.Button("刷新记录", () => track(history.RefreshAsync()), true));
        listActions.Children.Add(Ui.Button("全选", table.SelectAll));
        ComboBox display = new() { ItemsSource = new[] { "记录列表", "详细表格" }, SelectedIndex = 0, MinWidth = 106, MinHeight = 32, Margin = new(0, 0, 8, 6), VerticalAlignment = VerticalAlignment.Center, ToolTip = "详细表格保留列宽调整、数值排序和列选择复制" };
        display.SelectionChanged += (_, _) => table.SetRecordLayout(display.SelectedIndex == 0); listActions.Children.Add(display);
        toolbar.Children.Add(listActions); SetDock(toolbar, Dock.Top); listing.Children.Add(toolbar);
        HistoryColumn.Add(table, "时间", nameof(HistoryRow.Started), row => row.Started, width: 165);
        HistoryColumn.Add(table, "战斗", nameof(HistoryRow.Name), row => row.Name, width: 260);
        HistoryColumn.Add(table, "角色", nameof(HistoryRow.Players), row => row.Players, width: 240);
        HistoryColumn.Add(table, "DMG", nameof(HistoryRow.Damage), row => row.Damage, true, "N0");
        HistoryColumn.Add(table, "DPS", nameof(HistoryRow.Dps), row => row.Dps, true, "N1");
        HistoryColumn.Add(table, "秒", nameof(HistoryRow.Duration), row => row.Duration, true, "N1", 70);
        table.SetRecordLayout(true);
        table.SelectionMode = SelectionMode.Extended;
        table.SelectionChanged += (_, args) =>
        {
            if (refreshing) return;
            history.Select(table.SelectedItems.OfType<HistoryRow>().Select(row => row.Record.Key), args.AddedItems.OfType<HistoryRow>().LastOrDefault()?.Record.Key);
            UpdateState();
        };
        table.MouseDoubleClick += (_, args) =>
        {
            if (args.ChangedButton == MouseButton.Left && args.OriginalSource is DependencyObject source
                && ItemsControl.ContainerFromElement(table, source) is ListViewItem { Content: HistoryRow })
                track(history.LoadAsync(history.SelectedRecords.Select(row => row.Key), openDetails: true));
        };
        table.MinHeight = 360; table.Height = 400; listing.Children.Add(table);
        PageCard records = new("记录列表", listing); Grid.SetColumn(records, 2); split.Children.Add(records); body.Children.Add(split);
        Children.Add(new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });
        SizeChanged += (_, _) =>
        {
            var narrow = ActualWidth < 690; split.ColumnDefinitions[0].MinWidth = narrow ? 0 : 210;
            if (narrow) split.ColumnDefinitions[0].Width = new(1, GridUnitType.Star);
            else if (split.ColumnDefinitions[0].Width.IsStar) split.ColumnDefinitions[0].Width = new(260);
            split.ColumnDefinitions[1].Width = new(narrow ? 0 : 12); split.ColumnDefinitions[2].Width = narrow ? new(0) : new(1, GridUnitType.Star);
            Grid.SetColumn(records, narrow ? 0 : 2); Grid.SetRow(records, narrow ? 1 : 0); records.Margin = new(0, narrow ? 16 : 0, 0, 0); divider.Visibility = narrow ? Visibility.Collapsed : Visibility.Visible;
        };
        UpdateState();
    }
    public void RefreshRows()
    {
        var selected = history.SelectedRecords.Select(row => row.Key).ToHashSet(StringComparer.Ordinal);
        refreshing = true;
        try
        {
            var rows = history.Records.Select(record => new HistoryRow(record)).ToArray(); table.ItemsSource = rows;
            foreach (var row in rows.Where(row => selected.Contains(row.Record.Key))) table.SelectedItems.Add(row);
        }
        finally { refreshing = false; }
        if (table.SelectedItems.Count == 0 && table.Items.Count > 0) table.SelectedIndex = 0;
        UpdateState();
    }
    public void UpdateState()
    {
        var selected = history.SelectedRecords; var last = selected.LastOrDefault();
        state.Text = $"共 {history.Records.Count} 条 · 已选 {selected.Count} 条" + (history.Busy ? " · 正在索引或分析…" : "");
        loadButton.IsEnabled = analysisButton.IsEnabled = removeButton.IsEnabled = exportButton.IsEnabled = last is not null && !history.Busy;
        renameButton.IsEnabled = last is not null && !history.Busy && selected.Select(row => row.FilePath).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 1;
        importButton.IsEnabled = !history.ImportPending;
        sourceState.Text = history.DisplayedKey is null ? "悬浮窗：实时日志" : "悬浮窗：历史 · " + (history.Record?.Label ?? "已加载");
        if (!ReferenceEquals(selectedRecord, last)) { selectedRecord = last; summary.SetRecord(last); }
    }
    private void OpenFolder()
    {
        var file = history.SelectedRecords.LastOrDefault()?.FilePath;
        var path = file ?? logDirectory?.Invoke();
        if (path is null) return;
        ProcessStartInfo start = new("explorer.exe") { UseShellExecute = false };
        if (file is not null && File.Exists(file)) start.ArgumentList.Add("/select,");
        start.ArgumentList.Add(file is not null && File.Exists(file) ? file : Directory.Exists(path) ? path : Path.GetDirectoryName(path)!);
        Process.Start(start);
    }
    internal void ImportPaths(IEnumerable<string> paths) => track(history.ImportFilesAsync(paths));
    private void Import()
    {
        OpenFileDialog dialog = new() { Title = "导入战斗 trace", Filter = "战斗日志|*.log;*.jsonl|所有文件|*.*", Multiselect = true };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true) ImportPaths(dialog.FileNames);
    }
    private void Rename()
    {
        if (history.SelectedRecords.LastOrDefault() is not { } row) return;
        var label = Ui.Ask(Window.GetWindow(this), "重命名日志", "同一文件中的战斗及配套输入记录会一起更名", "");
        if (label is null) return;
        var destination = history.Rename(row.FilePath, label); SourceRenamed?.Invoke(row.FilePath, destination); RefreshRows(); notify("日志及配套引用已更新。");
    }
    private void Export()
    {
        if (history.SelectedRecords.LastOrDefault() is not { } row) return;
        SaveFileDialog dialog = new() { Title = "导出所选战斗 · 官网兼容日志", Filter = "战斗日志|*.log", FileName = TraceExportService.DefaultBattleFileName(row), AddExtension = true, DefaultExt = ".log" };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true)
            track(ExportAsync(row, dialog.FileName));
    }
    private async Task ExportAsync(HistoryRecord record, string destination)
    {
        await Task.Run(() => TraceExportService.ExportBattle(record, destination, new SkillResourceCatalog(new ResourceFiles(Path.Combine(ProductApplication.ResolveRoot(), "_internal")))));
        notify("已导出当前战斗的官网兼容日志，完整证据及来源日期保留。");
    }
}
