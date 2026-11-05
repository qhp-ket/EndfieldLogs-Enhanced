using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed record ParticipantRow(string Key, string Name, double? Damage, double? Dps, double? RDamage, double? RDps, double? CritRate, string Full);

internal sealed record HistoryRankingRow(int Rank, string Name, double Damage, double Share, double CritRate, double MaxDamage);

internal sealed class BattleSummaryView : Grid
{
    private readonly TextBlock total = Ui.Text("0.00", 22), dps = Ui.Text("0.00", 22), duration = Ui.Text("0.00 秒", 22), mvp = Ui.Text("—", 22);
    private readonly TextBlock quality = Ui.Text("");
    private readonly DataGrid table = Ui.Table();
    private readonly PageCard metricsCard, rankingCard;
    private HistoryRecord? currentRecord;
    public EvidenceObject? Snapshot { get; private set; }
    public BattleSummaryView()
    {
        ColumnDefinitions.Add(new() { Width = new(4, GridUnitType.Star) }); ColumnDefinitions.Add(new() { Width = new(6, GridUnitType.Star) });
        RowDefinitions.Add(new() { Height = GridLength.Auto }); RowDefinitions.Add(new() { Height = GridLength.Auto });
        Grid metrics = new(); metrics.ColumnDefinitions.Add(new()); metrics.ColumnDefinitions.Add(new()); metrics.RowDefinitions.Add(new()); metrics.RowDefinitions.Add(new());
        var tiles = new[] { ("总伤害", total), ("DPS", dps), ("战斗时长", duration), ("MVP", mvp) };
        for (var index = 0; index < tiles.Length; index++)
        {
            StackPanel content = new(); content.Children.Add(Ui.Text(tiles[index].Item1)); tiles[index].Item2.FontWeight = FontWeights.SemiBold; content.Children.Add(tiles[index].Item2);
            Border tile = new() { Child = content, Padding = new(14, 12, 14, 12), CornerRadius = new(8), MinHeight = 95,
                BorderThickness = new(1), BorderBrush = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromArgb(20, 128, 128, 128)), Margin = new(index % 2 == 0 ? 0 : 6, index < 2 ? 0 : 6, index % 2 == 0 ? 6 : 0, index < 2 ? 6 : 0) };
            Grid.SetRow(tile, index / 2); Grid.SetColumn(tile, index % 2); metrics.Children.Add(tile);
        }
        metricsCard = new("核心数据", metrics) { Margin = new(0, 0, 8, 0) }; Children.Add(metricsCard);
        DockPanel ranking = new(); DockPanel.SetDock(quality, Dock.Bottom); ranking.Children.Add(quality); table.MinHeight = 210; table.MaxHeight = 260;
        Ui.Column(table, "排名", nameof(HistoryRankingRow.Rank), true, width: 48); Ui.Column(table, "角色", nameof(HistoryRankingRow.Name), width: 125);
        Ui.Column(table, "总伤害", nameof(HistoryRankingRow.Damage), true, "N2", 95); Ui.Column(table, "占比", nameof(HistoryRankingRow.Share), true, "P2", 75);
        Ui.Column(table, "暴击率", nameof(HistoryRankingRow.CritRate), true, "P2", 75); Ui.Column(table, "最大伤害", nameof(HistoryRankingRow.MaxDamage), true, "N2", 95);
        ranking.Children.Add(table); rankingCard = new("伤害统计", ranking) { Margin = new(8, 0, 0, 0) }; SetColumn(rankingCard, 1); Children.Add(rankingCard);
        SizeChanged += (_, _) =>
        {
            var narrow = ActualWidth < 690; ColumnDefinitions[0].Width = narrow ? new(1, GridUnitType.Star) : new(4, GridUnitType.Star);
            ColumnDefinitions[1].Width = narrow ? new(0) : new(6, GridUnitType.Star); SetColumn(rankingCard, narrow ? 0 : 1); SetRow(rankingCard, narrow ? 1 : 0);
            metricsCard.Margin = new(0, 0, narrow ? 0 : 8, 0); rankingCard.Margin = new(narrow ? 0 : 8, narrow ? 16 : 0, 0, 0);
        };
    }
    public void SetSnapshot(EvidenceObject? snapshot, bool historical = false)
    {
        Snapshot = snapshot;
        if (currentRecord is not null) return;
        if (snapshot is null) { SetRecord(null); return; }
        var battle = snapshot.Get("battle") as EvidenceObject ?? EvidenceView.Empty();
        total.Text = EvidenceView.Format(battle.Get("total_damage"), "N2"); dps.Text = EvidenceView.Format(battle.Get("total_dps"), "N2");
        duration.Text = EvidenceView.Number(battle.Get("duration_ms")) is { } ms ? $"{ms / 1000:N2} 秒" : "未知";
        var participants = EvidenceView.Rows(snapshot.Get("participants")).OrderByDescending(item => EvidenceView.Number(item.Get("total_damage"))).ToArray();
        mvp.Text = participants.FirstOrDefault() is { } best ? EvidenceView.Text(best.Get("character_name"), EvidenceView.Text(best.Get("character_key"))) : "—";
        var amount = EvidenceView.Number(battle.Get("total_damage")) ?? 0;
        table.ItemsSource = participants.Select((item, index) => new HistoryRankingRow(index + 1, EvidenceView.Text(item.Get("character_name"), EvidenceView.Text(item.Get("character_key"))),
            EvidenceView.Number(item.Get("total_damage")) ?? 0, amount <= 0 ? 0 : (EvidenceView.Number(item.Get("total_damage")) ?? 0) / amount,
            EvidenceView.Number(item.Get("crit_rate")) ?? 0, EvidenceView.Number(item.Get("max_hit")) ?? 0)).ToArray();
        var state = snapshot.Get("snapshot_quality") as EvidenceObject ?? snapshot.Get("quality_summary") as EvidenceObject;
        var preflight = snapshot.Get("rdps_preflight") as EvidenceObject;
        quality.Text = state is not null ? "质量状态：" + (EvidenceView.Text(state.Get("status")) switch { "verified" => "已验证", "provisional" => "暂定", "unavailable" => "证据不可用", _ => "未知" })
            : preflight?.Get("ok") is EvidenceBoolean { Value: true } ? "rDPS 证据校验通过" : "rDPS 存在未确认或缺失的证据，详情见战斗分析。";
    }
    internal void SetRecord(HistoryRecord? record)
    {
        currentRecord = record;
        bool ready = record is { AnalysisLoaded: true };
        total.Text = record is null ? "0.00" : ready ? record.TotalDamage.ToString("N2") : "待加载";
        dps.Text = record is null ? "0.00" : ready ? record.Dps.ToString("N2") : "待加载";
        duration.Text = record is null ? "0.00 秒" : ready ? $"{record.DurationMs / 1000d:N2} 秒" : "待加载";
        var players = record?.Players.OrderByDescending(player => player.TotalDamage).ToArray() ?? [];
        mvp.Text = players.FirstOrDefault()?.DisplayName ?? "—"; mvp.ToolTip = mvp.Text;
        table.ItemsSource = ready ? players.Select((player, index) => new HistoryRankingRow(index + 1, player.DisplayName, player.TotalDamage,
            record!.TotalDamage <= 0 ? 0 : player.TotalDamage / record.TotalDamage, player.CritRate / 100, player.MaxDamage)).ToArray() : null;
        quality.Text = record is { AnalysisLoaded: false } ? "待加载 · 点击加载后分析所选战斗" : "";
    }
    internal static ParticipantRow[] Rows(EvidenceObject snapshot) => EvidenceView.Rows(snapshot.Get("participants")).Select(item => new ParticipantRow(
            EvidenceView.Text(item.Get("character_key")), EvidenceView.Text(item.Get("character_name"), EvidenceView.Text(item.Get("character_key"))),
            EvidenceView.Number(item.Get("total_damage")), EvidenceView.Number(item.Get("dps")), EvidenceView.Number(item.Get("total_rd")),
            EvidenceView.Number(item.Get("rdps")), EvidenceView.Number(item.Get("crit_rate")),
            $"DMG：{EvidenceView.Exact(item.Get("total_damage"))}\nrDMG：{EvidenceView.Exact(item.Get("total_rd"))}\nrDPS：{EvidenceView.Exact(item.Get("rdps"))}")).OrderByDescending(row => row.RDamage).ToArray();
}
