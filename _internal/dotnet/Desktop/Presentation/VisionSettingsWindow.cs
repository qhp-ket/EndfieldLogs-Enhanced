using System.Numerics;
using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class VisionSettingsWindow : Window
{
    private readonly IndependentServiceController controller;
    private readonly SettingsStore settings;
    private readonly ComboBox target = new() { MinWidth = 230, Margin = new(0, 0, 10, 5) }, mode = new() { MinWidth = 140, Margin = new(0, 0, 10, 5) };
    private readonly ComboBox slot = new() { MinWidth = 90, Margin = new(5) }, region = new() { MinWidth = 120, Margin = new(5) };
    private readonly TextBlock status = Ui.Text("");
    private HudSlotRegions[] regions;
    private bool updating, saved, closed;
    internal VisionPreviewCanvas Preview { get; } = new();
    internal ComboBox Mode => mode;
    internal ComboBox Target => target;
    internal EvidenceObject Value => new VisionConfiguration((mode.SelectedValue as string) ?? "auto", mode.SelectedValue as string == "custom" ? regions : [], target.SelectedValue is BigInteger value ? value : 0).ToEvidence();
    internal VisionSettingsWindow(IndependentServiceController controller, SettingsStore settings)
    {
        this.controller = controller; this.settings = settings; var initial = VisionConfiguration.Normalize(settings.Current.VisionSettings);
        regions = (initial.Regions.Count == 4 ? initial.Regions : VisionLayout.Presets()[0].Regions).ToArray();
        Title = "连携 CD 图像识别设置"; Width = 960; Height = 680; MinWidth = 600; MinHeight = 440; WindowPlacement.Initialize(this);
        Ui.ApplyAppearance(this, settings.Current.ThemeMode, settings.Current.FontPercent);
        DockPanel body = new() { Margin = new(14) }; Content = body;
        var note = Ui.Text("识别游戏窗口画面，可独立于抓包使用。CD 就绪表示冷却结束。自动识别不可靠时，按四个槽位分别框选冷却条、血条和阵亡图标。");
        DockPanel.SetDock(note, Dock.Top); body.Children.Add(note);
        WrapPanel controls = new(); DockPanel.SetDock(controls, Dock.Top); body.Children.Add(controls);
        target.DisplayMemberPath = mode.DisplayMemberPath = "Value"; target.SelectedValuePath = mode.SelectedValuePath = "Key";
        target.ItemsSource = TargetOptions(initial.TargetWindow, controller.VisualTargets); target.SelectedValue = initial.TargetWindow;
        mode.ItemsSource = new[] { new KeyValuePair<string, string>("auto", "自动布局"), new("keyboard", "键鼠"), new("gamepad", "手柄"), new("gamepad_expanded", "手柄组合键按住"), new("custom", "手动校准") }; mode.SelectedValue = initial.Layout;
        controls.Children.Add(target); controls.Children.Add(mode); controls.Children.Add(Ui.Button("恢复自动定位", () => mode.SelectedValue = "auto"));
        StackPanel footer = new(); DockPanel.SetDock(footer, Dock.Bottom); body.Children.Add(footer); footer.Children.Add(status);
        WrapPanel selection = new(); footer.Children.Add(selection); selection.Children.Add(Ui.Text("框选目标"));
        slot.ItemsSource = Enumerable.Range(0, 4).Select(index => new KeyValuePair<int, string>(index, $"槽位 {index + 1}")).ToArray();
        region.ItemsSource = new[] { new KeyValuePair<string, string>("energy", "冷却条"), new("hp", "血条"), new("portrait", "阵亡图标") };
        slot.DisplayMemberPath = region.DisplayMemberPath = "Value"; slot.SelectedValuePath = region.SelectedValuePath = "Key"; slot.SelectedIndex = region.SelectedIndex = 0;
        selection.Children.Add(slot); selection.Children.Add(region); selection.Children.Add(Ui.Button("取消", () => DialogResult = false)); selection.Children.Add(Ui.Button("保存", Save));
        body.Children.Add(Preview);
        Preview.RegionSelected += SelectRegion;
        mode.SelectionChanged += (_, _) => ApplyPreview(); target.SelectionChanged += (_, _) => { Preview.ClearPreview(); ApplyPreview(); };
        slot.SelectionChanged += (_, _) => UpdateSelection(); region.SelectionChanged += (_, _) => UpdateSelection();
        IsVisibleChanged += (_, _) => { if (!closed) { controller.SetPreview(IsVisible); if (!IsVisible) Preview.ClearPreview(); } };
        Closed += (_, _) =>
        {
            closed = true; Preview.ClearPreview();
            if (!saved) controller.PreviewVisionSettings(settings.Current.VisionSettings);
            controller.SetPreview(false);
        };
        ApplyPreview();
    }
    private static KeyValuePair<BigInteger, string>[] TargetOptions(BigInteger selected, VisionTargets targets)
    {
        var options = new[] { new KeyValuePair<BigInteger, string>(0, "自动选择（优先前台游戏窗口）") }.Concat(targets.Windows.Select(hwnd => new KeyValuePair<BigInteger, string>(hwnd, $"游戏窗口 0x{hwnd:x}"))).ToList();
        if (selected > 0 && options.All(row => row.Key != selected)) options.Add(new(selected, $"已配置窗口 0x{selected:x}（未发现）")); return options.ToArray();
    }
    private void UpdateSelection()
    { Preview.SelectedSlot = slot.SelectedValue is int index ? index : 0; Preview.SelectedRegion = region.SelectedValue as string ?? "energy"; Preview.InvalidateVisual(); }
    private void SelectRegion(HudRegion value)
    {
        var index = slot.SelectedValue is int selected ? selected : 0; var row = regions[index];
        regions[index] = (region.SelectedValue as string) switch { "hp" => row with { Hp = value }, "portrait" => row with { Portrait = value }, _ => row with { Energy = value } };
        if (mode.SelectedValue as string == "custom") ApplyPreview(); else mode.SelectedValue = "custom";
    }
    private void ApplyPreview()
    {
        if (updating || closed) return;
        try
        {
            controller.PreviewVisionSettings(Value); var chosen = mode.SelectedValue as string ?? "auto";
            Preview.SetRegions(chosen == "custom" ? regions : VisionLayout.Presets().FirstOrDefault(row => row.Name == chosen)?.Regions ?? []);
        }
        catch (Exception error) { status.Text = "预览设置失败：" + error.Message; }
    }
    private void Save()
    {
        try { controller.ConfigureVision(Value); saved = true; DialogResult = true; }
        catch (Exception error) { status.Text = "保存失败：" + error.Message; }
    }
    internal void Refresh()
    {
        if (closed || !IsVisible) return;
        var state = controller.VisualState; var configuration = VisionConfiguration.Normalize(Value); var options = TargetOptions(configuration.TargetWindow, controller.VisualTargets);
        if (target.ItemsSource is not KeyValuePair<BigInteger, string>[] old || !old.SequenceEqual(options))
        {
            updating = true; try { target.ItemsSource = options; target.SelectedValue = configuration.TargetWindow; } finally { updating = false; }
        }
        if (controller.TakePreview() is { } preview) Preview.SetPreview(preview);
        if (configuration.Layout != "custom")
        {
            var observed = VisionConfiguration.Normalize(new EvidenceObject(new Dictionary<string, EvidenceValue> { ["layout"] = new EvidenceText("custom"), ["regions"] = state.Get("regions") }));
            if (observed.Regions.Count == 4) Preview.SetRegions(observed.Regions);
        }
        var targetText = EvidenceView.Number(state.Get("target_hwnd")) is { } hwnd ? $"0x{(long)hwnd:x}" : "等待目标";
        status.Text = EvidenceView.Text(state.Get("status")) + " · " + EvidenceView.Text(state.Get("layout"), "布局未确认") + " · " + targetText + "\n画面仅用于识别与当前预览。";
    }
}
