using System.Runtime.InteropServices;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Desktop.Windows;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Updates;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    [DllImport("user32.dll")] private static extern nint SendMessage(nint window, uint message, nint wParam, nint lParam);
    private static async Task VerifyShell(MainWindow window, BattleAnalysisWindow analysis, SettingsStore settings, Recorder recorder, Action<string, bool> check)
    {
        var shell = window.Shell ?? throw new InvalidOperationException("Missing shell adapter"); check("shell_adapter_initialized", window.Shell is not null);
        check("portable_hotkeys_parse_supported_keys", ShellIntegration.Parse("Ctrl+Shift+O") == (6u, 0x4Fu) && ShellIntegration.Parse("Meta+F24") == (8u, 0x87u)
            && ShellIntegration.Parse("Ctrl+-") == (2u, 0xBDu) && ShellIntegration.Parse("Ctrl+Shift") is null && ShellIntegration.Parse("bad+O") is null);
        shell.Configure("Ctrl+Alt+Shift+F23", "Ctrl+Alt+Shift+F24");
        check("native_hotkeys_registered_on_owned_window", shell.HotkeyCount == 2);
        shell.Configure("bad+O", "Ctrl+Alt+Shift+F24");
        check("invalid_hotkey_preserves_working_registration", shell.HotkeyCount == 2);
        SendMessage(new WindowInteropHelper(window).Handle, 0x0312, 0xB101, 0);
        check("native_hotkey_hides_owned_analysis_and_keeps_services", !analysis.IsVisible && (!window.IsVisible || window.WindowState == WindowState.Minimized) && recorder.Running && !window.ServicesDisposed);
        SendMessage(new WindowInteropHelper(window).Handle, 0x0312, 0xB101, 0);
        check("native_hotkey_restores_owned_analysis", window.IsVisible && window.WindowState == WindowState.Normal && analysis.IsVisible);
        window.HideGui(); SendMessage(new WindowInteropHelper(window).Handle, 0x8000 + 63, 1, 0x0202);
        check("tray_callback_restores_owned_gui", window.IsVisible && window.WindowState == WindowState.Normal && analysis.IsVisible);
        shell.Configure(settings.Current.ToggleGuiHotkey, settings.Current.ToggleOverlaysHotkey);
        var oldIgnored = settings.Current.IgnoredUpdateVersion;
        TaskCompletionSource<ReleaseUpdate?> query = new(TaskCreationOptions.RunContinuationsAsynchronously);
        using UpdatePanel panel = new(settings, _ => { }, (_, _, _) => query.Task);
        var pending = panel.CheckAsync(true);
        check("manual_update_disables_duplicate_requests", panel.Busy && panel.Status == "正在检查更新…");
        var release = new ReleaseUpdate("999.0.0", DateTimeOffset.Parse("2026-10-28T10:20:30Z", System.Globalization.CultureInfo.InvariantCulture), new("https://github.com/qhp-ket/EndfieldLogs-Enhanced/releases/tag/v999.0.0"));
        query.SetResult(release); await pending;
        check("update_result_reaches_native_about_panel", !panel.Busy && panel.Release?.Version == "999.0.0" && panel.Status.Contains("2026-10-28", StringComparison.Ordinal)
            && panel.Children.OfType<WrapPanel>().Single().Children.OfType<Button>().Count(button => button.Visibility == Visibility.Visible) == 3);
        panel.Ignore(); check("ignore_update_persists_existing_config_field", settings.Current.IgnoredUpdateVersion == "999.0.0" && panel.Release is null);
        settings.Update(current => current with { IgnoredUpdateVersion = oldIgnored });
        TaskCompletionSource<ReleaseUpdate?> late = new(TaskCreationOptions.RunContinuationsAsynchronously);
        UpdatePanel closed = new(settings, _ => throw new InvalidOperationException("Late update notification"), (_, _, _) => late.Task);
        var lateRequest = closed.CheckAsync(true); closed.Dispose(); late.SetResult(release); await lateRequest;
        check("closed_update_panel_rejects_late_response", closed.Release is null);
        using UpdatePanel failed = new(settings, _ => { }, (_, _, _) => Task.FromException<ReleaseUpdate?>(new HttpRequestException("测试网络错误")));
        await failed.CheckAsync(true); check("manual_update_failure_is_recoverable", !failed.Busy && failed.Status.Contains("测试网络错误", StringComparison.Ordinal));
    }
}
