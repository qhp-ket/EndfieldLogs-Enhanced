using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class HomePage : ScrollViewer
{
    internal Button CaptureButton { get; }
    internal Button InputButton { get; }
    internal Button NewRecordingButton { get; }
    internal TextBlock CaptureHint { get; } = Ui.Text("已停止");
    internal TextBlock InputStatus { get; } = Ui.Text("已停止");
    internal TextBlock RecordingStatus { get; } = Ui.Text("未记录");
    internal TextBlock VisionStatus { get; } = Ui.Text("已停止");
    private readonly TextBlock program = Ui.Text("未启动"), game = Ui.Text("等待客户端运行"), server = Ui.Text("未连接"), session = Ui.Text("—");
    private readonly WrapPanel squad = new();
    private readonly AvatarCache avatars;
    private VisionMember[] members = [];

    internal HomePage(string root, Action capture, Action input, Action newRecording, Action hide, Action inputSettings, Action openOverlays)
    {
        avatars = new(root); HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled; VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
        StackPanel body = new() { Margin = new(0, 14, 8, 20) }; Content = body;
        Grid actions = Row();
        WrapPanel captureActions = new(); CaptureButton = Ui.Button("启动抓包", capture, true);
        NewRecordingButton = Ui.Button("开始记录", newRecording); NewRecordingButton.IsEnabled = false;
        NewRecordingButton.ToolTip = "开始时创建新文件组；停止时写完缓冲并关闭文件，实时分析继续运行。默认 Ctrl+I。";
        captureActions.Children.Add(CaptureButton); captureActions.Children.Add(NewRecordingButton);
        actions.Children.Add(captureActions); CaptureHint.Margin = new(8, 0, 12, 0); CaptureHint.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(CaptureHint, 1); actions.Children.Add(CaptureHint);
        var hideButton = Ui.Button("隐藏到托盘", hide); hideButton.Margin = new(0); hideButton.HorizontalAlignment = HorizontalAlignment.Right; body.Children.Add(hideButton);
        hideButton.ToolTip = "一起隐藏 GUI 窗口；抓包、输入记录和悬浮窗继续运行。设置中可修改恢复快捷键。";
        StackPanel damageBody = new(); damageBody.Children.Add(actions);
        captureActions.Children.Add(RecordingStatus); RecordingStatus.VerticalAlignment = VerticalAlignment.Center; RecordingStatus.Margin = new(10, 0, 8, 0);
        var captureNote = Ui.Text("默认不记录。停止记录不影响实时分析；停止抓包后再接续游戏则需重开游戏。"); captureNote.Margin = new(0, 12, 0, 0); damageBody.Children.Add(captureNote);
        AddCard(body, "伤害日志", damageBody);
        StackPanel status = new(); Grid fields = new(); fields.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); fields.ColumnDefinitions.Add(new());
        var values = new[] { ("解析服务", program), ("游戏客户端", game), ("服务器", server), ("当前会话", session) };
        for (var index = 0; index < values.Length; index++)
        {
            fields.RowDefinitions.Add(new() { Height = GridLength.Auto });
            var label = Ui.Text(values[index].Item1); label.FontWeight = FontWeights.SemiBold; label.Margin = new(8, 4, 24, 8);
            Grid.SetRow(label, index); fields.Children.Add(label); var value = values[index].Item2; value.Margin = new(0, 4, 0, 8);
            Grid.SetRow(value, index); Grid.SetColumn(value, 1); fields.Children.Add(value);
        }
        status.Children.Add(fields); var squadLabel = Ui.Text("当前小队"); squadLabel.FontWeight = FontWeights.SemiBold; squadLabel.Margin = new(8, 10, 0, 8);
        status.Children.Add(squadLabel); status.Children.Add(squad); SetMembers([]); AddCard(body, "状态和小队", status);
        StackPanel inputBody = new(); Grid inputRow = Row(); InputButton = Ui.Button("启用输入记录", input, true); inputRow.Children.Add(InputButton);
        InputStatus.VerticalAlignment = VerticalAlignment.Center; InputStatus.Margin = new(8, 0, 12, 0); Grid.SetColumn(InputStatus, 1); inputRow.Children.Add(InputStatus);
        var configure = Ui.Button("输入记录设置", inputSettings); configure.Margin = new(0); Grid.SetColumn(configure, 2); inputRow.Children.Add(configure);
        inputBody.Children.Add(inputRow); var inputNote = Ui.Text("启用后随伤害日志同步记录游戏前台输入；仅输入记录进程申请管理员权限。"); inputNote.Margin = new(0, 12, 0, 0); inputBody.Children.Add(inputNote);
        AddCard(body, "输入记录", inputBody);
        StackPanel visionBody = new(); Grid visionRow = Row(); Grid.SetColumnSpan(VisionStatus, 2); VisionStatus.VerticalAlignment = VerticalAlignment.Center; visionRow.Children.Add(VisionStatus);
        var go = Ui.Button("前往悬浮窗", openOverlays); go.Margin = new(0); Grid.SetColumn(go, 2); visionRow.Children.Add(go); visionBody.Children.Add(visionRow);
        var note = Ui.Text("请在“悬浮窗”页启用连携 CD。识别游戏画面，无需 Npcap；抓包可补充角色身份。"); note.Margin = new(0, 12, 0, 0); visionBody.Children.Add(note);
        AddCard(body, "连携 CD 图像识别", visionBody);
    }
    private static Grid Row()
    {
        Grid row = new(); row.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); row.ColumnDefinitions.Add(new()); row.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); return row;
    }
    private static void AddCard(Panel panel, string title, UIElement content) => panel.Children.Add(new PageCard(title, content) { Margin = new(0, 0, 0, 20) });
    internal void UpdateCapture(CaptureApplicationState state)
    {
        program.Text = state.Stopping ? "正在停止…" : state.Running ? "运行中" : state.Error is null ? "未启动" : "已停止：" + state.Error;
        var flow = state.Status?.Flow;
        if (state.Running && state.Status is { } status)
            CaptureHint.Text = (flow?.State switch { ServiceState.WaitingGame => "等待游戏启动", ServiceState.WaitingRestart => "请重开游戏", ServiceState.WaitingConnection => "等待服务器连接", ServiceState.WaitingHandshake => "等待握手", ServiceState.Live => "正在解析", _ => "正在启动…" })
                + $" · 已收 {status.PacketsSeen:N0} 包 · 丢弃 {status.QueueDrops:N0}";
        game.Text = !state.Running || flow?.State == ServiceState.WaitingGame ? "等待客户端运行" : flow?.State == ServiceState.WaitingRestart ? "需要重开游戏" : "客户端运行中";
        server.Text = flow?.Flow is { } connection ? $"{connection.Server.Ip}:{connection.Server.Port}" : "未连接";
        session.Text = flow?.SessionId ?? "—";
        session.ToolTip = session.Text;
        var next = state.Running ? state.Members.OrderBy(member => member.Slot).ToArray() : [];
        if (!members.SequenceEqual(next)) SetMembers(next);
    }
    internal void SetMembers(IReadOnlyList<VisionMember> next)
    {
        members = next.ToArray(); squad.Children.Clear();
        if (next.Count == 0) { squad.Children.Add(Ui.Text("暂无小队信息")); return; }
        foreach (var member in next.OrderBy(item => item.Slot))
        {
            StackPanel tile = new() { Width = 108, Margin = new(0, 0, 12, 0) };
            var image = avatars.Get(member.CharacterKey);
            FrameworkElement portrait = image is not null ? new Image { Source = image, Width = 56, Height = 56, Stretch = Stretch.UniformToFill }
                : new Border { Width = 56, Height = 56, CornerRadius = new(8), Background = new SolidColorBrush(Color.FromArgb(32, 128, 128, 128)), Child = new TextBlock { Text = member.DisplayName.Length > 0 ? member.DisplayName[..1] : "?", FontSize = 24, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center } };
            tile.Children.Add(portrait); var name = Ui.Text(string.IsNullOrEmpty(member.DisplayName) ? member.CharacterKey : member.DisplayName); name.TextAlignment = TextAlignment.Center; name.ToolTip = member.CharacterKey;
            tile.Children.Add(name); var slot = Ui.Text(member.IsLeader ? "队长" : "#" + (member.Slot + 1)); slot.TextAlignment = TextAlignment.Center; tile.Children.Add(slot); squad.Children.Add(tile);
        }
    }
    internal void UpdateInput(EvidenceObject status)
    {
        var name = EvidenceView.Text(status.Get("status"), "stopped");
        var title = name switch { "stopped" => "已停止", "starting" => "正在启动…", "recording" => "正在记录游戏前台输入", "waiting_game" => "等待游戏前台", "error" => "输入记录故障", _ => name };
        var received = status.Get("input_received") as EvidenceObject; var filtered = status.Get("input_filtered") as EvidenceObject;
        double Count(string key) => Math.Max(0, (EvidenceView.Number(received?.Get(key)) ?? 0) - (EvidenceView.Number(filtered?.Get(key)) ?? 0));
        InputStatus.Text = $"{title} · 键盘 {Count("key"):N0} · 鼠标 {Count("button") + Count("motion") + Count("wheel"):N0} · 缺失 {EvidenceView.Number(status.Get("lost")) ?? 0:N0} 条";
        if (status.Get("privilege") is EvidenceText privilege && privilege.Value.Length > 0) InputStatus.Text += " · " + privilege.Value;
        var error = status.Get("error") as EvidenceText ?? (status.Get("errors") as EvidenceArray)?.Items.LastOrDefault() as EvidenceText;
        if (error is not null) { var detail = error.Value.Split('\n').Last().Trim(); InputStatus.Text += " · " + detail[..Math.Min(180, detail.Length)]; }
        InputStatus.ToolTip = EvidenceView.Text(status.Get("path")) + $"\n文件记录 {EvidenceView.Format(status.Get("count"))} 条（含元数据）\n原始报告计数：{EvidenceView.Exact(status.Get("raw_received"))}\n管理员权限：{EvidenceView.Exact(status.Get("administrator"))}\n采集健康状态：{EvidenceView.Exact(status.Get("capture_health"))}";
    }
}
