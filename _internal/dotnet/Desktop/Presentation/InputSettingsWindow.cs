using System.Collections.ObjectModel;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Input;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class InputRuleRow
{
    public string Action { get; set; } = "skill";
    public int Slot { get; set; }
    public string Keys { get; set; } = "K:49";
    public string Gesture { get; set; } = "tap_hold";
}

internal sealed class InputSettingsWindow : Window
{
    private readonly ObservableCollection<InputRuleRow> rules = [];
    private readonly DataGrid table = Ui.Table();
    private readonly TextBox hold = new() { Width = 90, Margin = new(8), VerticalContentAlignment = VerticalAlignment.Center };
    private readonly CheckBox other = new() { Content = "显示其他输入", Margin = new(6) }, motion = new() { Content = "显示鼠标移动", Margin = new(6) }, axes = new() { Content = "显示手柄模拟量", Margin = new(6) };
    private readonly TextBlock error = Ui.Text("");
    internal EvidenceObject Value { get; private set; }
    internal InputSettingsWindow(EvidenceObject source)
    {
        Value = source; Title = "输入记录与解释设置"; Width = 900; Height = 650; MinWidth = 680; MinHeight = 450; WindowStartupLocation = WindowStartupLocation.CenterOwner;
        DockPanel body = new() { Margin = new(14) }; Content = body;
        var note = Ui.Text("解释结果表示操作意图。K:49–52 为数字 1–4，K:ALT / CTRL / SHIFT 为修饰键，K:69 为 E；手柄使用 P:LB / RB / WEST 等，组合以 + 分隔。");
        DockPanel.SetDock(note, Dock.Top); body.Children.Add(note);
        StackPanel threshold = new() { Orientation = Orientation.Horizontal }; threshold.Children.Add(Ui.Text("长按阈值（参考值，ms）")); threshold.Children.Add(hold); DockPanel.SetDock(threshold, Dock.Top); body.Children.Add(threshold);
        StackPanel footer = new(); DockPanel.SetDock(footer, Dock.Bottom); body.Children.Add(footer);
        WrapPanel filters = new(); filters.Children.Add(other); filters.Children.Add(motion); filters.Children.Add(axes); footer.Children.Add(filters); footer.Children.Add(error);
        WrapPanel buttons = new(); footer.Children.Add(buttons);
        buttons.Children.Add(Ui.Button("增加绑定", () => rules.Add(new())));
        buttons.Children.Add(Ui.Button("删除选中", () => { foreach (var row in table.SelectedItems.Cast<InputRuleRow>().ToArray()) rules.Remove(row); }));
        buttons.Children.Add(Ui.Button("恢复默认", () => Load(EvidenceView.Empty())));
        buttons.Children.Add(Ui.Button("取消", () => DialogResult = false)); buttons.Children.Add(Ui.Button("保存", Save));
        table.IsReadOnly = false; table.SelectionMode = DataGridSelectionMode.Extended; table.ItemsSource = rules;
        void Choices(string title, string path, IReadOnlyList<KeyValuePair<object, string>> choices, double width)
        {
            table.Columns.Add(new DataGridComboBoxColumn { Header = title, SelectedValueBinding = new Binding(path), SelectedValuePath = "Key", DisplayMemberPath = "Value", ItemsSource = choices, Width = width });
        }
        Choices("动作", nameof(InputRuleRow.Action), new[] { ("skill", "战技"), ("ultimate", "终结技"), ("combo", "连携"), ("switch", "切换角色"), ("other", "其他") }.Select(pair => new KeyValuePair<object, string>(pair.Item1, pair.Item2)).ToArray(), 125);
        Choices("角色槽位", nameof(InputRuleRow.Slot), Enumerable.Range(-1, 5).Select(slot => new KeyValuePair<object, string>(slot, slot < 0 ? "全局" : (slot + 1).ToString(CultureInfo.InvariantCulture))).ToArray(), 90);
        table.Columns.Add(new DataGridTextColumn { Header = "原始组合", Binding = new Binding(nameof(InputRuleRow.Keys)), Width = new DataGridLength(1, DataGridLengthUnitType.Star) });
        Choices("判定方式", nameof(InputRuleRow.Gesture), [new("press", "按下／组合成立"), new("tap_hold", "短按战技／长按终结技")], 230);
        body.Children.Add(table); Load(source);
    }
    private void Load(EvidenceObject source)
    {
        var value = InputInterpretationSettings.Normalize(source); hold.Text = value.HoldMs.ToString(CultureInfo.InvariantCulture);
        rules.Clear(); foreach (var rule in value.Bindings) rules.Add(new() { Action = rule.Action, Slot = rule.Slot ?? -1, Keys = string.Join(" + ", rule.Keys), Gesture = rule.Gesture });
        other.IsChecked = value.ShowOther; motion.IsChecked = value.ShowMotion; axes.IsChecked = value.ShowAxes;
    }
    private void Save()
    {
        table.CommitEdit(DataGridEditingUnit.Cell, true); table.CommitEdit(DataGridEditingUnit.Row, true);
        if (!int.TryParse(hold.Text, out var threshold) || threshold is < 1 or > 10000) { error.Text = "长按阈值范围为 1–10000 ms"; return; }
        if (rules.Count > 128) { error.Text = "最多设置 128 条绑定"; return; }
        List<InputRule> bindings = [];
        foreach (var row in rules)
        {
            var keys = row.Keys.Split('+', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).Select(key => key.ToUpperInvariant()).Distinct(StringComparer.Ordinal).ToArray();
            if (keys.Length is < 1 or > 8 || keys.Any(key => key.EnumerateRunes().Count() > 40)) { error.Text = "每条绑定需要 1–8 个按键，每个按键最多 40 字符"; return; }
            bindings.Add(new(row.Action, row.Slot < 0 ? null : row.Slot, keys, row.Gesture));
        }
        Value = new InputInterpretationSettings(threshold, bindings, other.IsChecked == true, motion.IsChecked == true, axes.IsChecked == true).ToEvidence(); DialogResult = true;
    }
}
