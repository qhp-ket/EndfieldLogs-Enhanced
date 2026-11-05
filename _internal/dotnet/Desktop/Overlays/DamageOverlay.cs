using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Overlays;

internal sealed class DamageOverlay : IOverlayModule
{
    private sealed record Column(string Key, string Label, string Field);
    private sealed record Row(EvidenceObject Player, string Name, string Crit, string[] Cells, string[] Tips);
    private sealed record LayoutData(OverlayPalette Palette, EvidenceObject Battle, Row[] Rows, Column[] Columns,
        double[] Widths, double NameWidth, double RowHeight, double Avatar, double Header, double Heading, double Footer, string Metric, string Status,
        string[] HeaderValues, double[] HeaderLabelHeights, double Maximum);
    private static readonly string[] headerLabels = ["总伤害", "DPS", "战斗时间"], industrialHeaderLabels = ["团队 DMG", "团队 DPS", "战斗时间"];
    private static readonly Column[] columns = [new("damage", "DMG", "total_damage"), new("damage_rate", "DMG rate", "total_damage"),
        new("rdamage", "rDMG", "total_rd"), new("rdamage_rate", "rDMG rate", "total_rd")];
    private EvidenceObject settings = EvidenceView.Empty(), theme = EvidenceView.Empty(), message = EvidenceView.Empty();
    public string Type => "damage";
    public bool Connected { get; set; } = true;
    private bool recording;
    public void Configure(EvidenceObject settings, EvidenceObject theme) { this.settings = settings; this.theme = theme; }
    public bool Receive(EvidenceObject next)
    {
        if (next.Get("type") is EvidenceText { Value: "recording_state" })
        { var active = next.Get("recording") is EvidenceBoolean { Value: true }; var changedState = active != recording; recording = active; return changedState; }
        if (next.Get("type") is not EvidenceText { Value: "analysis_summary" }) return false;
        var changed = !EvidenceJson.PythonEquals(message.Get("snapshot"), next.Get("snapshot"))
            || !EvidenceJson.PythonEquals(message.Get("source"), next.Get("source")) || !EvidenceJson.PythonEquals(message.Get("error"), next.Get("error"));
        message = next; return changed;
    }
    public OverlayLayout Measure(double dpi, double? width = null)
    {
        var palette = new OverlayPalette(settings, theme); var industrial = palette.Industrial;
        var snapshot = message.Get("snapshot") as EvidenceObject ?? EvidenceView.Empty();
        var battle = snapshot.Get("battle") as EvidenceObject ?? EvidenceView.Empty();
        var metric = EvidenceView.Text(settings.Get("bar_mode")) == "dps" ? "total_damage" : "total_rd";
        var selected = settings.Get("columns") is EvidenceArray items ? items.Items.OfType<EvidenceText>().Select(text => text.Value).ToHashSet() : columns.Select(c => c.Key).ToHashSet();
        var shown = columns.Where(column => selected.Contains(column.Key)).ToArray();
        var normal = OverlayDrawing.Measure("角色", palette, dpi, industrial ? 15 : 13, industrial);
        var secondary = OverlayDrawing.Measure("CRIT", palette, dpi, industrial ? 10 : 13);
        var avatar = EvidenceView.Text(settings.Get("show_character_avatars")) == "off" ? 0 : 40 * Math.Clamp(OverlayDrawing.Parameter(settings, "avatar_size_percent", 100) / 100, .5, 3);
        var rowHeight = Math.Max(avatar + (industrial ? 6 : 10), normal.Height + secondary.Height + (industrial ? 8 : 10));
        var total = OverlayDrawing.Number(battle.Get("total_damage"));
        var rows = EvidenceView.Rows(snapshot.Get("participants")).OrderByDescending(p => OverlayDrawing.Number(p.Get(metric)) ?? 0).Select(player =>
        {
            var name = EvidenceView.Text(player.Get("character_name"), EvidenceView.Text(player.Get("character_key"), "未知角色"));
            var values = shown.Select(c =>
            {
                var number = OverlayDrawing.Number(player.Get(c.Field));
                return c.Key.EndsWith("_rate", StringComparison.Ordinal) ? number is { } n && total > 0 ? (n / total.Value * 100).ToString("N1") + "%" : "—" : OverlayDrawing.Format(player.Get(c.Field), compact: true);
            }).ToArray();
            var crit = OverlayDrawing.Number(player.Get("crit_rate"));
            return new Row(player, name, "CRIT " + (crit is null ? "—" : (crit * 100)?.ToString("N1") + "%"), values,
                shown.Select(c => c.Label + "：" + OverlayDrawing.Format(player.Get(c.Field), 2)).ToArray());
        }).ToArray();
        var nameWidth = Math.Min(420, Math.Max(130, rows.Select(row => OverlayDrawing.Measure(row.Name, palette, dpi, industrial ? 15 : 13, industrial).Width + avatar + 22).DefaultIfEmpty(130).Max()));
        var widths = shown.Select((column, i) => Math.Max(80, Math.Max(OverlayDrawing.Measure(column.Label, palette, dpi).Width + 20,
            rows.Select(row => OverlayDrawing.Measure(row.Cells[i], palette, dpi, industrial ? 19 : 13, industrial, mono: industrial).Width + 20).DefaultIfEmpty(0).Max()))).ToArray();
        var headerValues = new[] { OverlayDrawing.Format(battle.Get("total_damage")), OverlayDrawing.Format(battle.Get("total_dps"), 1), OverlayDrawing.Clock(battle.Get("duration_ms")) };
        var headerCell = Math.Max(headerValues.Select(value => OverlayDrawing.Measure(value, palette, dpi, industrial ? 30 : 20, true).Width).Max(), normal.Width + 32) + 16;
        var naturalWidth = Math.Max(320, Math.Max(nameWidth + widths.Sum() + 24, headerCell * 3 + 48));
        var header = Math.Max(industrial ? 60 : 68, normal.Height + OverlayDrawing.Measure("100", palette, dpi, industrial ? 30 : 20, true).Height + 20);
        var heading = normal.Height + 12; var footer = secondary.Height + (industrial ? 10 : 18);
        var height = header + heading + Math.Max(rowHeight * rows.Length, rowHeight) + footer;
        var quality = snapshot.Get("quality_summary") as EvidenceObject ?? snapshot.Get("snapshot_quality") as EvidenceObject ?? EvidenceView.Empty();
        var source = message.Get("source") as EvidenceObject ?? EvidenceView.Empty();
        var mode = source.Get("mode") is EvidenceText { Value: "history" } ? "历史 · " + EvidenceView.Text(source.Get("label"), "已加载") : "实时";
        var status = message.Get("error") is not EvidenceNull ? "分析异常" : snapshot.Fields.Count == 0 ? "STANDBY // 等待战斗数据"
            : mode + " // " + (EvidenceView.Text(quality.Get("status")) switch { "verified" => "已验证", "provisional" => "暂定", "unavailable" => "证据不可用", _ => "质量未知" });
        if (!Connected) status += " / 连接断开";
        status = (recording ? "记录中" : "未记录") + " · " + status;
        var qualityTip = string.Join("\n", new[] { "rdps", "timing" }.Select(key => key + "：" + EvidenceView.Exact(quality.Get(key))));
        List<OverlayHit> hits = [new(new(0, height - footer, naturalWidth, footer), qualityTip), new(new(0, 0, naturalWidth, header),
            $"总伤害 {OverlayDrawing.Format(battle.Get("total_damage"), 2)}\nDPS {OverlayDrawing.Format(battle.Get("total_dps"), 2)}\n时长 {OverlayDrawing.Clock(battle.Get("duration_ms"))}")];
        for (var index = 0; index < rows.Length; index++)
        {
            var y = header + heading + index * rowHeight; hits.Add(new(new(12, y, nameWidth, rowHeight), rows[index].Name + "\n" + rows[index].Crit));
            var x = nameWidth + 12; for (var column = 0; column < widths.Length; column++) { hits.Add(new(new(x, y, widths[column], rowHeight), rows[index].Tips[column])); x += widths[column]; }
        }
        var labelHeights = (industrial ? industrialHeaderLabels : headerLabels).Select(label => OverlayDrawing.Measure(label, palette, dpi).Height + 8).ToArray();
        var maximum = rows.Select(row => OverlayDrawing.Number(row.Player.Get(metric)) ?? 0).DefaultIfEmpty(0).Max();
        return new(new(naturalWidth, height), hits, new LayoutData(palette, battle, rows, shown, widths, nameWidth, rowHeight, avatar, header, heading, footer, metric, status,
            headerValues, labelHeights, maximum));
    }
    public void Draw(OverlayDrawContext context, Rect area, OverlayLayout layout, double dpi, AvatarCache avatars, double pixelScale)
    {
        var data = (LayoutData)layout.Data!; var palette = data.Palette; palette.PixelScale = pixelScale; var industrial = palette.Industrial;
        if (industrial) OverlayDrawing.Industrial(context, area, data.Header, data.Footer);
        var third = (area.Width - 48) / 3;
        var labels = industrial ? industrialHeaderLabels : headerLabels;
        for (var i = 0; i < 3; i++)
        {
            var x = 12 + i * third; var labelHeight = data.HeaderLabelHeights[i];
            OverlayDrawing.Write(context, labels[i], new(x, 4, third - 8, labelHeight), palette, dpi, brush: industrial ? OverlayDrawing.Brush("#bfb400") : palette["muted"]);
            OverlayDrawing.Write(context, data.HeaderValues[i], new(x, labelHeight + 2, third - 8, data.Header - labelHeight - 6), palette, dpi, industrial ? i == 2 ? 17 : 30 : 20,
                industrial ? Brushes.White : palette["foreground"], true, mono: industrial);
        }
        OverlayDrawing.Write(context, data.Metric == "total_rd" ? "角色 · rDMG 条" : "角色 · DMG 条", new(12, data.Header, data.NameWidth, data.Heading), palette, dpi, brush: palette["muted"]);
        var left = data.NameWidth + 12;
        for (var i = 0; i < data.Columns.Length; i++)
        { OverlayDrawing.Write(context, data.Columns[i].Label, new(left, data.Header, data.Widths[i] - 8, data.Heading), palette, dpi, brush: palette["muted"], align: TextAlignment.Right); left += data.Widths[i]; }
        for (var i = 0; i < data.Rows.Length; i++)
        {
            var row = data.Rows[i]; var y = data.Header + data.Heading + i * data.RowHeight;
            if (industrial) context.DrawRectangle(OverlayDrawing.Brush("#d2ffffff"), OverlayDrawing.Pen(OverlayDrawing.Brush("#bba4ad"), .7), new(8, y, area.Width - 16, data.RowHeight - 3));
            var ratio = data.Maximum > 0 ? Math.Clamp((OverlayDrawing.Number(row.Player.Get(data.Metric)) ?? 0) / data.Maximum, 0, 1) : 0;
            context.DrawRectangle(OverlayDrawing.Alpha(palette["accent"], data.Metric == "total_damage" ? .14 : .22), null, new(8, y, (area.Width - 16) * ratio, data.RowHeight - 3));
            left = 12;
            if (data.Avatar > 0)
            {
                OverlayDrawing.Portrait(context, avatars, EvidenceView.Text(row.Player.Get("character_key")), new(left, y + (data.RowHeight - data.Avatar) / 2, data.Avatar, data.Avatar), false, palette["muted"], "", palette, dpi);
                left += data.Avatar + 8;
            }
            OverlayDrawing.Write(context, row.Name, new(left, y + 3, Math.Max(1, data.NameWidth - (left - 12) - 8), data.RowHeight / 2), palette, dpi, industrial ? 15 : 13, bold: industrial);
            OverlayDrawing.Write(context, row.Crit, new(left, y + data.RowHeight / 2, Math.Max(1, data.NameWidth - (left - 12) - 8), data.RowHeight / 2 - 3), palette, dpi, industrial ? 10 : 13, palette["muted"]);
            left = data.NameWidth + 12;
            for (var j = 0; j < row.Cells.Length; j++)
            { OverlayDrawing.Write(context, row.Cells[j], new(left, y, data.Widths[j] - 8, data.RowHeight), palette, dpi, industrial ? 19 : 13, bold: industrial, align: TextAlignment.Right, mono: industrial); left += data.Widths[j]; }
        }
        if (data.Rows.Length == 0) OverlayDrawing.Write(context, "等待战斗数据", new(12, data.Header + data.Heading, area.Width - 24, data.RowHeight), palette, dpi, brush: palette["muted"]);
        context.DrawEllipse(OverlayDrawing.Brush(recording ? "#e34b55" : "#92969e"), null, new Point(15.5, area.Height - data.Footer / 2), 3.5, 3.5);
        OverlayDrawing.Write(context, data.Status, new(25, area.Height - data.Footer, area.Width - 37, data.Footer), palette, dpi,
            industrial ? 10 : 13, industrial ? palette["foreground"] : palette["muted"]);
    }
}
