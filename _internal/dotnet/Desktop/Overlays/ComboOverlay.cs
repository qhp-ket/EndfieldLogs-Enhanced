using System.Windows;
using System.Windows.Media;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Overlays;

internal sealed class ComboOverlay : IOverlayModule
{
    private sealed record Slot(EvidenceObject Evidence, string Name, string Status, double? Progress, string Label, string Tip);
    private sealed record Data(OverlayPalette Palette, Slot[] Slots, bool Bars, double Avatar, double Top, double Row, double LabelHeight, string Status);
    private EvidenceObject settings = EvidenceView.Empty(), theme = EvidenceView.Empty(), snapshot = EvidenceView.Empty();
    public string Type => "combo_skill";
    public bool Connected { get; set; } = true;
    public void Configure(EvidenceObject settings, EvidenceObject theme) { this.settings = settings; this.theme = theme; }
    public bool Receive(EvidenceObject message)
    {
        if (message.Get("type") is not EvidenceText { Value: "combo_snapshot" } || message.Get("snapshot") is not EvidenceObject next) return false;
        var changed = !EvidenceJson.PythonEquals(next, snapshot); snapshot = next; return changed;
    }
    public OverlayLayout Measure(double dpi, double? width = null)
    {
        var palette = new OverlayPalette(settings, theme); var bars = settings.Get("display_style") is EvidenceText { Value: "bars" };
        var font = OverlayDrawing.Measure("角色", palette, dpi);
        var avatar = (bars ? 32 : 60) * Math.Clamp(OverlayDrawing.Parameter(settings, "avatar_size_percent", 100) / 100, .5, 3);
        var slots = Enumerable.Range(0, 4).Select(index =>
        {
            var item = EvidenceView.Rows(snapshot.Get("slots")).FirstOrDefault(slot => slot.Get("slot") is EvidenceInteger i && i.Value == index) ?? EvidenceView.Empty();
            var status = EvidenceView.Text(item.Get("status"), "unknown");
            var progress = OverlayDrawing.Number(item.Get("progress")) is { } p ? Math.Clamp(p, 0, 1) : (double?)null;
            var remaining = OverlayDrawing.Number(item.Get("estimated_remaining_ms"));
            var label = status switch
            {
                "ready" => "CD 就绪", "unknown" => "—", "dead" => "阵亡", "empty" => "空位",
                _ => (progress is { } value ? (value * 100).ToString("N0") + "%" : "—") + " · " + (remaining is { } ms ? "≈" + (ms / 1000).ToString("N1") + "s" : "—"),
            };
            var name = EvidenceView.Text(item.Get("display_name"), "位置 " + (index + 1));
            var tip = name + "\n" + label + "\n" + (item.Get("held") is EvidenceBoolean { Value: true } ? "沿用上次识别，秒数按已有速度估算" : "图像观测") + "；CD 就绪不等于满足连携触发条件";
            return new Slot(item, name, status, progress, label, tip);
        }).ToArray();
        var held = slots.Any(s => s.Evidence.Get("held") is EvidenceBoolean { Value: true } && s.Status != "unknown");
        var state = held ? "沿用上次状态" : EvidenceView.Text(snapshot.Get("status"), "等待图像识别");
        if (!Connected) state += " / 连接断开";
        var top = font.Height + 18; double row; Size size;
        if (bars)
        {
            row = Math.Max(avatar + 10, font.Height * 2 + 12);
            var natural = Math.Max(420, avatar + slots.Max(s => OverlayDrawing.Measure(s.Name, palette, dpi).Width) + 200);
            size = new(natural, top + row * 4 + 8);
        }
        else
        {
            var cell = Math.Max(90, Math.Max(avatar + 20, Math.Min(180, slots.Max(s => OverlayDrawing.Measure(s.Name, palette, dpi).Width + 12))));
            row = avatar + font.Height * 2 + 24; size = new(cell * 4 + 24, top + row + 8);
        }
        List<OverlayHit> hits = [];
        for (var i = 0; i < 4; i++) hits.Add(new(bars ? new(8, top + i * row, size.Width - 16, row) : new(12 + i * (size.Width - 24) / 4, top, (size.Width - 24) / 4, row), slots[i].Tip));
        hits.Add(new(new(0, 0, size.Width, top), EvidenceView.Text(snapshot.Get("status"), "等待图像识别")));
        OverlayLayout layout = new(size, hits, new Data(palette, slots, bars, avatar, top, row, font.Height + 6, state));
        return bars && width is { } constrained ? ArrangeBars(layout, constrained) : layout;
    }
    internal static OverlayLayout ArrangeBars(OverlayLayout natural, double width)
    {
        // Horizontal stretching changes hit rectangles, not slot values, text metrics or height.
        var delta = width - natural.Size.Width;
        var hits = natural.Hits.Select(hit => hit with { Area = new(hit.Area.X, hit.Area.Y, hit.Area.Width + delta, hit.Area.Height) }).ToArray();
        return natural with { Size = new(width, natural.Size.Height), Hits = hits };
    }
    public void Draw(OverlayDrawContext context, Rect area, OverlayLayout layout, double dpi, AvatarCache avatars, double pixelScale)
    {
        var data = (Data)layout.Data!; var palette = data.Palette; palette.PixelScale = pixelScale;
        if (palette.Industrial) OverlayDrawing.Industrial(context, area, data.Top);
        OverlayDrawing.Write(context, data.Status, new(12, 4, area.Width - 48, data.Top - 4), palette, dpi, brush: palette.Industrial ? OverlayDrawing.Brush("#feef00") : palette["muted"]);
        for (var i = 0; i < 4; i++)
        {
            var slot = data.Slots[i]; var rect = layout.Hits[i].Area;
            var color = palette[slot.Status == "ready" ? "ready" : slot.Status is "unknown" or "dead" or "empty" ? "muted" : "accent"];
            if (slot.Status == "ready")
                context.DrawRoundedRectangle(OverlayDrawing.Alpha(color, .45), OverlayDrawing.Pen(color, 1.2), new(rect.X + 2, rect.Y + 2, rect.Width - 4, rect.Height - 4), 4, 4);
            var icon = new Rect(data.Bars ? rect.Left + 4 : rect.Left + (rect.Width - data.Avatar) / 2, rect.Top + 4, data.Avatar, data.Avatar);
            context.DrawEllipse(OverlayDrawing.Brush("#4646505e"), OverlayDrawing.Pen(color, slot.Status == "ready" ? 2.5 : 1.2), new(icon.X + icon.Width / 2, icon.Y + icon.Height / 2), icon.Width / 2, icon.Height / 2);
            var key = settings.Get("show_character_avatars") is EvidenceText { Value: "off" } ? "" : EvidenceView.Text(slot.Evidence.Get("character_key"));
            OverlayDrawing.Portrait(context, avatars, key, icon, true, color, (i + 1).ToString(), palette, dpi);
            if (!data.Bars && slot.Progress is { } progress)
            {
                if (progress >= 1) context.DrawEllipse(null, OverlayDrawing.Pen(color, 4), new(icon.X + icon.Width / 2, icon.Y + icon.Height / 2), icon.Width / 2, icon.Height / 2);
                else if (progress > 0)
                {
                    context.DrawGeometry(null, OverlayDrawing.Pen(color, 4), ProgressArc(icon, progress));
                }
            }
            if (data.Bars)
            {
                var left = icon.Right + 10; var width = Math.Max(1, rect.Right - left - 8);
                var labelWidth = Math.Min(width * .65, OverlayDrawing.Measure(slot.Label, palette, dpi).Width + 8);
                OverlayDrawing.Write(context, slot.Name, new(left, rect.Y, Math.Max(1, width - labelWidth - 6), data.Row / 2), palette, dpi);
                OverlayDrawing.Write(context, slot.Label, new(left + width - labelWidth, rect.Y, labelWidth, data.Row / 2), palette, dpi, brush: color, align: TextAlignment.Right);
                var track = new Rect(left, rect.Y + data.Row / 2 + 3, width, 8);
                context.DrawRoundedRectangle(OverlayDrawing.Brush("#416e7d91"), null, track, 3, 3);
                context.DrawRoundedRectangle(color, null, new(track.X, track.Y, track.Width * (slot.Progress ?? 0), track.Height), 3, 3);
            }
            else
            {
                OverlayDrawing.Write(context, slot.Name, new(rect.X + 3, icon.Bottom + 5, rect.Width - 6, data.LabelHeight), palette, dpi, align: TextAlignment.Center);
                OverlayDrawing.Write(context, slot.Label, new(rect.X + 3, icon.Bottom + 5 + data.LabelHeight, rect.Width - 6, data.LabelHeight), palette, dpi, brush: color, align: TextAlignment.Center);
            }
        }
    }
    internal static StreamGeometry ProgressArc(Rect icon, double progress)
    {
        var angle = progress * 2 * Math.PI; var center = new Point(icon.X + icon.Width / 2, icon.Y + icon.Height / 2);
        // Same WPF arc and flattening tolerance, without a graph of mutable Freezables per slot/frame.
        StreamGeometry path = new();
        using (var writer = path.Open())
        {
            writer.BeginFigure(new(center.X, icon.Y), true, false);
            writer.ArcTo(new(center.X + icon.Width / 2 * Math.Sin(angle), center.Y - icon.Height / 2 * Math.Cos(angle)),
                new(icon.Width / 2, icon.Height / 2), 0, progress > .5, SweepDirection.Clockwise, true, false);
        }
        path.Freeze(); return path;
    }
}

internal sealed class UidOverlay : IOverlayModule
{
    private bool rounded;
    public string Type => "uid_mask";
    public bool Connected { get; set; } = true;
    public void Configure(EvidenceObject settings, EvidenceObject theme) => rounded = settings.Get("shape") is EvidenceText { Value: "rounded" };
    public bool Receive(EvidenceObject message) => false;
    public OverlayLayout Measure(double pixelsPerDip, double? width = null) => new(new(260, 36), []);
    public void Draw(OverlayDrawContext context, Rect area, OverlayLayout layout, double pixelsPerDip, AvatarCache avatars, double pixelScale)
        => context.DrawRoundedRectangle(Brushes.Black, null, area, rounded ? 8 : 0, rounded ? 8 : 0);
}
