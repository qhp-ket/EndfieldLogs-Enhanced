using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class EnemyEvidencePage : DockPanel
{
    internal DataGrid Stats { get; } = Ui.Table();
    internal DataGrid Poise { get; } = Ui.Table();
    internal DataGrid HitResistance { get; } = Ui.Table();
    internal EnemyEvidencePage(EvidenceObject snapshot, EnemyObservationResult observations)
    {
        var note = Ui.Text("实体抗性是记录时刻的观测点数。本击有效抗性仅在 PKT_ATTR 有一致证据时展示，缺失值显示「未知」。");
        DockPanel.SetDock(note, Dock.Top); Children.Add(note);
        TabControl pages = new(); Children.Add(pages);
        var summary = Ui.Table(); Ui.Column(summary, "敌人／实例", "[name]", width: 260); Ui.Column(summary, "命中", "[count]", true, "N0"); Ui.Column(summary, "DMG", "[damage]", true, "N0");
        summary.ItemsSource = EvidenceView.Rows(snapshot.Get("timeline_events")).Where(row => EvidenceView.Text(row.Get("event_type")) == "damage").GroupBy(EnemyObservations.Identity)
            .Select(group => new Dictionary<string, object?> { ["name"] = EnemyObservations.Label(group.First()), ["count"] = group.Count(), ["damage"] = group.Sum(row => EvidenceView.Number(row.Get("value")) ?? 0) }).ToArray();
        pages.Items.Add(new TabItem { Header = "伤害汇总", Content = summary });
        Ui.Column(Stats, "敌人／实例", "[name]", width: 220); Ui.Column(Stats, "属性记录时间（ms）", "[time]", true, "N3", 150); Ui.Column(Stats, "防御", "[defense]", true, "N2");
        foreach (var (key, name, _) in EnemyObservations.Elements) Ui.Column(Stats, name + "抗性", "[" + key + "]", true, "N2");
        Ui.Column(Stats, "证据", "[evidence]", width: 280);
        var rows = observations.Snapshots.Select(row =>
        {
            var values = new Dictionary<string, object?> { ["name"] = EvidenceView.Text(row.Get("name")), ["time"] = EvidenceView.Number(row.Get("target_stats_snapshot_ts_ms")), ["defense"] = EvidenceView.Number(row.Get("target_defense")),
                ["evidence"] = EvidenceView.Text(row.Get("target_resistance_points_source"), "抗性未知") + " · 解析段行 " + EvidenceView.Exact(row.Get("target_stats_snapshot_line_no")) };
            foreach (var (key, _, _) in EnemyObservations.Elements) values[key] = EvidenceView.Number((row.Get("target_resistance_points") as EvidenceObject)?.Get(key));
            return values;
        }).ToList();
        var observed = observations.Snapshots.Select(row => PythonSortedJson.Serialize(row.Get("key"), compact: true)).ToHashSet(StringComparer.Ordinal);
        foreach (var track in observations.Tracks.Where(track => !observed.Contains(PythonSortedJson.Serialize(new EvidenceArray([new EvidenceText(track.Key.Character), new EvidenceText(track.Key.Actor)]), compact: true))))
        {
            var empty = new Dictionary<string, object?> { ["name"] = track.Name, ["time"] = null, ["defense"] = null, ["evidence"] = "缺少可绑定的 ENTITY_STATS" };
            foreach (var (key, _, _) in EnemyObservations.Elements) empty[key] = null; rows.Add(empty);
        }
        Stats.ItemsSource = rows; pages.Items.Add(new TabItem { Header = "实体属性", Content = Stats });
        Ui.Column(Poise, "敌人／实例", "[name]", width: 240); Ui.Column(Poise, "采样数", "[count]", true, "N0"); Ui.Column(Poise, "首个值", "[first]", true, "N2");
        Ui.Column(Poise, "最后值", "[last]", true, "N2"); Ui.Column(Poise, "观测峰值（非上限）", "[peak]", true, "N2", 160); Ui.Column(Poise, "零值采样数", "[zeros]", true, "N0");
        Poise.ItemsSource = observations.Tracks.Select(track => new Dictionary<string, object?> { ["name"] = track.Name, ["count"] = track.Samples.Count, ["first"] = track.Samples.FirstOrDefault()?.Value,
            ["last"] = track.Samples.LastOrDefault()?.Value, ["peak"] = track.Peak, ["zeros"] = track.Samples.Count > 0 ? track.Samples.Count(point => point.Value <= 0) : null }).ToArray();
        pages.Items.Add(new TabItem { Header = "失衡观测", Content = Poise });
        Ui.Column(HitResistance, "时间（ms）", "[time]", true, "N3"); Ui.Column(HitResistance, "敌人／实例", "[name]", width: 240); Ui.Column(HitResistance, "技能", "[skill]", width: 230);
        Ui.Column(HitResistance, "元素", "[element]"); Ui.Column(HitResistance, "本击有效抗性", "[resistance]", true, "N3", 150);
        HitResistance.ItemsSource = EvidenceView.Rows(snapshot.Get("timeline_events")).Where(row => EvidenceView.Text(row.Get("event_type")) == "damage").Select(row => new Dictionary<string, object?>
        {
            ["time"] = EvidenceView.Number(row.Get("ts_ms_from_start")), ["name"] = EnemyObservations.Label(row), ["skill"] = EvidenceView.Text(row.Get("event_name")),
            ["element"] = EnemyObservations.Elements.FirstOrDefault(element => element.Key == EvidenceView.Text(row.Get("damage_element"))).Name ?? "未知", ["resistance"] = EnemyObservations.HitResistance(row),
        }).ToArray();
        pages.Items.Add(new TabItem { Header = "逐击有效抗性", Content = HitResistance });
        var foot = Ui.Text("失衡按 POISE_V1 同刻技能配对；多目标歧义放入「目标未绑定」。曲线使用观测值，峰值不代表真实上限，零值不代表完整失衡持续时间。");
        DockPanel.SetDock(foot, Dock.Bottom); Children.Insert(1, foot);
    }
}
