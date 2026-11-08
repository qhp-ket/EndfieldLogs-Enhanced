using System.Windows;
using System.Windows.Controls;
using System.IO;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleAnalysisWindow : Window
{
    private readonly BattleTimeline timeline;
    private readonly DataGrid contributions = Ui.Table(), hits = Ui.Table();
    private readonly TextBox overview = EvidenceBox(), raw = EvidenceBox();
    private readonly ComboBox character = new() { MinWidth = 120, Margin = new(4) };
    private readonly Slider timeZoom = new() { Minimum = 1, Maximum = 10, Value = 1, Width = 110, Margin = new(4) };
    private readonly Slider graphScale = new() { Minimum = .75, Maximum = 2.5, Value = 1, Width = 100, Margin = new(4) };
    private readonly CheckBox showBuffs = new() { Content = "BUFF", IsChecked = false, Margin = new(6) }, frames = new() { Content = "帧（30F/s）", Margin = new(6) };
    private readonly DamagePlot plot = new() { Height = 155 };
    private readonly ComboBox metric = new() { ItemsSource = new[] { "累计 rDMG", "累计 DMG", "rDPS", "DPS", "关闭曲线" }, SelectedIndex = 0, MinWidth = 105, Margin = new(4) };
    private readonly EvidenceObject snapshot;
    private string? curveOwner, curveMetric;
    private readonly InputEvidencePanel inputPanel;
    private readonly SettingsStore settings;
    private readonly TablePreferences tables;
    private readonly AvatarCache avatars;
    private readonly TextBlock fallbackStatus = Ui.Text("固定起止回退已开启");
    internal SkillCompositionPage SkillsPage { get; }
    private readonly ScrollViewer diagramScroll = new() { HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    internal ScrollViewer DiagramScroll => diagramScroll;
    internal BattleTimeline Timeline => timeline;
    internal DamagePlot Plot => plot;
    internal InputEvidencePanel InputPanel => inputPanel;
    internal EnemyEvidencePage EnemyPage { get; }
    internal TextBlock SummaryHeader { get; }
    internal BattleAnalysisWindow(EvidenceObject snapshot, SettingsStore settings, HistoryRecord? record = null, Action<string>? notify = null, ResourceFiles? resources = null)
    {
        this.snapshot = snapshot; this.settings = settings; tables = new(settings); avatars = new(settings.Context.ApplicationRoot); Title = "战斗分析 · Endfield Logs"; Width = 1200; Height = 800; MinWidth = 800; MinHeight = 500;
        WindowPlacement.Initialize(this);
        resources ??= new ResourceFiles(Path.Combine(settings.Context.ApplicationRoot, "_internal"));
        timeline = new(snapshot, EnergyObservations.Rules(resources), resources); DockPanel root = new() { Margin = new(12) }; Content = root;
        timeline.SetLaneConfigs(settings.Current.BattleLaneConfigs);
        timeline.LaneSettingsRequested += EditRoleLanes;
        inputPanel = new(snapshot, settings, notify ?? (message => Title = "战斗分析 · " + message));
        inputPanel.Changed += state => timeline.SetInputEvidence(state.Visible ? state.Evidence : EvidenceView.Empty());
        Loaded += async (_, _) => { if (record is not null) await inputPanel.SetRecordAsync(record); };
        Closed += (_, _) => { inputPanel.Dispose(); tables.Save(); };
        var battle = snapshot.Get("battle") as EvidenceObject ?? EvidenceView.Empty();
        var duration = EvidenceView.Number(battle.Get("duration_ms"));
        SummaryHeader = Ui.Text($"{EvidenceView.Text(battle.Get("dungeon_name"))}  ·  DMG {EvidenceView.Format(battle.Get("total_damage"))}  ·  DPS {EvidenceView.Format(battle.Get("total_dps"), "N1")}  ·  {(duration is { } ms ? $"{ms / 1000:N2} 秒" : "时长未知")}", 16);
        var quality = snapshot.Get("snapshot_quality") as EvidenceObject ?? snapshot.Get("quality_summary") as EvidenceObject;
        string State(string key) => EvidenceView.Text((quality?.Get(key) as EvidenceObject)?.Get("status")) switch
            { "verified" => "已验证", "provisional" => "暂定", "unavailable" => "证据不足", _ => "未知" };
        SummaryHeader.ToolTip = $"rDPS：{State("rdps")} · 计时：{State("timing")}。详细证据见显示设置中的角色统计与快照质量。";
        DockPanel.SetDock(SummaryHeader, Dock.Top); root.Children.Add(SummaryHeader);
        root.Children.Add(analysisArea); analysisArea.Children.Add(pages);
        DockPanel timelinePage = new(); WrapPanel controls = new(); DockPanel.SetDock(controls, Dock.Top); timelinePage.Children.Add(controls);
        var options = new[] { new KeyValuePair<string, string>("", "全部角色") }.Concat(EvidenceView.Rows(snapshot.Get("participants")).Select(row => new KeyValuePair<string, string>(EvidenceView.Text(row.Get("character_key")), EvidenceView.Text(row.Get("character_name"))))).ToArray();
        character.ItemsSource = options; character.DisplayMemberPath = "Value"; character.SelectedValuePath = "Key"; character.SelectedIndex = 0;
        controls.Children.Add(character); controls.Children.Add(showBuffs); controls.Children.Add(inputPanel); controls.Children.Add(Ui.Text("时间缩放")); controls.Children.Add(timeZoom);
        controls.Children.Add(frames); controls.Children.Add(Ui.Text("图形大小")); controls.Children.Add(graphScale);
        graphScale.ToolTip = "调整技能块、头像、标记及曲线区域大小；文字大小可在显示设置中单独调整。";
        controls.Children.Add(Ui.Button("适合窗口", () => { timeZoom.Value = 1; timeline.FitToWindow(diagramScroll.ViewportWidth); diagramScroll.ScrollToHorizontalOffset(0); }));
        controls.Children.Add(metric);
        controls.Children.Add(Ui.Button("详情", () => SetDetails(!DetailsExpanded)));
        controls.Children.Add(Ui.Button("显示设置", DisplayOptions));
        fallbackStatus.Visibility = Visibility.Collapsed; controls.Children.Add(fallbackStatus);
        StackPanel diagrams = new(); diagrams.Children.Add(plot); diagrams.Children.Add(timeline);
        diagramScroll.Content = diagrams; timelinePage.Children.Add(diagramScroll);
        diagramScroll.ScrollChanged += (_, _) =>
        {
            var plotHeight = plot.Visibility == Visibility.Visible ? plot.ActualHeight : 0;
            timeline.SetViewport(diagramScroll.HorizontalOffset, Math.Max(0, diagramScroll.VerticalOffset - plotHeight), diagramScroll.ViewportWidth,
                Math.Max(0, diagramScroll.ViewportHeight - Math.Max(0, plotHeight - diagramScroll.VerticalOffset)));
            plot.SetViewport(diagramScroll.HorizontalOffset);
        };
        timeline.LabelWidthChanged += plot.SetLabelWidth;
        timeline.ReferenceChanged += plot.SetReference; plot.ReferenceChanged += timeline.SetReference;
        pages.Items.Add(new TabItem { Header = "战斗时间轴", Content = timelinePage });
        SkillsPage = new(snapshot); tables.Attach("skills", SkillsPage.Table);
        pages.Items.Add(new TabItem { Header = "技能构成", Content = SkillsPage });
        EnemyPage = new(snapshot, timeline.Enemies); pages.Items.Add(new TabItem { Header = "敌方数据", Content = EnemyPage });
        InitializeDetails();
        tables.Attach("contributions", contributions); tables.Attach("hits", hits); tables.Attach("enemy_stats", EnemyPage.Stats); tables.Attach("enemy_poise", EnemyPage.Poise);
        timeline.MarksSelected += ShowMarks;
        character.SelectionChanged += (_, _) => Configure(); showBuffs.Checked += (_, _) => Configure(); showBuffs.Unchecked += (_, _) => Configure();
        frames.Checked += (_, _) => Configure(); frames.Unchecked += (_, _) => Configure(); timeZoom.ValueChanged += (_, _) => Configure(); graphScale.ValueChanged += (_, _) => Configure();
        metric.SelectionChanged += (_, _) => Configure();
        ApplyAppearance(); Configure();
    }
    internal void EditRoleLanes(string owner)
    {
        RoleLanesWindow dialog = new(EvidenceView.Rows(snapshot.Get("participants")).Where(row => EvidenceView.Text(row.Get("character_key")) == owner)
            .Select(row => EvidenceView.Text(row.Get("character_name"), owner)).FirstOrDefault() ?? owner, timeline.SkillOptions(owner), timeline.RoleLanes(owner)) { Owner = this };
        if (Ui.ShowDialog(dialog) != true) return;
        var saved = settings.Current.BattleLaneConfigs.Fields.ToDictionary(); saved[owner] = dialog.Value;
        settings.Update(current => current with { BattleLaneConfigs = SettingsCodec.LaneConfigs(new EvidenceObject(saved)) });
        timeline.SetLaneConfigs(settings.Current.BattleLaneConfigs);
    }
    internal Task RelocateInputAsync(string oldPath, string newPath) => inputPanel.RelocateAsync(oldPath, newPath);
    private static TextBox EvidenceBox() => new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Padding = new(8) };
    private static Dictionary<string, object?> TableRow(EvidenceObject value) => value.Fields.ToDictionary(pair => pair.Key, pair => pair.Value switch
        { EvidenceText text => (object?)text.Value, EvidenceReal number => number.Value, EvidenceInteger number => (double)number.Value, EvidenceBoolean boolean => boolean.Value, _ => null });
    private void Configure()
    {
        var owner = character.SelectedValue as string ?? "";
        timeline.Configure(owner, showBuffs.IsChecked == true, timeZoom.Value, graphScale.Value, frames.IsChecked == true);
        plot.Height = 155 * graphScale.Value;
        if (selectedMarks.Count > 0) ShowMarks(selectedMarks);
        plot.Visibility = metric.SelectedIndex == 4 ? Visibility.Collapsed : Visibility.Visible;
        if (metric.SelectedIndex == 4) return;
        var name = metric.SelectedIndex switch { 1 => "dmg", 2 => "rdps", 3 => "dps", _ => "rdmg" };
        if (curveOwner == owner && curveMetric == name) return;
        plot.SetSeries(DamageSeries.Build(snapshot, name, owner), EvidenceView.Rows(snapshot.Get("participants")).ToDictionary(row => EvidenceView.Text(row.Get("character_key")), row => EvidenceView.Text(row.Get("character_name"))));
        curveOwner = owner; curveMetric = name;
    }
}
