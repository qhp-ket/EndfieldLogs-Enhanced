using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Bounded nonactivating startup through ProductApplication, including its real service composition.</summary>
internal sealed class ProductStartupCheck : IDisposable
{
    private readonly string output;
    private readonly Dictionary<string, object?> result = [];
    private readonly DirectoryInfo temporary = Directory.CreateTempSubdirectory("endfield-startup-check-");
    private readonly Stopwatch watch = Stopwatch.StartNew();
    private readonly DispatcherTimer deadline = new() { Interval = TimeSpan.FromSeconds(20) };
    private MainWindow? window;
    internal string ProfileRoot => temporary.FullName;

    internal ProductStartupCheck(string output)
    {
        this.output = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(this.output)!);
    }

    internal void PrepareSettings(SettingsCodec codec)
    {
        // Do not read the user's configuration, acquire hotkeys, query releases or start capture/input.
        var initial = codec.Decode(new(new Dictionary<string, EvidenceValue>())) with
        {
            CheckUpdatesOnStart = false, StartCaptureOnLaunch = false, StartInputRecordingOnLaunch = false,
            ToggleGuiHotkey = "verification-disabled", ToggleOverlaysHotkey = "verification-disabled",
            ToggleRecordingHotkey = "verification-disabled",
            Overlays = new[] { "damage", "combo_skill", "uid_mask" }.Select(type => new OverlaySettings
                { SourceValue = type, Enabled = false, Hidden = true, ClickThrough = true }).ToArray(),
            ThemeMode = "dark", FontPercent = 100,
        };
        codec.Save(initial);
    }

    internal void ValidateSettings(ApplicationSettings settings)
    {
        if (settings.StartCaptureOnLaunch || settings.StartInputRecordingOnLaunch || settings.CheckUpdatesOnStart
            || settings.Overlays.Any(entry => entry.Enabled) || settings.ToggleGuiHotkey != "verification-disabled"
            || settings.ToggleOverlaysHotkey != "verification-disabled"
            || settings.ToggleRecordingHotkey != "verification-disabled")
            throw new InvalidOperationException("启动检查的隔离配置不能开启采集、输入、快捷键或浮窗");
    }

    internal void Attach(MainWindow main, SettingsStore settings, SettingsCodec codec)
    {
        window = main;
        BenchmarkWindow.Prepare(main);
        deadline.Tick += (_, _) =>
        {
            result["error"] = "产品启动或退出超过 20 秒";
            Application.Current.Shutdown(1);
        };
        deadline.Start();
        main.Loaded += async (_, _) =>
        {
            try
            {
                await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                BenchmarkWindow.Check();
                Check("real_main_window_loaded", main.IsLoaded && main.IsVisible && main.ActualWidth > 700);
                Check("shell_created_without_hotkey_bindings", main.Shell is { HotkeyCount: 0 });
                Check("jsonl_is_default", settings.Current.Service.TraceFormat == "jsonl");
                Check("initial_dark_theme", settings.Current.ThemeMode == "dark" && main.Background is SolidColorBrush brush && brush.Color.R < 100);
                foreach (var page in Enum.GetValues<MainPage>())
                {
                    main.Navigation.Select(page);
                    await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                    BenchmarkWindow.Check();
                    Check("navigation_" + page, main.Navigation.SelectedPage == page && main.Navigation.SelectedContent.IsVisible);
                }
                main.Navigation.SetExpanded(false);
                Check("navigation_collapses", !main.Navigation.IsExpanded);
                main.Navigation.SetExpanded(true);
                settings.Update(current => current with { FontPercent = 150, ThemeMode = "light" }); main.ApplySettings();
                await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                Check("light_large_font", main.FontSize > 15 && main.Background is SolidColorBrush light && light.Color.R > 150);
                settings.Update(current => current with { FontPercent = 100, ThemeMode = "dark" }); main.ApplySettings();
                var restored = codec.Load();
                Check("configuration_saved_and_reloaded", restored.ThemeMode == "dark" && restored.FontPercent == 100
                    && restored.Service.TraceFormat == "jsonl" && !restored.StartCaptureOnLaunch && !restored.StartInputRecordingOnLaunch);
                Check("no_overlay_or_recording_autostart", main.Overlays.Windows.Count == 0 && !settings.Current.StartCaptureOnLaunch && !settings.Current.StartInputRecordingOnLaunch);
                result["ready_ms"] = watch.Elapsed.TotalMilliseconds;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally { main.Close(); }
        };
    }

    private void Check(string name, bool passed)
    {
        result[name] = passed;
        if (!passed) throw new InvalidOperationException(name);
    }

    internal int Complete(MainWindow main, string root)
    {
        deadline.Stop(); BenchmarkWindow.Check();
        Check("real_services_disposed_on_close", main.ServicesDisposed && !main.IsVisible);
        result["passed"] = !result.ContainsKey("error");
        result["root"] = root;
        result["process_path"] = Environment.ProcessPath;
        result["runtime_path"] = typeof(object).Assembly.Location;
        result["wpf_path"] = typeof(Application).Assembly.Location;
        result["desktop_path"] = typeof(MainWindow).Assembly.Location;
        result["boundary"] = "Root apphost/common ProductApplication initialization, actual MainWindow and real inactive services, isolated configuration; nonactivating/input-transparent window. No capture, input worker, global hotkeys, release query, game or physical input.";
        result["elapsed_ms"] = watch.Elapsed.TotalMilliseconds;
        File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
        return (bool)result["passed"]! ? 0 : 1;
    }

    internal static void WriteFailure(string output, Exception error)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(new { passed = false, error = error.ToString() }));
    }

    public void Dispose()
    {
        deadline.Stop();
        // The normal Closing path disposes the services. Keep the profile if an exceptional shutdown interrupted it.
        if (window is null || window.ServicesDisposed) temporary.Delete(true);
    }
}
