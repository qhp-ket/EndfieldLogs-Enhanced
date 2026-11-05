using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using EndfieldLogs.Runtime.Configuration;
using Microsoft.Win32;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class SettingsPage : ScrollViewer
{
    private readonly SettingsStore settings;
    private readonly Action changed;
    private readonly Action<string> notify;
    private readonly Dictionary<string, TextBox> text = [];
    private readonly Dictionary<string, CheckBox> checks = [];
    private readonly ComboBox theme = new() { ItemsSource = new[] { "跟随系统", "浅色", "深色" }, MinWidth = 180 };
    private readonly Slider font = new() { Minimum = 80, Maximum = 180, TickFrequency = 5, IsSnapToTickEnabled = true, MinWidth = 200 };
    public SettingsPage(SettingsStore settings, Action changed, Action<string> notify, UpdatePanel updates, Action<bool>? hotkeyCapture = null)
    {
        this.settings = settings; this.changed = changed; this.notify = notify;
        Resources.MergedDictionaries.Add(new() { Source = new Uri("/EndfieldLogs-Enhanced;component/Presentation/CompactControls.xaml", UriKind.Relative) });
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto; HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
        StackPanel panel = new() { Margin = new(12), MaxWidth = 900, HorizontalAlignment = HorizontalAlignment.Left }; Content = panel;
        var current = settings.Current; var service = current.Service;
        void Field(string key, string label, string value, string? picker = null)
        {
            panel.Children.Add(Ui.Text(label)); DockPanel row = new() { LastChildFill = true, Margin = new(0, 0, 0, 9) };
            TextBox entry = new() { Text = value, MinWidth = 420, VerticalContentAlignment = VerticalAlignment.Center, Padding = new(6, 4, 6, 4) }; text[key] = entry;
            if (picker is not null)
            {
                var button = Ui.Button("选择…", () =>
                {
                    if (picker == "folder")
                    { OpenFolderDialog dialog = new() { Title = label }; if (dialog.ShowDialog(Window.GetWindow(this)) == true) entry.Text = dialog.FolderName; }
                    else
                    { OpenFileDialog dialog = new() { Title = label, Filter = picker == "exe" ? "游戏程序|*.exe|所有文件|*.*" : "所有文件|*.*" }; if (dialog.ShowDialog(Window.GetWindow(this)) == true) entry.Text = dialog.FileName; }
                }); DockPanel.SetDock(button, Dock.Right); row.Children.Add(button);
            }
            row.Children.Add(entry); panel.Children.Add(row);
            if (key.EndsWith("_hotkey", StringComparison.Ordinal))
            {
                var hint = Ui.Text("点击输入框后直接按下组合键。"); hint.FontSize = 12; hint.Margin = new(0, 0, 0, 8); panel.Children.Add(hint);
                entry.GotKeyboardFocus += (_, _) => { hotkeyCapture?.Invoke(true); entry.SelectAll(); hint.Text = "正在录入：请按下组合键；按 Tab 或点击其他位置结束。"; };
                entry.LostKeyboardFocus += (_, _) => { hint.Text = "点击输入框后直接按下组合键。"; hotkeyCapture?.Invoke(false); };
                entry.PreviewKeyDown += (_, args) =>
                {
                    var pressed = args.Key == Key.System ? args.SystemKey : args.Key;
                    if (pressed == Key.Tab) return;
                    args.Handled = true;
                    if (pressed is Key.LeftCtrl or Key.RightCtrl or Key.LeftAlt or Key.RightAlt or Key.LeftShift or Key.RightShift or Key.LWin or Key.RWin) return;
                    var modifiers = Keyboard.Modifiers;
                    var name = pressed switch { Key.Escape => "Esc", Key.Return => "Return", Key.OemMinus => "-", Key.OemPlus => "=", Key.OemComma => ",", Key.OemPeriod => ".", Key.OemQuestion => "/", Key.OemSemicolon => ";", Key.OemQuotes => "'", Key.OemOpenBrackets => "[", Key.OemCloseBrackets => "]", Key.OemPipe => "\\", Key.OemTilde => "`", _ => pressed.ToString() };
                    if (pressed >= Key.D0 && pressed <= Key.D9) name = ((int)pressed - (int)Key.D0).ToString(System.Globalization.CultureInfo.InvariantCulture);
                    entry.Text = (modifiers.HasFlag(ModifierKeys.Control) ? "Ctrl+" : "") + (modifiers.HasFlag(ModifierKeys.Alt) ? "Alt+" : "")
                        + (modifiers.HasFlag(ModifierKeys.Shift) ? "Shift+" : "") + (modifiers.HasFlag(ModifierKeys.Windows) ? "Meta+" : "") + name;
                    entry.CaretIndex = entry.Text.Length;
                };
            }
        }
        void Check(string key, string label, bool value)
        { CheckBox box = new() { Content = label, IsChecked = value, Margin = new(0, 5, 0, 8) }; checks[key] = box; panel.Children.Add(box); }
        panel.Children.Add(Ui.Text("界面", 18)); panel.Children.Add(theme); theme.SelectedIndex = current.ThemeMode switch { "light" => 1, "dark" => 2, _ => 0 };
        panel.Children.Add(Ui.Text("字号比例")); font.Value = current.FontPercent; panel.Children.Add(font);
        Field("game", "游戏程序", Path.Combine(service.NativeGameDirectory, service.GameExecutable), "exe");
        Field("logs", "日志目录", service.LogDirectory, "folder");
        Field("device", "Npcap 设备（auto 自动选择）", service.NpcapDevice);
        Field("port", "本机 WebSocket 端口", service.WebSocketPort.ToString(System.Globalization.CultureInfo.InvariantCulture));
        Check("capture", "启动时开始抓包", current.StartCaptureOnLaunch); Check("input", "启用输入记录（随伤害日志启停）", current.StartInputRecordingOnLaunch || current.InputRecordingEnabled);
        Check("updates", "启动时检查更新", current.CheckUpdatesOnStart); Check("avatars", "显示角色头像", current.ShowCharacterAvatars);
        Check("merge", "合并多阶段敌方战斗", service.MergeMultiPhaseEnemyBattles);
        Field("overlays_hotkey", "悬浮窗显示快捷键", current.ToggleOverlaysHotkey); Field("gui_hotkey", "主窗口显示快捷键", current.ToggleGuiHotkey);
        Field("recording_hotkey", "启停记录快捷键", current.ToggleRecordingHotkey);
        panel.Children.Add(Ui.Text("高级路径", 18));
        Field("rsa", "抓包运行密钥文件", service.RsaKeyPath, "file"); Field("names", "角色名称索引", service.NameIndexPath, "file");
        Check("debug", "保存抓包诊断信息", service.DebugEnabled); Field("debug_dir", "诊断目录", service.DebugDirectory, "folder");
        panel.Children.Add(Ui.Button("保存设置", Save));
        panel.Children.Add(updates);
    }
    internal void Save()
    {
        try
        {
            var game = Path.GetFullPath(text["game"].Text.Trim());
            if (!int.TryParse(text["port"].Text, out var port) || port is < 1 or > 65535) throw new InvalidDataException("WebSocket 端口范围为 1–65535");
            string PathValue(string key) => Path.GetFullPath(text[key].Text.Trim());
            settings.Update(current => current with
            {
                ThemeMode = theme.SelectedIndex switch { 1 => "light", 2 => "dark", _ => "system" }, FontPercent = (int)font.Value,
                ShowCharacterAvatars = checks["avatars"].IsChecked == true, CheckUpdatesOnStart = checks["updates"].IsChecked == true,
                StartCaptureOnLaunch = checks["capture"].IsChecked == true, StartInputRecordingOnLaunch = checks["input"].IsChecked == true,
                InputRecordingEnabled = checks["input"].IsChecked == true,
                ToggleOverlaysHotkey = text["overlays_hotkey"].Text.Trim(), ToggleGuiHotkey = text["gui_hotkey"].Text.Trim(),
                ToggleRecordingHotkey = text["recording_hotkey"].Text.Trim(),
                Service = current.Service with
                {
                    GameExecutable = Path.GetFileName(game), NativeGameDirectory = Path.GetDirectoryName(game)!,
                    LogDirectory = PathValue("logs"), NpcapDevice = text["device"].Text.Trim(), WebSocketPort = port,
                    RsaKeyPath = PathValue("rsa"), NameIndexPath = PathValue("names"), DebugEnabled = checks["debug"].IsChecked == true,
                    DebugDirectory = PathValue("debug_dir"), MergeMultiPhaseEnemyBattles = checks["merge"].IsChecked == true,
                },
            });
            changed(); notify("设置已保存；采集路径和端口在下次启动抓包时应用。");
        }
        catch (Exception error) { notify("保存设置失败：" + error.Message); }
    }
}
