using System.IO;
using System.Windows;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Desktop.Verification;

namespace EndfieldLogs.Desktop;

internal static class ProductApplication
{
    internal static string ResolveRoot(string? requested = null)
    {
        if (requested is not null) return Path.GetFullPath(requested);
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "_internal", "data", "resource-manifest.json"))) return directory.FullName;
        // A portable installation always owns its configuration beside the executable.
        return AppContext.BaseDirectory;
    }
    internal static int Run(string? requestedRoot = null, string? startupCheckOutput = null)
    {
        try
        {
            var root = ResolveRoot(requestedRoot);
            using var check = startupCheckOutput is null ? null : new ProductStartupCheck(startupCheckOutput);
            SettingsContext context = new(check?.ProfileRoot ?? root); SettingsCodec codec = new(context);
            check?.PrepareSettings(codec);
            SettingsStore settings = new(codec.Load(), codec);
            check?.ValidateSettings(settings.Current);
            Application app = new() { ShutdownMode = ShutdownMode.OnMainWindowClose };
            MainWindow window = new(settings, new ResourceFiles(Path.Combine(root, "_internal")));
            check?.Attach(window, settings, codec);
            var exit = app.Run(window);
            return check?.Complete(window, root) ?? exit;
        }
        catch (Exception error)
        {
            using var failureLog = new RuntimeLog(Path.Combine(ResolveRoot(requestedRoot), ".dev-gui", "logs", "runtime.log"));
            failureLog.Write("程序启动失败", error);
            if (startupCheckOutput is not null) ProductStartupCheck.WriteFailure(startupCheckOutput, error);
            else MessageBox.Show(error.Message, "启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
            return 1;
        }
    }
}
