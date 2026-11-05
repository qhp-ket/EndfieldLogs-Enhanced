using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Input;
using Microsoft.Win32;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>One battle's binding controls. Dialogs are owned by the persistent battle window.</summary>
internal sealed class InputEvidencePanel : StackPanel, IDisposable
{
    private readonly InputEvidenceController controller;
    private readonly EvidenceObject snapshot;
    private readonly Action<string> notify;
    private readonly CheckBox visible = new() { Content = "显示输入", Margin = new(6), VerticalAlignment = VerticalAlignment.Center };
    private readonly Button menuButton;
    private readonly MenuItem status = new() { IsEnabled = false };
    private bool rendering, closed;
    private string? lastError;
    internal event Action<InputEvidenceState>? Changed;
    internal InputEvidenceState State => controller.State;
    internal InputEvidencePanel(EvidenceObject snapshot, SettingsStore settings, Action<string> notify)
    {
        this.snapshot = snapshot; this.notify = notify; Orientation = Orientation.Horizontal;
        controller = new(snapshot.Get("battle") as EvidenceObject ?? EvidenceView.Empty(), settings);
        Children.Add(visible); ContextMenu menu = new(); menu.Items.Add(status); menu.Items.Add(new Separator());
        void Command(string title, Action action)
        {
            MenuItem entry = new() { Header = title }; entry.Click += (_, _) => _ = Dispatcher.BeginInvoke(new Action(() => { if (!closed) action(); })); menu.Items.Add(entry);
        }
        Command("绑定 input log…", Choose); Command("解除绑定", () => _ = UnbindAsync());
        Command("对齐／槽位…", Alignment); Command("输入解释设置…", Settings);
        menuButton = Ui.Button("输入 ▾", () => { menu.PlacementTarget = menuButton; menu.Placement = PlacementMode.Bottom; menu.IsOpen = true; });
        menuButton.ContextMenu = menu; Children.Add(menuButton);
        visible.Checked += (_, _) => VisibilityChanged(); visible.Unchecked += (_, _) => VisibilityChanged();
        Unloaded += (_, _) => menu.IsOpen = false;
    }
    private void VisibilityChanged()
    {
        if (rendering || closed) return;
        try { controller.SetVisible(visible.IsChecked == true); Render(); } catch (Exception error) { notify(error.Message); }
    }
    internal async Task SetRecordAsync(HistoryRecord record) => await ChangeAsync(() => controller.SetRecordAsync(record));
    internal async Task BindAsync(string path) => await ChangeAsync(() => controller.BindAsync(path));
    internal async Task UnbindAsync() => await ChangeAsync(controller.UnbindAsync);
    internal async Task RelocateAsync(string oldPath, string newPath) => await ChangeAsync(() => controller.RelocateAsync(oldPath, newPath));
    internal async Task AlignAsync(double offset, double? start, IReadOnlyDictionary<int, string> slots) => await ChangeAsync(() => controller.SetAlignmentAsync(offset, start, slots));
    internal async Task ConfigureAsync(EvidenceObject settings) => await ChangeAsync(() => controller.SetSettingsAsync(settings));
    private async Task ChangeAsync(Func<Task> change)
    {
        if (closed) return;
        try
        {
            var task = change(); Render(); await task;
            if (closed) return; controller.Drain(); Render();
        }
        catch (Exception error) { if (!closed) notify(error.Message); }
    }
    private void Choose()
    {
        OpenFileDialog dialog = new() { Title = "绑定 input log", Filter = "输入日志|*.input.jsonl;*.jsonl|所有文件|*.*", InitialDirectory = Path.GetDirectoryName(State.TracePath) ?? "" };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true) _ = BindAsync(dialog.FileName);
    }
    private void Alignment()
    {
        try
        {
            InputAlignmentWindow dialog = new(snapshot, State) { Owner = Window.GetWindow(this) };
            if (Ui.ShowDialog(dialog) == true) _ = AlignAsync(dialog.OffsetMs, dialog.StartOverride, dialog.ManualSlots);
        }
        catch (Exception error) { notify(error.Message); }
    }
    private void Settings()
    {
        InputSettingsWindow dialog = new(State.Settings) { Owner = Window.GetWindow(this) };
        if (Ui.ShowDialog(dialog) == true) _ = ConfigureAsync(dialog.Value);
    }
    private void Render()
    {
        var state = controller.State; rendering = true; visible.IsChecked = state.Visible; rendering = false;
        var count = EvidenceView.Rows(state.Evidence.Get("actions")).Count();
        var text = state.Pending ? "正在读取输入证据…" : state.Error is { } error ? "输入读取失败：" + error : state.Paths.Count == 0 ? "未绑定 input log" : $"{state.Paths.Count} 份输入日志 · {count} 个操作意图";
        var warnings = state.Evidence.Get("warnings") is EvidenceArray rows ? rows.Items.OfType<EvidenceText>().Select(row => row.Value) : [];
        var tip = string.Join("\n", new[] { text }.Concat(state.Paths).Concat(warnings)); status.Header = text; status.ToolTip = tip; menuButton.ToolTip = tip;
        if (state.Error is { Length: > 0 } failure && failure != lastError) notify("输入读取失败：" + failure);
        lastError = state.Error;
        Changed?.Invoke(state);
    }
    public void Dispose() { if (closed) return; closed = true; menuButton.ContextMenu!.IsOpen = false; controller.Dispose(); }
}
