using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class BattleAnalysisWindow
{
    internal void ApplyAppearance()
    {
        var current = settings.Current; var dark = Ui.ApplyAppearance(this, current.ThemeMode, current.FontPercent);
        timeline.ApplyPresentation(avatars, current.FontPercent, current.ShowCharacterAvatars, current.CharacterAvatarPercent, dark);
        plot.ApplyAppearance(current.FontPercent / 100d, dark);
        SkillsPage.ApplyPresentation(avatars, current.ShowCharacterAvatars, current.CharacterAvatarPercent, current.FontPercent);
    }
    private void DisplayOptions()
    {
        Window dialog = new() { Title = "显示设置", Owner = this, Width = 340, SizeToContent = SizeToContent.Height, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        StackPanel body = new() { Margin = new(18) }; dialog.Content = body;
        CheckBox portraits = new() { Content = "显示角色头像", IsChecked = settings.Current.ShowCharacterAvatars, Margin = new(0, 4, 0, 10) }; body.Children.Add(portraits);
        body.Children.Add(Ui.Button("角色统计与快照质量", () => Ui.ShowDialog(new BattleSummaryWindow(snapshot, settings) { Owner = dialog })));
        body.Children.Add(Ui.Text("头像比例")); Slider percent = new() { Minimum = 50, Maximum = 300, TickFrequency = 10, IsSnapToTickEnabled = true, Value = settings.Current.CharacterAvatarPercent, Margin = new(0, 4, 0, 12) }; body.Children.Add(percent);
        var save = Ui.Button("保存", () => dialog.DialogResult = true); save.IsDefault = true; body.Children.Add(save);
        CheckBox fallback = new() { Content = "固定起止配置回退", IsChecked = timeline.ShowFrameReference, Margin = new(0, 4, 0, 10),
            ToolTip = "缺少完整起止时，以首个实际命中点 + AKEData 配置时长显示虚线参考块；实线保留日志区间。" }; body.Children.Insert(body.Children.Count - 1, fallback);
        if (Ui.ShowDialog(dialog) != true) return;
        settings.Update(current => current with { ShowCharacterAvatars = portraits.IsChecked == true, CharacterAvatarPercent = (int)percent.Value }); ApplyAppearance();
        timeline.SetFrameReference(fallback.IsChecked == true); fallbackStatus.Visibility = timeline.ShowFrameReference ? Visibility.Visible : Visibility.Collapsed;
    }
}
