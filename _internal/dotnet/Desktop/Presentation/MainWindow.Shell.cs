using System.Windows;
using EndfieldLogs.Desktop.Windows;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed partial class MainWindow
{
    private ShellIntegration? shell;
    private readonly UpdatePanel updates;
    private readonly List<(WeakReference<Window> Window, WindowState State)> hiddenWindows = [];
    internal ShellIntegration? Shell => shell;
    private void InitializeShell()
    {
        SourceInitialized += (_, _) =>
        {
            shell = new(this, RestoreGui, HideGui, ToggleGui, overlays.ToggleVisible, Notify, () => Track(NewRecordingAsync()));
            shell.Configure(settings.Current.ToggleGuiHotkey, settings.Current.ToggleOverlaysHotkey, settings.Current.ToggleRecordingHotkey);
        };
    }
    private bool Belongs(Window window)
    {
        for (Window? candidate = window; candidate is not null; candidate = candidate.Owner) if (candidate == this) return true;
        return false;
    }
    internal void ToggleGui()
    {
        if (closing) return;
        if (Application.Current.Windows.OfType<Window>().Any(window => Belongs(window) && window.IsVisible && window.WindowState != WindowState.Minimized)) HideGui(); else RestoreGui();
    }
    internal void HideGui()
    {
        if (closing) return;
        foreach (var window in Application.Current.Windows.OfType<Window>().Where(window => window != this && Belongs(window) && window.IsVisible).ToArray())
        { hiddenWindows.Add((new(window), window.WindowState)); window.Hide(); }
        history.ReleaseCache();
        if (shell?.TrayAvailable == true) Hide(); else WindowState = WindowState.Minimized;
    }
    internal void RestoreGui()
    {
        if (closing) return; Show(); WindowState = WindowState.Normal;
        var restore = hiddenWindows.ToArray(); hiddenWindows.Clear();
        foreach (var entry in restore) if (entry.Window.TryGetTarget(out var window) && window.IsLoaded)
        { window.WindowState = entry.State; window.Show(); }
        Activate(); Poll();
    }
}
