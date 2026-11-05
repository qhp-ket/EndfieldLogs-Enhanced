using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleAnalysisWindow
{
    internal sealed record HitRow(double? Time, string Skill, string Target, double? Damage, double? Basis, string Split, string Element, double? Resistance, double? Poise, EvidenceObject Evidence);
    private readonly Grid analysisArea = new();
    private readonly TabControl pages = new();
    private readonly DockPanel detailPanel = new();
    private readonly TabControl detailTabs = new();
    private readonly GridSplitter divider = new() { Height = 6, HorizontalAlignment = HorizontalAlignment.Stretch, ResizeDirection = GridResizeDirection.Rows, ResizeBehavior = GridResizeBehavior.PreviousAndNext, Background = new SolidColorBrush(Color.FromArgb(35, 128, 128, 128)) };
    private readonly TextBlock allocationSummary = Ui.Text("尚未选择技能块");
    private readonly Button maximizeDetails = new() { Content = "最大化详情", Padding = new(8, 3, 8, 3), Margin = new(4) };
    private IReadOnlyList<TimelineMark> selectedMarks = [];
    private EvidenceObject[]? selectedRows;
    private EvidenceObject? selectedHit;
    private readonly bool[] detailDirty = [true, true, true, true];
    private double detailHeight = 240;
    private bool detailsMaximized;
    internal bool DetailsExpanded { get; private set; }
    internal DataGrid HitTable { get { EnsureDetails(2); return hits; } }
    internal DataGrid ContributionTable { get { EnsureDetails(1); return contributions; } }
    internal string RawEvidence { get { EnsureDetails(3); return raw.Text; } }
    internal string OverviewEvidence { get { EnsureDetails(0); return overview.Text; } }
    internal TabControl DetailsPages => detailTabs;
    internal double DetailsHeight => analysisArea.RowDefinitions[2].ActualHeight;
    private void InitializeDetails()
    {
        analysisArea.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        analysisArea.RowDefinitions.Add(new() { Height = new(0) }); analysisArea.RowDefinitions.Add(new() { Height = new(0) });
        Grid.SetRow(divider, 1); analysisArea.Children.Add(divider); Grid.SetRow(detailPanel, 2); analysisArea.Children.Add(detailPanel);
        WrapPanel actions = new(); DockPanel.SetDock(actions, Dock.Top); detailPanel.Children.Add(actions);
        actions.Children.Add(Ui.Text("详情")); actions.Children.Add(maximizeDetails); actions.Children.Add(Ui.Button("收起详情", () => SetDetails(false)));
        maximizeDetails.Click += (_, _) => MaximizeDetails(!detailsMaximized);
        DockPanel allocation = new(); DockPanel.SetDock(allocationSummary, Dock.Top); allocation.Children.Add(allocationSummary); allocation.Children.Add(contributions);
        detailTabs.Items.Add(new TabItem { Header = "事件概况", Content = overview }); detailTabs.Items.Add(new TabItem { Header = "贡献分配", Content = allocation });
        detailTabs.Items.Add(new TabItem { Header = "逐击证据", Content = hits }); detailTabs.Items.Add(new TabItem { Header = "原始证据", Content = raw }); detailPanel.Children.Add(detailTabs);
        detailTabs.SelectedIndex = 0;
        Ui.Column(contributions, "贡献者", nameof(ContributionShare.Name), width: 200); Ui.Column(contributions, "rDMG", nameof(ContributionShare.Value), true, "N4");
        Ui.Column(contributions, "占已分配 rDMG（%）", nameof(ContributionShare.Percent), true, "N2", 180);
        Ui.Column(hits, "时间／s", nameof(HitRow.Time), true, "N3"); Ui.Column(hits, "技能", nameof(HitRow.Skill), width: 210);
        Ui.Column(hits, "目标／实例", nameof(HitRow.Target), width: 170); Ui.Column(hits, "DMG", nameof(HitRow.Damage), true, "N2"); Ui.Column(hits, "rD 基数", nameof(HitRow.Basis), true, "N4");
        Ui.Column(hits, "rDMG 分配", nameof(HitRow.Split), width: 250); Ui.Column(hits, "元素", nameof(HitRow.Element));
        Ui.Column(hits, "本击抗性／点", nameof(HitRow.Resistance), true, "N2", 140); Ui.Column(hits, "核心匹配失衡值", nameof(HitRow.Poise), true, "N2", 150);
        hits.SelectionChanged += (_, _) =>
        {
            if (hits.SelectedItem is not HitRow hit) return;
            selectedHit = hit.Evidence; detailDirty[3] = true;
            if (DetailsExpanded && detailTabs.SelectedIndex == 3) EnsureDetails(3);
        };
        detailTabs.SelectionChanged += (_, args) =>
        {
            if (ReferenceEquals(args.Source, detailTabs) && DetailsExpanded) EnsureDetails(detailTabs.SelectedIndex);
        };
        divider.DragCompleted += (_, _) => { if (DetailsExpanded && !detailsMaximized) detailHeight = Math.Max(100, DetailsHeight); };
        SetDetails(false);
    }
    internal void SetDetails(bool expanded)
    {
        if (DetailsExpanded && !detailsMaximized && DetailsHeight > 0) detailHeight = Math.Max(100, DetailsHeight);
        DetailsExpanded = expanded; detailsMaximized = false; pages.Visibility = Visibility.Visible;
        analysisArea.RowDefinitions[0].Height = new(1, GridUnitType.Star);
        analysisArea.RowDefinitions[1].Height = new(expanded ? 6 : 0);
        analysisArea.RowDefinitions[2].Height = new(expanded ? Math.Clamp(detailHeight, 100, Math.Max(100, analysisArea.ActualHeight - 120)) : 0);
        detailPanel.Visibility = expanded ? Visibility.Visible : Visibility.Collapsed; divider.Visibility = detailPanel.Visibility;
        maximizeDetails.Content = "最大化详情";
        if (expanded) EnsureDetails(detailTabs.SelectedIndex);
    }
    internal void MaximizeDetails(bool maximized)
    {
        if (!DetailsExpanded) SetDetails(true);
        if (maximized && !detailsMaximized) detailHeight = Math.Max(100, DetailsHeight);
        detailsMaximized = maximized; maximizeDetails.Content = maximized ? "还原详情" : "最大化详情";
        pages.Visibility = maximized ? Visibility.Collapsed : Visibility.Visible;
        divider.Visibility = maximized ? Visibility.Collapsed : Visibility.Visible;
        analysisArea.RowDefinitions[0].Height = maximized ? new(0) : new(1, GridUnitType.Star);
        analysisArea.RowDefinitions[1].Height = new(maximized ? 0 : 6);
        analysisArea.RowDefinitions[2].Height = maximized ? new(1, GridUnitType.Star) : new(Math.Clamp(detailHeight, 100, Math.Max(100, analysisArea.ActualHeight - 120)));
    }
    private void ShowMarks(IReadOnlyList<TimelineMark> marks)
    {
        selectedMarks = marks; selectedRows = null; selectedHit = null;
        Array.Fill(detailDirty, true);
        // Do not retain a potentially very large serialized previous selection while it is hidden.
        raw.Clear();
        if (DetailsExpanded) EnsureDetails(detailTabs.SelectedIndex);
    }
    private void EnsureDetails(int page)
    {
        if (page < 0 || page >= detailDirty.Length || !detailDirty[page] || selectedMarks.Count == 0) return;
        var useFrames = frames.IsChecked == true;
        if (page == 0)
        {
            overview.Text = string.Join("\n\n", selectedMarks.Select(mark => BattleDetails.Description(mark, useFrames)));
            detailDirty[page] = false; return;
        }
        var rows = selectedRows ??= selectedMarks.SelectMany(mark => mark.Evidence).Distinct().ToArray();
        if (page == 3)
        {
            raw.Text = selectedHit is { } hit ? PythonSortedJson.Serialize(hit) : string.Join("\n\n", rows.Select(row => PythonSortedJson.Serialize(row)));
            detailDirty[page] = false; return;
        }
        if (page == 1)
        {
            var summary = BattleEvidence.Summary(rows);
            allocationSummary.Text = $"DMG {summary.Damage:N2} · rD 基数 {BattleDetails.Number(summary.Basis)} · 已分配 {summary.Allocated:N2}\n有分配证据 {summary.Covered}/{summary.Hits} 击；占比以已分配 rDMG 为分母。";
            contributions.ItemsSource = summary.Contributions;
            detailDirty[page] = false; return;
        }
        hits.Columns[0].Header = useFrames ? "时间／F（30F/s）" : "时间／s";
        hits.ItemsSource = rows.Where(row => EvidenceView.Text(row.Get("event_type")) == "damage").Select(row =>
        {
            var stamp = BattleEvidence.Number(row.Get("ts_ms_from_start"));
            var split = string.Join("；", EvidenceView.Rows(row.Get("rdps_contributions")).Select(item => TimelineSkills.CharacterName(EvidenceView.Text(item.Get("character_key")), EvidenceView.Text(item.Get("character_name"))) + " " + BattleDetails.Number(BattleEvidence.Number(item.Get("value")))));
            return new HitRow(stamp / 1000 * (useFrames ? 30 : 1), EvidenceView.Text(row.Get("event_name")), EnemyObservations.Label(row), BattleEvidence.Number(row.Get("value")), BattleEvidence.Number(row.Get("rdps_basis_value")), split.Length > 0 ? split : "未知",
                EnemyObservations.Elements.FirstOrDefault(element => element.Key == EvidenceView.Text(row.Get("damage_element"))).Name ?? "未知属性", EnemyObservations.HitResistance(row),
                row.Get("poise_damage") is EvidenceObject poise ? BattleEvidence.Number(poise.Get("current_value")) : null, row);
        }).ToArray();
        detailDirty[page] = false;
    }
}
