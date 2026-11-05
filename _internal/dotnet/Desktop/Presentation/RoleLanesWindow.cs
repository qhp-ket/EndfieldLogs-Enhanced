using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class RoleLanesWindow : Window
{
    private readonly IReadOnlyList<TimelineSkillOption> options;
    private readonly List<TimelineSkillLane> rows;
    private readonly ListBox tracks = new() { MinWidth = 180, Margin = new(0, 0, 12, 6) };
    private readonly StackPanel skills = new();
    private readonly TextBox name = new() { Margin = new(0, 0, 0, 10), MaxLength = 60 };
    private readonly TextBlock status = Ui.Text("");
    private bool refreshing;
    internal EvidenceArray Value { get; private set; }
    internal RoleLanesWindow(string title, IReadOnlyList<TimelineSkillOption> options, IReadOnlyList<TimelineSkillLane> lanes)
    {
        this.options = options; rows = lanes.Select(lane => lane with { Skills = lane.Skills.ToArray() }).ToList(); Value = TimelineSkills.Encode(rows);
        Title = title + " · 时间轴设置"; Width = 690; Height = 500; MinWidth = 540; MinHeight = 360; WindowStartupLocation = WindowStartupLocation.CenterOwner;
        DockPanel body = new() { Margin = new(14) }; Content = body;
        var hint = Ui.Text("选择轨道后勾选本场技能；勾选会将技能移到当前轨道。未分配技能归入「其他」。"); DockPanel.SetDock(hint, Dock.Top); body.Children.Add(hint);
        WrapPanel footer = new(); DockPanel.SetDock(footer, Dock.Bottom); body.Children.Add(footer);
        footer.Children.Add(Ui.Button("恢复默认", () => { rows.Clear(); rows.AddRange(TimelineSkills.Defaults(options)); Reload(0); }));
        footer.Children.Add(Ui.Button("取消", () => DialogResult = false)); footer.Children.Add(Ui.Button("保存", () => { Value = TimelineSkills.Encode(rows); DialogResult = true; }));
        DockPanel.SetDock(status, Dock.Bottom); body.Children.Add(status);
        DockPanel left = new() { Width = 220 }; DockPanel.SetDock(left, Dock.Left); body.Children.Add(left);
        WrapPanel actions = new(); DockPanel.SetDock(actions, Dock.Bottom); left.Children.Add(actions);
        actions.Children.Add(Ui.Button("添加轨道", () => { if (rows.Count >= 32) return; rows.Add(new(Guid.NewGuid().ToString(), "轨道 " + (rows.Count + 1), [])); Reload(rows.Count - 1); }));
        actions.Children.Add(Ui.Button("删除", () => { var index = tracks.SelectedIndex; if (index < 0) return; rows.RemoveAt(index); Reload(Math.Min(index, rows.Count - 1)); }));
        actions.Children.Add(Ui.Button("上移", () => Move(-1))); actions.Children.Add(Ui.Button("下移", () => Move(1))); left.Children.Add(tracks);
        DockPanel right = new(); body.Children.Add(right); DockPanel.SetDock(name, Dock.Top); right.Children.Add(name);
        right.Children.Add(new ScrollViewer { Content = skills, VerticalScrollBarVisibility = ScrollBarVisibility.Auto });
        tracks.SelectionChanged += (_, _) => { if (!refreshing) Select(); };
        name.TextChanged += (_, _) =>
        {
            var index = tracks.SelectedIndex; if (refreshing || index < 0) return;
            rows[index] = rows[index] with { Name = name.Text.Length > 0 ? name.Text : "轨道 " + (index + 1) }; Reload(index);
        };
        Reload(0);
    }
    private void Move(int delta)
    {
        var index = tracks.SelectedIndex; var next = index + delta; if (index < 0 || next < 0 || next >= rows.Count) return;
        (rows[index], rows[next]) = (rows[next], rows[index]); Reload(next);
    }
    private void Reload(int selection)
    {
        refreshing = true;
        try { tracks.ItemsSource = rows.Select(row => row.Name).ToArray(); tracks.SelectedIndex = selection; }
        finally { refreshing = false; }
        Select();
    }
    private void Select()
    {
        refreshing = true;
        try
        {
            var index = tracks.SelectedIndex; var row = index >= 0 ? rows[index] : null;
            name.Text = row?.Name ?? ""; name.IsEnabled = row is not null; skills.Children.Clear();
            foreach (var option in options)
            {
                CheckBox check = new() { Content = (option.Category == "大招" ? "终结" : option.Category) + " · " + option.Name,
                    Tag = option.Key, ToolTip = option.Name + "\n" + option.Key, IsChecked = row?.Skills.Contains(option.Key) == true, IsEnabled = row is not null, Margin = new(4, 6, 4, 6) };
                check.Checked += (_, _) => Assign(option.Key, true); check.Unchecked += (_, _) => Assign(option.Key, false); skills.Children.Add(check);
            }
            var unassigned = options.Count(option => !rows.Any(lane => lane.Skills.Contains(option.Key)));
            status.Text = unassigned > 0 ? $"{unassigned} 个技能保留在「其他」回退轨道。" : "每项技能仅分配到一个轨道。";
        }
        finally { refreshing = false; }
    }
    private void Assign(string key, bool active)
    {
        var selected = tracks.SelectedIndex; if (refreshing || selected < 0) return;
        for (var index = 0; index < rows.Count; index++)
        {
            var members = rows[index].Skills.Where(skill => skill != key).ToList(); if (active && selected == index) members.Add(key);
            rows[index] = rows[index] with { Skills = members };
        }
        Select();
    }
}
