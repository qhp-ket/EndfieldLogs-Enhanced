using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media.Imaging;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class SkillCompositionPage : DockPanel
{
    internal sealed record SkillRow(string Owner, string Character, string Category, string Skill, string Code, double? Count, double? Damage, double? Percent, double? Average, double? Maximum)
    {
        public string Tooltip => $"{Character} · {Category} · {Skill}\n{Code}";
        public BitmapSource? Portrait { get; init; }
        public double PortraitSize { get; init; }
    }
    internal DataGrid Table { get; } = Ui.Table();
    internal ComboBox Character { get; } = new() { MinWidth = 140, Margin = new(0, 4, 0, 8) };
    private readonly TextBlock empty = Ui.Text("没有技能伤害统计");
    private IReadOnlyList<SkillRow> rows;
    internal void ApplyPresentation(AvatarCache avatars, bool portraits, int portraitPercent, int fontPercent)
    {
        var size = portraits ? 24 * Math.Clamp(portraitPercent / 100d, .5, 3) : 0;
        rows = rows.Select(row => row with { Portrait = portraits ? avatars.Get(row.Owner) : null, PortraitSize = size }).ToArray();
        Table.MinRowHeight = Math.Max(16 * fontPercent / 100d + 8, size + 8); Filter();
    }
    public SkillCompositionPage(EvidenceObject snapshot)
    {
        static string Text(EvidenceObject row, string key) => EvidenceView.Text(row.Get(key));
        rows = SkillComposition.Build(snapshot).Select(row => new SkillRow(Text(row, "character_key"), Text(row, "display_character"), Text(row, "category"), Text(row, "display_skill"), Text(row, "skill_key"),
            BattleEvidence.Number(row.Get("cast_count")), BattleEvidence.Number(row.Get("total_damage")), BattleEvidence.Number(row.Get("damage_percent")), BattleEvidence.Number(row.Get("avg_damage")), BattleEvidence.Number(row.Get("max_damage")))).ToArray();
        var options = new[] { new KeyValuePair<string, string>("", "全部角色") }.Concat(EvidenceView.Rows(snapshot.Get("participants")).Select(row => new KeyValuePair<string, string>(Text(row, "character_key"), TimelineSkills.CharacterName(Text(row, "character_key"), Text(row, "character_name"))))).ToArray();
        Character.ItemsSource = options; Character.DisplayMemberPath = "Value"; Character.SelectedValuePath = "Key"; Character.SelectedIndex = 0;
        SetDock(Character, Dock.Top); Children.Add(Character); SetDock(empty, Dock.Top); Children.Add(empty);
        Ui.Column(Table, "角色", nameof(SkillRow.Character), width: 160); Ui.Column(Table, "分类", nameof(SkillRow.Category), width: 80); Ui.Column(Table, "技能", nameof(SkillRow.Skill), width: 240);
        Ui.Column(Table, "次数", nameof(SkillRow.Count), true, "N0", 75); Ui.Column(Table, "总伤害", nameof(SkillRow.Damage), true, "N0", 120);
        Ui.Column(Table, "占比／%", nameof(SkillRow.Percent), true, "N2", 110); Ui.Column(Table, "平均单次", nameof(SkillRow.Average), true, "N1", 115); Ui.Column(Table, "最大单次", nameof(SkillRow.Maximum), true, "N0", 115);
        var container = new FrameworkElementFactory(typeof(DockPanel));
        var portrait = new FrameworkElementFactory(typeof(Image)); portrait.SetBinding(Image.SourceProperty, new Binding(nameof(SkillRow.Portrait)));
        portrait.SetBinding(WidthProperty, new Binding(nameof(SkillRow.PortraitSize))); portrait.SetBinding(HeightProperty, new Binding(nameof(SkillRow.PortraitSize))); portrait.SetValue(MarginProperty, new Thickness(4)); portrait.SetValue(DockPanel.DockProperty, Dock.Left); container.AppendChild(portrait);
        var name = new FrameworkElementFactory(typeof(TextBlock)); name.SetBinding(TextBlock.TextProperty, new Binding(nameof(SkillRow.Character))); name.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center); name.SetValue(MarginProperty, new Thickness(3)); name.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis); container.AppendChild(name);
        Table.Columns[0] = new DataGridTemplateColumn { Header = "角色", Width = 160, SortMemberPath = nameof(SkillRow.Character), CellTemplate = new DataTemplate { VisualTree = container } };
        var style = new Style(typeof(DataGridRow)); style.Setters.Add(new Setter(ToolTipProperty, new Binding(nameof(SkillRow.Tooltip)))); Table.RowStyle = style;
        Children.Add(Table); Character.SelectionChanged += (_, _) => Filter(); Filter();
    }
    private void Filter()
    {
        var owner = Character.SelectedValue as string ?? ""; Table.ItemsSource = rows.Where(row => owner.Length == 0 || row.Owner == owner).ToArray();
        var view = CollectionViewSource.GetDefaultView(Table.ItemsSource); view.SortDescriptions.Add(new(nameof(SkillRow.Damage), ListSortDirection.Descending));
        Table.Columns[4].SortDirection = ListSortDirection.Descending; empty.Visibility = Table.Items.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }
}
