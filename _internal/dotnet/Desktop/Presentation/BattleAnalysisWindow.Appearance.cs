using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleAnalysisWindow
{
    internal void ApplyAppearance()
    {
        var current = settings.Current; var dark = Ui.ApplyAppearance(this, current.ThemeMode, current.BattleFontPercent);
        timeline.ApplyPresentation(avatars, current.BattleFontPercent, current.ShowCharacterAvatars, current.CharacterAvatarPercent, dark);
        plot.ApplyAppearance(current.BattleFontPercent / 100d, dark);
        SkillsPage.ApplyPresentation(avatars, current.ShowCharacterAvatars, current.CharacterAvatarPercent, current.BattleFontPercent);
    }
    private void DisplayOptions()
    {
        Window dialog = new() { Title = "显示设置", Owner = this, Width = 340, SizeToContent = SizeToContent.Height, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        StackPanel body = new() { Margin = new(18) }; dialog.Content = body;
        var fontLabel = Ui.Text($"分析字号：{settings.Current.BattleFontPercent}%"); body.Children.Add(fontLabel);
        Slider font = new() { Minimum = 80, Maximum = 180, TickFrequency = 5, IsSnapToTickEnabled = true, Value = settings.Current.BattleFontPercent, Margin = new(0, 4, 0, 12) };
        font.ValueChanged += (_, _) => fontLabel.Text = $"分析字号：{font.Value:0}%"; body.Children.Add(font);
        CheckBox portraits = new() { Content = "显示角色头像", IsChecked = settings.Current.ShowCharacterAvatars, Margin = new(0, 4, 0, 10) }; body.Children.Add(portraits);
        body.Children.Add(Ui.Button("角色统计与快照质量", () => Ui.ShowDialog(new BattleSummaryWindow(snapshot, settings) { Owner = dialog })));
        body.Children.Add(Ui.Text("头像比例")); Slider percent = new() { Minimum = 50, Maximum = 300, TickFrequency = 10, IsSnapToTickEnabled = true, Value = settings.Current.CharacterAvatarPercent, Margin = new(0, 4, 0, 12) }; body.Children.Add(percent);
        var save = Ui.Button("保存", () => dialog.DialogResult = true); save.IsDefault = true; body.Children.Add(save);
        CheckBox fallback = new() { Content = "固定起止配置回退", IsChecked = timeline.ShowFrameReference, Margin = new(0, 4, 0, 10),
            ToolTip = "缺少完整起止时，以首个实际命中点 + AKEData 配置时长显示虚线参考块；实线保留日志区间。" }; body.Children.Insert(body.Children.Count - 1, fallback);
        if (Ui.ShowDialog(dialog) != true) return;
        settings.Update(current => current with { ShowCharacterAvatars = portraits.IsChecked == true, CharacterAvatarPercent = (int)percent.Value, BattleFontPercent = (int)font.Value }); ApplyAppearance();
        timeline.SetFrameReference(fallback.IsChecked == true); fallbackStatus.Visibility = timeline.ShowFrameReference ? Visibility.Visible : Visibility.Collapsed;
    }
}
