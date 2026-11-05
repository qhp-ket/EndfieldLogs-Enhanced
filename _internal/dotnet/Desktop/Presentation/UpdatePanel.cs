using System.Diagnostics;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Updates;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class UpdatePanel : StackPanel, IDisposable
{
    private readonly SettingsStore settings;
    private readonly Action<string> notify;
    private readonly CancellationTokenSource lifetime = new();
    private readonly Func<string, string, CancellationToken, Task<ReleaseUpdate?>> query;
    private readonly TextBlock status = Ui.Text("");
    private readonly Button check, download, ignore;
    private ReleaseUpdate? release;
    private bool disposed;
    internal string Status => status.Text;
    internal bool Busy => !check.IsEnabled;
    internal ReleaseUpdate? Release => release;
    internal static string Version => typeof(ProductApplication).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0] ?? "0.0.0";
    internal UpdatePanel(SettingsStore settings, Action<string> notify, Func<string, string, CancellationToken, Task<ReleaseUpdate?>>? query = null)
    {
        this.settings = settings; this.notify = notify; this.query = query ?? ((current, ignored, token) => ReleaseUpdates.CheckAsync(current, ignored, token));
        Children.Add(Ui.Text("关于", 18)); Children.Add(Ui.Text("Endfield Logs - Enhanced · " + Version)); Children.Add(status);
        WrapPanel actions = new(); Children.Add(actions);
        check = Ui.Button("检查更新", () => _ = CheckAsync(true)); download = Ui.Button("前往下载", OpenRelease); ignore = Ui.Button("忽略此版本", Ignore);
        actions.Children.Add(check); actions.Children.Add(download); actions.Children.Add(ignore); SetRelease(null);
        status.Text = "尚未检查更新";
    }
    internal async Task ScheduleAsync()
    {
        try { await Task.Delay(1200, lifetime.Token); if (settings.Current.CheckUpdatesOnStart) await CheckAsync(false); }
        catch (OperationCanceledException) when (disposed) { }
    }
    internal async Task CheckAsync(bool manual)
    {
        if (disposed || Busy) return; check.IsEnabled = false; if (manual) status.Text = "正在检查更新…";
        try
        {
            var result = await query(Version, settings.Current.IgnoredUpdateVersion, lifetime.Token);
            if (disposed) return;
            if (result?.Version == settings.Current.IgnoredUpdateVersion.TrimStart('v')) result = null;
            SetRelease(result); if (result is not null) notify(status.Text);
        }
        catch (OperationCanceledException) when (disposed) { }
        catch (Exception error)
        {
            if (!disposed && manual) status.Text = "检查失败：" + error.Message.Split('\n')[0][..Math.Min(160, error.Message.Split('\n')[0].Length)];
        }
        finally { if (!disposed) check.IsEnabled = true; }
    }
    private void SetRelease(ReleaseUpdate? value)
    {
        release = value; download.Visibility = ignore.Visibility = value is null ? Visibility.Collapsed : Visibility.Visible;
        status.Text = value is null ? "未检测到新版" : $"发现新版 {value.Version} · 发布日期 {value.PublishedAt.LocalDateTime:yyyy-MM-dd}";
    }
    private void OpenRelease()
    {
        if (release is null) return;
        try { Process.Start(new ProcessStartInfo(release.Url.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception error) { notify("打开发行页失败：" + error.Message); }
    }
    internal void Ignore()
    {
        if (release is null || disposed) return;
        try { settings.Update(current => current with { IgnoredUpdateVersion = release.Version }); SetRelease(null); }
        catch (Exception error) { notify("保存忽略版本失败：" + error.Message); }
    }
    public void Dispose() { if (disposed) return; disposed = true; lifetime.Cancel(); lifetime.Dispose(); }
}
