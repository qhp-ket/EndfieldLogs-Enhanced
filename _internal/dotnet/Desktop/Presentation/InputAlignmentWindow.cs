using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Input;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class InputAlignmentWindow : Window
{
    private readonly TextBox date = new(), offset = new();
    private readonly ComboBox[] slots = new ComboBox[4];
    private readonly TextBlock error = Ui.Text("");
    private readonly InputEvidenceState initial;
    private readonly string originalDate, initialDate;
    internal double OffsetMs { get; private set; }
    internal double? StartOverride { get; private set; }
    internal IReadOnlyDictionary<int, string> ManualSlots { get; private set; } = new Dictionary<int, string>();
    internal InputAlignmentWindow(EvidenceObject snapshot, InputEvidenceState state)
    {
        initial = state; Title = "输入日志对齐与手动槽位"; Width = 570; SizeToContent = SizeToContent.Height; WindowStartupLocation = WindowStartupLocation.CenterOwner; ResizeMode = ResizeMode.NoResize;
        StackPanel body = new() { Margin = new(16) }; Content = body; body.Children.Add(Ui.Text("时间偏移和槽位只影响输入证据的展示。"));
        var battle = snapshot.Get("battle") as EvidenceObject ?? EvidenceView.Empty(); var anchor = new InputEvidenceLoader().BattleStartWallMs(battle);
        string Format(double value) => DateTimeOffset.FromUnixTimeMilliseconds((long)value).ToLocalTime().ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture);
        originalDate = Format(anchor); initialDate = state.StartOverride is { } start ? Format(start) : originalDate;
        date.Text = initialDate; offset.Text = state.OffsetMs.ToString("0.###", CultureInfo.InvariantCulture);
        void Field(string label, Control control) { body.Children.Add(Ui.Text(label)); control.Margin = new(0, 0, 0, 8); control.Padding = new(5); body.Children.Add(control); }
        Field("战斗起点（本地日期时间）", date); Field("输入偏移（ms）", offset);
        var options = new[] { new KeyValuePair<string, string>("", "使用 trace LOADOUT；缺失时显示槽位") }.Concat(EvidenceView.Rows(snapshot.Get("participants")).Select(row => new KeyValuePair<string, string>(EvidenceView.Text(row.Get("character_key")), EvidenceView.Text(row.Get("character_name"))))).ToArray();
        for (var index = 0; index < slots.Length; index++)
        {
            var entry = slots[index] = new() { ItemsSource = options, DisplayMemberPath = "Value", SelectedValuePath = "Key", SelectedValue = state.ManualSlots.GetValueOrDefault(index, "") };
            Field($"角色槽位 {index + 1}", entry);
        }
        body.Children.Add(error); WrapPanel actions = new(); body.Children.Add(actions);
        actions.Children.Add(Ui.Button("恢复自动对齐", () => { date.Text = originalDate; offset.Text = "0"; foreach (var entry in slots) entry.SelectedValue = ""; }));
        actions.Children.Add(Ui.Button("取消", () => DialogResult = false)); actions.Children.Add(Ui.Button("应用", Save));
    }
    private void Save()
    {
        if (!double.TryParse(offset.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) || !double.IsFinite(value) || Math.Abs(value) > 86400000) { error.Text = "输入偏移应在 ±86400000 ms 内"; return; }
        double? start;
        var chosen = date.Text.Trim();
        if (chosen.Length == 0 || chosen == originalDate) start = null;
        else if (chosen == initialDate) start = initial.StartOverride;
        else if (DateTimeOffset.TryParse(chosen, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out var parsed)) start = parsed.ToUnixTimeMilliseconds();
        else { error.Text = "日期格式示例：2026-10-29T17:30:00.000"; return; }
        OffsetMs = value; StartOverride = start;
        ManualSlots = Enumerable.Range(0, slots.Length).Where(index => slots[index].SelectedValue is string { Length: > 0 }).ToDictionary(index => index, index => (string)slots[index].SelectedValue);
        DialogResult = true;
    }
}
