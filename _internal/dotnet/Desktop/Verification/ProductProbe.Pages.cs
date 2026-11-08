using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Desktop.Overlays;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    /// <summary>Render the actual product pages without HWNDs, foreground changes or hardware services.</summary>
    internal static int RunPageChecks(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        Dictionary<string, bool> checks = [];
        var temporary = Directory.CreateTempSubdirectory("endfield-page-layout-");
        Window? host = null;
        void Check(string name, bool value) { checks[name] = value; if (!value) throw new InvalidOperationException(name); }
        try
        {
            Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            host = new();
            var codec = new SettingsCodec(new(temporary.FullName)); var settings = new SettingsStore(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")), codec);
            var snapshot = (EvidenceObject)EvidenceJson.Parse("""{"battle":{"total_damage":3000,"total_dps":750,"duration_ms":4000},"participants":[{"character_key":"chr_0001_test","character_name":"角色甲","total_damage":2000,"max_hit":1200,"crit_hits":1,"hit_count":2},{"character_key":"chr_0002_test","character_name":"角色乙","total_damage":1000,"max_hit":1000,"crit_hits":0,"hit_count":1}]}""");
            using var history = new HistoryController(settings, new(Path.Combine(temporary.FullName, "cache")), (_, _) => Task.FromResult(snapshot));
            var path = Path.Combine(temporary.FullName, "trace_synthetic.log");
            File.WriteAllText(path, "[00:00:00.000] LOADOUT reason=squad\n[00:00:00.000] LOADOUT slot=0 char=chr_0001_test\n[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100\n");
            var original = File.ReadAllBytes(path);
            history.ImportFilesAsync([path]).GetAwaiter().GetResult(); history.Drain();
            Check("history_fixture_indexes", history.Records.Count == 1);
            var requests = 0; var returnedLive = 0; var summary = new BattleSummaryView();
            HistoryPage page = new(history, task => { requests++; task.GetAwaiter().GetResult(); }, message => throw new InvalidOperationException(message), () => { returnedLive++; history.ReturnLive(); }, summary);
            Button FindButton(FrameworkElement root, string text) => Descendants<Button>(root).Single(button => Equals(button.Content, text));
            void Layout(FrameworkElement content, string theme, double width, double height, int font = 100)
            {
                host.Content = content; Ui.ApplyAppearance(host, theme, font);
                content.Measure(new(width, height)); content.Arrange(new(0, 0, width, height)); content.UpdateLayout();
                Check("no_native_window_" + theme + "_" + width + "_" + font, PresentationSource.FromVisual(host) is null);
            }
            void Save(FrameworkElement content, string name, double width = 940, double height = 720)
            {
                RenderTargetBitmap bitmap = new((int)width, (int)height, 96, 96, PixelFormats.Pbgra32);
                DrawingVisual backdrop = new(); using (var drawing = backdrop.RenderOpen()) drawing.DrawRectangle(host.Background, null, new(0, 0, width, height));
                bitmap.Render(backdrop); bitmap.Render(content);
                PngBitmapEncoder png = new(); png.Frames.Add(BitmapFrame.Create(bitmap)); using var file = File.Create(Path.ChangeExtension(output, "." + name + ".png")); png.Save(file);
            }
            Layout(page, "light", 940, 720);
            Check("history_empty_selection_disables_mutating_actions", !FindButton(page, "加载选中记录").IsEnabled && !FindButton(page, "重命名文件…").IsEnabled);
            page.RefreshRows();
            Check("history_refresh_selects_first_record", history.SelectedRecords.Count == 1);
            Layout(page, "light", 940, 720);
            var list = page.RecordsTable;
            var row = (HistoryRow)list.SelectedItem;
            var card = (ListViewItem)list.ItemContainerGenerator.ContainerFromItem(row);
            Check("history_defaults_to_two_line_record_cards", list.View is null && Descendants<TextBlock>(card).Select(text => text.Text).SequenceEqual([row.Name, row.Description]));
            var display = Descendants<ComboBox>(page).Single(); display.SelectedIndex = 1;
            Check("history_detail_table_retains_selection", list.View is GridView && ReferenceEquals(list.SelectedItem, row) && history.SelectedRecords.Count == 1);
            display.SelectedIndex = 0;
            Check("history_record_cards_retain_selection", list.View is null && ReferenceEquals(list.SelectedItem, row));
            FindButton(page, "全选").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Check("history_select_all_updates_actions", history.SelectedRecords.Count == 1 && FindButton(page, "加载选中记录").IsEnabled && FindButton(page, "重命名文件…").IsEnabled);
            Check("history_original_directory_entry", FindButton(page, "打开所在文件夹").IsEnabled);
            FindButton(page, "加载选中记录").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); history.Drain(); page.RefreshRows();
            Check("history_load_preserves_controller_path", requests == 1 && history.DisplayedKey is not null && history.Records[0].AnalysisLoaded);
            Layout(page, "light", 940, 720);
            Check("history_core_metrics_and_mvp", Descendants<TextBlock>(summary).Any(text => text.Text == "3,000.00") && Descendants<TextBlock>(summary).Any(text => text.Text == "角色甲"));
            var rankings = Descendants<DataGrid>(summary).Single().Items.OfType<HistoryRankingRow>().ToArray();
            Check("history_ranking_exact_existing_values", rankings.Length == 2 && rankings[0] is { Rank: 1, Damage: 2000, MaxDamage: 1200, CritRate: .5 } && rankings[1].Share == 1000d / 3000);
            var calls = new int[6];
            using OverlayManager overlays = new(settings, message => throw new InvalidOperationException(message));
            OverlaysPage overlayPage = new(settings, overlays, message => throw new InvalidOperationException(message));
            HomePage home = new(temporary.FullName, () => calls[0]++, () => calls[1]++, () => calls[2]++, () => calls[3]++, () => calls[4]++, () => calls[5]++);
            List<bool> captures = [];
            using UpdatePanel updates = new(settings, _ => { });
            SettingsPage settingsPage = new(settings, () => { }, _ => { }, updates, captures.Add);
            Layout(settingsPage, "dark", 940, 1600);
            var shortcutEdits = Descendants<TextBox>(settingsPage).Where(entry => entry.Text is "Ctrl+I" or "Ctrl+O" or "Ctrl+Shift+O").ToArray();
            Check("settings_three_shortcuts_include_recording", shortcutEdits.Length == 3);
            foreach (var edit in shortcutEdits)
            {
                edit.RaiseEvent(new KeyboardFocusChangedEventArgs(Keyboard.PrimaryDevice, 0, null, edit) { RoutedEvent = Keyboard.GotKeyboardFocusEvent });
                Check("settings_capture_hint_" + edit.Text, captures.Last() && Descendants<TextBlock>(settingsPage).Any(label => label.Text.StartsWith("正在录入", StringComparison.Ordinal)));
                edit.RaiseEvent(new KeyboardFocusChangedEventArgs(Keyboard.PrimaryDevice, 0, edit, null) { RoutedEvent = Keyboard.LostKeyboardFocusEvent });
                Check("settings_capture_finished_" + edit.Text, !captures.Last() && !Descendants<TextBlock>(settingsPage).Any(label => label.Text.StartsWith("正在录入", StringComparison.Ordinal)));
            }
            Layout(home, "light", 940, 720);
            home.UpdateInput((EvidenceObject)EvidenceJson.Parse("""{"status":"recording","count":20,"lost":1,"input_received":{"key":12,"button":7},"input_filtered":{"key":2,"button":3},"path":"synthetic.input.jsonl"}"""));
            Check("home_input_counts_and_health", home.InputStatus.Text.Contains("键盘 10", StringComparison.Ordinal) && home.InputStatus.Text.Contains("鼠标 4", StringComparison.Ordinal) && home.InputStatus.Text.Contains("缺失 1", StringComparison.Ordinal) && ((string)home.InputStatus.ToolTip).Contains("synthetic.input.jsonl", StringComparison.Ordinal));
            foreach (var text in new[] { "启动抓包", "启用输入记录", "隐藏到托盘", "输入记录设置", "前往悬浮窗" }) FindButton(home, text).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Check("home_commands_keep_independent_actions", calls.SequenceEqual([1, 1, 0, 1, 1, 1]) && !home.NewRecordingButton.IsEnabled);
            home.SetMembers([new(0, "chr_0001_test", "角色甲", true), new(1, "chr_0002_test", "角色乙"), new(2, "chr_0003_test", "角色丙"), new(3, "chr_0004_test", "角色丁")]);
            foreach (var theme in new[] { "dark", "light" })
            {
                Layout(home, theme, 940, 720);
                Check(theme + "_home_sections", Descendants<TextBlock>(home).Select(text => text.Text).Contains("状态和小队") && Descendants<TextBlock>(home).Any(text => text.Text == "连携 CD 图像识别"));
                Check(theme + "_home_four_members", Descendants<TextBlock>(home).Count(text => text.Text.StartsWith('#') || text.Text == "队长") == 4);
                Save(home, theme + "-home");
                Layout(settingsPage, theme, 940, 1600); Save(settingsPage, theme + "-settings", 940, 1600);
                Check(theme + "_settings_control_contrast", Descendants<CheckBox>(settingsPage).All(box => box.Foreground is SolidColorBrush ink
                    && (theme == "dark" ? ink.Color.R > 180 : ink.Color.R < 100)));
                var recordingEdit = shortcutEdits.Single(edit => edit.Text == "Ctrl+I");
                recordingEdit.RaiseEvent(new KeyboardFocusChangedEventArgs(Keyboard.PrimaryDevice, 0, null, recordingEdit) { RoutedEvent = Keyboard.GotKeyboardFocusEvent });
                Check(theme + "_recording_hint_visible", Descendants<TextBlock>(settingsPage).Any(label => label.Text.StartsWith("正在录入", StringComparison.Ordinal)));
                settingsPage.UpdateLayout();
                Save(settingsPage, theme + "-recording-hotkey", 940, 1600);
                recordingEdit.RaiseEvent(new KeyboardFocusChangedEventArgs(Keyboard.PrimaryDevice, 0, recordingEdit, null) { RoutedEvent = Keyboard.LostKeyboardFocusEvent });
                File.WriteAllText(Path.ChangeExtension(output, "." + theme + "-buttons.json"), JsonSerializer.Serialize(Descendants<Button>(home).Where(button => button.Content is string).Select(button => new { text = button.Content, width = button.ActualWidth, height = button.ActualHeight, desired_width = button.DesiredSize.Width })));
                Check(theme + "_home_button_bounds", Descendants<Button>(home).Where(button => button.Content is string).All(button => button.ActualHeight >= 30 && button.ActualHeight <= 44 && button.ActualWidth + button.Margin.Left + button.Margin.Right >= button.DesiredSize.Width - 1));
                Layout(page, theme, 940, 720); Save(page, theme + "-history");
                Layout(overlayPage, theme, 1040, 900); Save(overlayPage, theme + "-overlays", 1040, 900);
                Check(theme + "_overlay_geometry_read_only", Descendants<TextBox>(overlayPage).Length == 1);
                var toggles = Descendants<CheckBox>(overlayPage);
                Check(theme + "_overlay_state_group", toggles.Any(box => Equals(box.Content, "启用")) && toggles.Any(box => Equals(box.Content, "显示浮窗"))
                    && ReferenceEquals(System.Windows.Media.VisualTreeHelper.GetParent(toggles.Single(box => Equals(box.Content, "启用"))), System.Windows.Media.VisualTreeHelper.GetParent(toggles.Single(box => Equals(box.Content, "显示浮窗")))));
                Check(theme + "_overlay_multi_select_compact", toggles.Where(box => Equals(box.Content, "DMG") || Equals(box.Content, "rDMG")).All(box => VisualTreeHelper.GetParent(box) is WrapPanel));
                Layout(page, theme, 940, 720);
                Check(theme + "_history_table_contrast", Descendants<DataGridCell>(summary).All(cell => cell.Foreground is SolidColorBrush ink && (theme == "dark" ? ink.Color.R > 180 : ink.Color.R < 100)));
                var tableText = Descendants<DataGridCell>(summary).SelectMany(cell => Descendants<TextBlock>(cell))
                    .Concat(Descendants<System.Windows.Controls.Primitives.DataGridColumnHeader>(summary).SelectMany(header => Descendants<TextBlock>(header)))
                    .Where(text => text.Text.Length > 0).ToArray();
                Check(theme + "_history_rendered_table_text_contrast", tableText.Length > 0
                    && tableText.All(text => text.Foreground is SolidColorBrush ink && (theme == "dark" ? ink.Color.R > 180 : ink.Color.R < 100)));
                Check(theme + "_history_sections", new[] { "核心数据", "伤害统计", "记录操作", "记录列表" }.All(title => Descendants<TextBlock>(page).Any(text => text.Text == title)));
                Layout(home, theme, 520, 720, 150); Save(home, theme + "-home-narrow", 520, 720);
                Check(theme + "_home_large_font_no_horizontal_overflow", home.ExtentWidth <= home.ViewportWidth + 1);
                Layout(page, theme, 520, 720, 150); Save(page, theme + "-history-narrow", 520, 720);
                var scroll = Descendants<ScrollViewer>(page).First(); Check(theme + "_history_narrow_scrollable", scroll.ExtentHeight > scroll.ViewportHeight);
                Layout(overlayPage, theme, 520, 720, 150); Save(overlayPage, theme + "-overlays-narrow", 520, 720);
                var overlayScroll = Descendants<ScrollViewer>(overlayPage).First();
                Check(theme + "_overlay_narrow_no_horizontal_overflow", overlayScroll.ExtentWidth <= overlayScroll.ViewportWidth + 1);
                Check(theme + "_overlay_setting_changes_allocate_no_windows", overlays.Windows.Count == 0);
            }
            Layout(page, "light", 940, 720);
            FindButton(page, "返回实时日志").RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); page.UpdateState();
            Check("history_return_live_action", returnedLive == 1 && history.DisplayedKey is null);
            FindButton(page, "从列表移除选中记录").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Check("history_remove_keeps_original", history.Records.Count == 0 && File.ReadAllBytes(path).SequenceEqual(original));
            VerifyHistoryInteractions(Check);
            var timelineReport = (EvidenceObject)EvidenceJson.Parse("""
                {"battle":{"duration_ms":10000},"participants":[{"character_key":"chr_0001_test","character_name":"长名称角色"}],
                 "casts":[{"character_key":"chr_0001_test","skill_key":"chr_0001_test_normal_skill","skill_name":"完整战技名称","ts_ms_from_start":1000,"end_ms_from_start":2000},
                   {"character_key":"chr_0001_test","skill_key":"chr_0001_test_combo_skill","ts_ms_from_start":3000,"end_ms_from_start":4000},
                   {"character_key":"chr_0001_test","skill_key":"chr_0001_test_ultimate_skill","ts_ms_from_start":5000}],
                 "timeline_events":[{"event_type":"damage","lane_type":"skill","source_character_key":"chr_0001_test","event_key":"chr_0001_test_ultimate_skill","ts_ms_from_start":7000,"value":100}]}
                """);
            BattlePresentationCheck.Verify(timelineReport, new(temporary.FullName), temporary.FullName,
                Path.ChangeExtension(output, ".timeline.json"), Check);
            File.WriteAllText(output, JsonSerializer.Serialize(new { passed = true, checks, native_windows = 0, boundary = "Actual page controls rendered offscreen; no foreground, keyboard, mouse, capture or hardware services." }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (Exception error) { File.WriteAllText(output, JsonSerializer.Serialize(new { passed = false, checks, error = error.ToString() }, new JsonSerializerOptions { WriteIndented = true })); return 1; }
        finally { if (host is not null) host.Content = null; temporary.Delete(true); }
    }
}
