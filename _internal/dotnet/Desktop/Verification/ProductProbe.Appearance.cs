using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    private static async Task VerifyAppearance(Application app, MainWindow main, BattleAnalysisWindow analysis,
        SettingsStore settings, string output, Action<string, bool> check)
    {
        var previous = settings.Current;
        bool Contrast(Brush? foreground, Brush? background, bool dark, Brush? backdrop = null)
        {
            if (foreground is not SolidColorBrush ink || background is not SolidColorBrush fill) return false;
            var alpha = fill.Color.A / 255d * fill.Opacity;
            if (alpha < 1 && backdrop is not SolidColorBrush { Color.A: 255 }) return false;
            var red = fill.Color.R * alpha + (backdrop is SolidColorBrush under ? under.Color.R : 0) * (1 - alpha);
            return dark ? red < 100 && ink.Color.R > 180 : red > 180 && ink.Color.R < 100;
        }
        void Dialog(string key, Action open, Func<Window, bool> select, bool dark)
        {
            Exception? failure = null; bool visited = false;
            DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(20) };
            timer.Tick += (_, _) =>
            {
                var dialog = app.Windows.OfType<Window>().FirstOrDefault(candidate => candidate.IsVisible && select(candidate));
                if (dialog is null) return; timer.Stop(); visited = true;
                try
                {
#pragma warning disable WPF0001
                    check(key + "_theme_font", dialog.ThemeMode == analysis.ThemeMode && dialog.FontSize == analysis.FontSize
                        && Contrast(dialog.Foreground, dialog.Background, dark));
#pragma warning restore WPF0001
                    dialog.UpdateLayout();
                    Screenshot(dialog, Path.ChangeExtension(output, "." + key + ".png"));
                    var entry = Descendants<TextBox>(dialog).FirstOrDefault();
                    if (entry is not null && entry.IsEnabled) check(key + "_entry_contrast", Contrast(entry.Foreground, entry.Background, dark, dialog.Background));
                    var grid = Descendants<DataGrid>(dialog).FirstOrDefault();
                    if (grid is not null)
                    {
                        var cell = Descendants<DataGridCell>(grid).First();
                        check(key + "_table_text", cell.Foreground is SolidColorBrush ink && (dark ? ink.Color.R > 180 : ink.Color.R < 100));
                    }
                    if (dialog is BattleSummaryWindow summary)
                    {
                        check(key + "_core_statistics", summary.Participants.Columns.Count == 6
                            && summary.Participants.Items.OfType<ParticipantRow>().Single() is { Damage: 200, RDamage: 200 });
                        if (!dark) check(key + "_restores_column_width", summary.Participants.Columns[1].Width.Value == 173);
                        summary.Participants.Columns[1].Width = 173; summary.UpdateLayout();
                        check(key + "_raw_quality", EvidenceJson.PythonEquals(EvidenceJson.Parse(summary.Quality.Text), main.Summary.Snapshot!.Get("snapshot_quality")));
                        Descendants<TabControl>(summary).Single().SelectedIndex = 1; summary.UpdateLayout();
                        check(key + "_quality_contrast", Contrast(summary.Quality.Foreground, summary.Quality.Background, dark, summary.Background));
                        Screenshot(summary, Path.ChangeExtension(output, "." + key + "-quality.png"));
                    }
                    if (dialog.Title == "显示设置")
                    {
                        var button = Descendants<Button>(dialog).Single(candidate => Equals(candidate.Content, "角色统计与快照质量"));
                        Dialog((dark ? "dark" : "light") + "-summary", () => button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)), candidate => candidate is BattleSummaryWindow, dark);
                        check(key + "_summary_column_width_saved", new SettingsCodec(settings.Context).Load().BattleTableWidths.Get("participants") is EvidenceArray widths
                            && EvidenceView.Number(widths.Items[1]) == 173);
                    }
                }
                catch (Exception error) { failure = error; }
                finally { dialog.DialogResult = false; }
            };
            timer.Start(); try { open(); } finally { timer.Stop(); }
            if (failure is not null) throw failure;
            check(key + "_opened", visited);
        }
        try
        {
            foreach (var mode in new[] { "dark", "light" })
            {
                var dark = mode == "dark";
                settings.Update(current => current with { ThemeMode = mode, FontPercent = 125 });
                main.ApplySettings(); analysis.UpdateLayout(); main.UpdateLayout();
                await analysis.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle);
                check(mode + "_main_analysis_contrast", Contrast(main.Foreground, main.Background, dark)
                    && Contrast(analysis.Foreground, analysis.Background, dark) && analysis.FontSize == 16.25);
                check(mode + "_analysis_quality_tooltip", analysis.SummaryHeader.ToolTip is string hint
                    && hint.Contains("rDPS：暂定", StringComparison.Ordinal) && hint.Contains("计时：暂定", StringComparison.Ordinal));
                Screenshot(main, Path.ChangeExtension(output, "." + mode + "-main.png"));
                analysis.Timeline.SelectMarks(analysis.Timeline.Marks.Where(mark => mark.Skill is not null).ToArray());
                analysis.SetDetails(true); analysis.DetailsPages.SelectedIndex = 2; analysis.UpdateLayout();
                Screenshot(analysis, Path.ChangeExtension(output, "." + mode + "-details.png"));
                var tabs = Descendants<TabControl>(analysis).First();
                tabs.SelectedIndex = 1; analysis.UpdateLayout();
                var skillCell = Descendants<DataGridCell>(analysis.SkillsPage.Table).First();
                check(mode + "_skills_table_text", skillCell.Foreground is SolidColorBrush cellInk && (dark ? cellInk.Color.R > 180 : cellInk.Color.R < 100));
                Screenshot(analysis, Path.ChangeExtension(output, "." + mode + "-skills.png"));
                tabs.SelectedIndex = 2; analysis.UpdateLayout(); Screenshot(analysis, Path.ChangeExtension(output, "." + mode + "-enemies.png")); tabs.SelectedIndex = 0; analysis.UpdateLayout();
                Dialog(mode + "-display", () => Descendants<Button>(analysis).Single(button => Equals(button.Content, "显示设置")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)),
                    dialog => dialog.Title == "显示设置", dark);
                Dialog(mode + "-lanes", () => analysis.EditRoleLanes("chr_0001_test"), dialog => dialog is RoleLanesWindow, dark);
                Dialog(mode + "-input", () => Ui.ShowDialog(new InputSettingsWindow(analysis.InputPanel.State.Settings) { Owner = analysis }), dialog => dialog is InputSettingsWindow, dark);
                Dialog(mode + "-alignment", () => Ui.ShowDialog(new InputAlignmentWindow(main.Summary.Snapshot!, analysis.InputPanel.State) { Owner = analysis }), dialog => dialog is InputAlignmentWindow, dark);
                Dialog(mode + "-rename", () => Ui.Ask(analysis, "主题检查重命名", "名称", "测试战斗"), dialog => dialog.Title == "主题检查重命名", dark);
                check(mode + "_persisted_theme", new SettingsCodec(settings.Context).Load().ThemeMode == mode);
            }
        }
        finally
        {
            settings.Update(current => current with { ThemeMode = previous.ThemeMode, FontPercent = previous.FontPercent });
            main.ApplySettings(); analysis.SetDetails(false);
            await main.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ContextIdle); main.UpdateLayout(); analysis.UpdateLayout();
        }
    }
}
