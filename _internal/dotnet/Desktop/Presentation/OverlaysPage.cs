using System.IO;
using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;
using Microsoft.Win32;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class OverlaysPage : DockPanel
{
    private sealed record EntryRow(string Id, string Label) { public override string ToString() => Label; }
    private readonly SettingsStore settings;
    private readonly OverlayManager manager;
    private readonly Action<string> notify;
    private readonly ListBox entries = new() { MinWidth = 230, Margin = new(4) };
    private readonly Grid fields = new() { Margin = new(16, 0, 0, 0) };
    private readonly TextBlock counts = Ui.Text("");
    private bool refreshing;
    internal OverlaysPage(SettingsStore settings, OverlayManager manager, Action<string> notify, Action? visionSettings = null)
    {
        this.settings = settings; this.manager = manager; this.notify = notify;
        Resources.MergedDictionaries.Add(new() { Source = new Uri("/EndfieldLogs-Enhanced;component/Presentation/CompactControls.xaml", UriKind.Relative) });
        WrapPanel tools = new();
        tools.Children.Add(Ui.Button("添加伤害统计", () => Add("damage"))); tools.Children.Add(Ui.Button("添加连携 CD", () => Add("combo_skill")));
        tools.Children.Add(Ui.Button("添加 UID 遮挡", () => Add("uid_mask"))); tools.Children.Add(Ui.Button("导入原生皮肤", Import));
        StackPanel body = new() { Margin = new(0, 14, 8, 20) }; body.Children.Add(tools);
        WrapPanel bulk = new();
        bulk.Children.Add(Ui.Button("启用全部", () => SetEnabled(true))); bulk.Children.Add(Ui.Button("停用全部", () => SetEnabled(false)));
        bulk.Children.Add(Ui.Button("隐藏／恢复浮窗", manager.ToggleVisible)); bulk.Children.Add(counts);
        body.Children.Add(new PageCard("一键配置", bulk) { Margin = new(0, 12, 0, 16) });
        if (visionSettings is not null) body.Children.Add(Ui.Button("连携识别设置（图像识别，无需 Npcap）", visionSettings));
        fields.ColumnDefinitions.Add(new() { Width = GridLength.Auto, MinWidth = 100 });
        fields.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        Grid editor = new(); editor.ColumnDefinitions.Add(new() { Width = new(210), MinWidth = 130 });
        editor.ColumnDefinitions.Add(new() { Width = new(8) }); editor.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        editor.RowDefinitions.Add(new() { Height = GridLength.Auto }); editor.RowDefinitions.Add(new() { Height = GridLength.Auto });
        DockPanel list = new() { Width = 240 }; WrapPanel order = new();
        order.Children.Add(Ui.Button("上移", () => Move(-1))); order.Children.Add(Ui.Button("下移", () => Move(1))); order.Children.Add(Ui.Button("移除", Remove));
        list.Width = double.NaN; entries.MinWidth = 0;
        DockPanel.SetDock(order, Dock.Bottom); list.Children.Add(order); list.Children.Add(entries); editor.Children.Add(list);
        GridSplitter divider = new() { Width = 5, HorizontalAlignment = HorizontalAlignment.Center, Background = System.Windows.Media.Brushes.Transparent };
        Grid.SetColumn(divider, 1); editor.Children.Add(divider); Grid.SetColumn(fields, 2); editor.Children.Add(fields);
        body.Children.Add(new PageCard("悬浮窗配置", editor) { Margin = new(0, 16, 0, 0) });
        Children.Add(new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });
        SizeChanged += (_, _) =>
        {
            var narrow = ActualWidth < 720;
            editor.ColumnDefinitions[0].MinWidth = narrow ? 0 : 130;
            editor.ColumnDefinitions[0].Width = narrow ? new(1, GridUnitType.Star) : new(210);
            editor.ColumnDefinitions[1].Width = new(narrow ? 0 : 8); editor.ColumnDefinitions[2].Width = narrow ? new(0) : new(1, GridUnitType.Star);
            Grid.SetColumn(fields, narrow ? 0 : 2); Grid.SetRow(fields, narrow ? 1 : 0);
            fields.Margin = new(narrow ? 0 : 16, narrow ? 16 : 0, 0, 0); entries.MaxHeight = narrow ? 160 : double.PositiveInfinity;
            divider.Visibility = narrow ? Visibility.Collapsed : Visibility.Visible;
        };
        entries.SelectionChanged += (_, _) => { if (!refreshing) BuildFields(); };
        manager.EntriesChanged += Refresh; Refresh();
    }
    private string? Selected => (entries.SelectedItem as EntryRow)?.Id;
    internal void Refresh()
    {
        var id = Selected; refreshing = true;
        try
        {
            entries.ItemsSource = settings.Current.Overlays.Select(entry => new EntryRow(entry.Id, entry.Name + (!entry.Enabled ? " · 停用" : entry.Hidden ? " · 桌面隐藏" : ""))).ToArray();
            entries.SelectedItem = entries.Items.Cast<EntryRow>().FirstOrDefault(row => row.Id == id) ?? entries.Items.Cast<EntryRow>().FirstOrDefault();
        }
        finally { refreshing = false; }
        BuildFields();
        counts.Text = $"{settings.Current.Overlays.Count(row => row.Enabled)} / {settings.Current.Overlays.Count} 项已启用 · {settings.Current.Overlays.Count(row => row.Enabled && !row.Hidden)} 项显示";
    }
    private void SetEnabled(bool enabled) => Guard(() =>
    {
        settings.Update(current => current with { Overlays = current.Overlays.Select(entry => entry with { Enabled = enabled }).ToArray() });
        manager.Sync(); Refresh();
    });
    private void Guard(Action action) { try { action(); } catch (Exception error) { notify(error.Message); } }
    private void Add(string type) => Guard(() =>
    {
        var skin = NativeSkins.Builtin(type); var entry = new OverlaySettings { SourceValue = type, Name = skin.Name };
        settings.Update(current => current with { Overlays = [.. current.Overlays, entry] }); manager.Sync(); Refresh(); entries.SelectedIndex = entries.Items.Count - 1;
    });
    private void Import() => Guard(() =>
    {
        OpenFileDialog dialog = new() { Title = "导入原生皮肤", Filter = "原生皮肤 (*.json)|*.json", CheckFileExists = true };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true) return;
        var skin = NativeSkins.Read(dialog.FileName);
        var entry = new OverlaySettings { SourceType = "file", SourceValue = Path.GetFullPath(dialog.FileName), Name = skin.Name };
        settings.Update(current => current with { Overlays = [.. current.Overlays, entry] }); manager.Sync(); Refresh(); entries.SelectedIndex = entries.Items.Count - 1;
    });
    private void Move(int direction)
    {
        if (Selected is not { } id) return;
        Guard(() => { var rows = settings.Current.Overlays.ToList(); var index = rows.FindIndex(row => row.Id == id); var target = index + direction;
            if (target < 0 || target >= rows.Count) return; (rows[index], rows[target]) = (rows[target], rows[index]); settings.Update(current => current with { Overlays = rows }); Refresh(); });
    }
    private void Remove()
    {
        if (Selected is not { } id) return;
        Guard(() => { settings.Update(current => current with { Overlays = current.Overlays.Where(row => row.Id != id).ToArray() }); manager.Sync(); Refresh(); });
    }
    private void Change(string id, Func<OverlaySettings, OverlaySettings> update, bool rebuild = false)
        => Guard(() => { manager.Update(id, update); if (rebuild) Refresh(); else RefreshList(); });
    private void RefreshList()
    {
        var id = Selected; refreshing = true;
        try
        {
            entries.ItemsSource = settings.Current.Overlays.Select(entry => new EntryRow(entry.Id, entry.Name + (!entry.Enabled ? " · 停用" : entry.Hidden ? " · 桌面隐藏" : ""))).ToArray();
            entries.SelectedItem = entries.Items.Cast<EntryRow>().FirstOrDefault(row => row.Id == id);
            counts.Text = $"{settings.Current.Overlays.Count(row => row.Enabled)} / {settings.Current.Overlays.Count} 项已启用 · {settings.Current.Overlays.Count(row => row.Enabled && !row.Hidden)} 项显示";
        }
        finally { refreshing = false; }
    }
    private void Row(string label, FrameworkElement control)
    {
        var row = fields.RowDefinitions.Count; fields.RowDefinitions.Add(new() { Height = GridLength.Auto });
        var caption = Ui.Text(label); caption.VerticalAlignment = VerticalAlignment.Center; caption.Margin = new(0, 7, 16, 7);
        Grid.SetRow(caption, row); fields.Children.Add(caption);
        control.Margin = new(0, 6, 0, 6); Grid.SetRow(control, row); Grid.SetColumn(control, 1); fields.Children.Add(control);
    }
    private static CheckBox Toggle(string label, bool value, Action<bool> change)
    {
        CheckBox box = new() { Content = label, IsChecked = value, Margin = new(0, 6, 26, 6), VerticalAlignment = VerticalAlignment.Center };
        box.Checked += (_, _) => change(true); box.Unchecked += (_, _) => change(false); return box;
    }
    private void Slider(string label, double value, double min, double max, Action<double> change)
    {
        DockPanel line = new(); TextBlock caption = Ui.Text($"{value:0}%"); caption.MinWidth = 50; caption.TextAlignment = TextAlignment.Right;
        DockPanel.SetDock(caption, Dock.Right); line.Children.Add(caption);
        Slider control = new() { Minimum = min, Maximum = max, Value = value, TickFrequency = 1, IsSnapToTickEnabled = true, MinWidth = 100, VerticalAlignment = VerticalAlignment.Center, Margin = new(0, 0, 10, 0) };
        control.ValueChanged += (_, _) => caption.Text = $"{control.Value:0}%";
        control.PreviewMouseLeftButtonUp += (_, _) => change(control.Value);
        control.LostKeyboardFocus += (_, _) => change(control.Value);
        line.Children.Add(control); Row(label, line);
    }
    private void BuildFields()
    {
        fields.Children.Clear(); fields.RowDefinitions.Clear();
        var entry = settings.Current.Overlays.FirstOrDefault(row => row.Id == Selected);
        if (entry is null) { Row("", Ui.Text("添加浮窗，或导入原生皮肤。")); return; }
        WrapPanel state = new();
        state.Children.Add(Toggle("启用", entry.Enabled, value => Change(entry.Id, current => current with { Enabled = value }, true)));
        var visible = Toggle("显示浮窗", !entry.Hidden, value => Change(entry.Id, current => current with { Hidden = !value }));
        visible.IsEnabled = entry.Enabled; visible.ToolTip = "关闭后保留窗口和绘制，供 OBS 窗口采集继续更新。"; state.Children.Add(visible); Row("状态", state);
        TextBox name = new() { Text = entry.Name, MaxLength = 160, MinHeight = 30, VerticalContentAlignment = VerticalAlignment.Center };
        name.LostKeyboardFocus += (_, _) => { if (name.Text != entry.Name) Change(entry.Id, current => current with { Name = name.Text }); }; Row("名称", name);
        try
        {
            var skin = NativeSkins.For(entry, settings.Context); var values = NativeSkins.Values(entry, skin);
            foreach (var declaration in skin.Settings)
            {
                var key = EvidenceView.Text(declaration.Get("key")); var label = EvidenceView.Text(declaration.Get("label"), key); var kind = EvidenceView.Text(declaration.Get("type"));
                if (kind == "slider")
                { Slider(label, OverlayDrawing.Number(values.Get(key)) ?? 100, OverlayDrawing.Number(declaration.Get("min")) ?? 0, OverlayDrawing.Number(declaration.Get("max")) ?? 100,
                    value => Change(entry.Id, current => NativeSkins.WithValue(current, skin, key, new EvidenceInteger((int)value)))); continue; }
                if (kind == "select")
                {
                    ComboBox select = new() { MinHeight = 30, VerticalContentAlignment = VerticalAlignment.Center };
                    foreach (var option in EvidenceView.Rows(declaration.Get("options"))) select.Items.Add(new ComboBoxItem { Content = EvidenceView.Text(option.Get("label"), EvidenceView.Text(option.Get("value"))), Tag = option.Get("value") });
                    select.SelectedItem = select.Items.Cast<ComboBoxItem>().FirstOrDefault(item => EvidenceJson.PythonEquals((EvidenceValue)item.Tag, values.Get(key)));
                    select.SelectionChanged += (_, _) => { if (select.SelectedItem is ComboBoxItem { Tag: EvidenceValue selected }) Change(entry.Id, current => NativeSkins.WithValue(current, skin, key, selected)); }; Row(label, select);
                }
                else
                {
                    WrapPanel options = new();
                    foreach (var option in EvidenceView.Rows(declaration.Get("options")))
                    {
                        var optionValue = option.Get("value");
                        options.Children.Add(Toggle(EvidenceView.Text(option.Get("label"), EvidenceView.Text(optionValue)), values.Get(key) is EvidenceArray array && array.Items.Any(value => EvidenceJson.PythonEquals(value, optionValue)), active =>
                            Change(entry.Id, current => { var saved = NativeSkins.Values(current, skin).Get(key) as EvidenceArray; var next = saved?.Items.Where(value => !EvidenceJson.PythonEquals(value, optionValue)).ToList() ?? [];
                                if (active) next.Add(optionValue); return NativeSkins.WithValue(current, skin, key, new EvidenceArray(next)); })));
                    }
                    Row(label, options);
                }
            }
        }
        catch (Exception error) { Row("皮肤", Ui.Text(error.Message)); }
        var geometry = manager.Windows.TryGetValue(entry.Id, out var window) ? new OverlayGeometry((int)window.Left, (int)window.Top, (int)window.Width, (int)window.Height) : entry.Geometry;
        Row("窗口", Ui.Text(geometry is null ? "随内容自动适配；拖动边缘等比例缩放。" : $"{geometry.Width} × {geometry.Height} · 拖动边缘等比例缩放"));
        Slider("字体大小", entry.FontScale * 100, 50, 300, value => Change(entry.Id, current => current with { FontScale = value / 100 }));
        DockPanel position = new();
        var reset = Ui.Button("重置布局", () => Change(entry.Id, current => current with { Geometry = null, Scale = 1, FontScale = 1,
            TemplateSettings = new(current.TemplateSettings.Fields.Where(pair => pair.Key is not ("_damage_window_scale" or "_combo_window_scale" or "_native_window_scale")).ToDictionary()) }, true));
        DockPanel.SetDock(reset, Dock.Right); position.Children.Add(reset);
        position.Children.Add(Ui.Text(geometry is null ? "默认位置" : $"X {geometry.X} · Y {geometry.Y}")); Row("位置", position);
        Slider("不透明度", entry.Opacity * 100, 5, 100, value => Change(entry.Id, current => current with { Opacity = value / 100 }));
        WrapPanel mouse = new();
        mouse.Children.Add(Toggle("锁定位置与大小", entry.Locked, value => Change(entry.Id, current => current with { Locked = value })));
        mouse.Children.Add(Toggle("鼠标穿透", entry.ClickThrough, value => Change(entry.Id, current => current with { ClickThrough = value }))); Row("鼠标", mouse);
        if (entry.SourceType == "file") Row("原生皮肤", Ui.Button("重新加载皮肤", () => Guard(() => { manager.Sync(); BuildFields(); })));
    }
}
