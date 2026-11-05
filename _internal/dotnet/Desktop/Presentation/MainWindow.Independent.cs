using System.Windows;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class MainWindow
{
    private VisionSettingsWindow? visionSettings;
    internal void ShowVisionSettings()
    {
        if (closing) return;
        if (visionSettings is { } existing) { existing.Activate(); return; }
        try
        {
            visionSettings = new(independent, settings) { Owner = this };
            Ui.ShowDialog(visionSettings);
        }
        catch (Exception error) { Notify("图像识别设置不可用：" + error.Message); }
        finally { visionSettings = null; }
    }
    private void ShowInputSettings()
    {
        if (closing) return;
        try
        {
            InputSettingsWindow dialog = new(settings.Current.InputSettings) { Owner = this };
            if (Ui.ShowDialog(dialog) == true) settings.Update(current => current with { InputSettings = dialog.Value });
        }
        catch (Exception error) { Notify("输入设置不可用：" + error.Message); }
    }
}
