using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop;

internal static class StandaloneOverlays
{
    internal static int Run(string? root = null)
    {
        try
        {
            SettingsContext context = new(ProductApplication.ResolveRoot(root)); SettingsCodec codec = new(context); SettingsStore settings = new(codec.Load(), codec);
            Application app = new() { ShutdownMode = ShutdownMode.OnMainWindowClose }; return app.Run(new Host(settings));
        }
        catch (Exception error) { MessageBox.Show(error.Message, "独立悬浮窗启动失败"); return 1; }
    }
    private sealed class Host : Window
    {
        private readonly SettingsStore settings;
        private readonly OverlayManager manager;
        private readonly DispatcherTimer timer;
        private OverlaySocketClient? client;
        private Task transportChange = Task.CompletedTask;
        private long revision;
        private HashSet<string> clientStreams = new(StringComparer.Ordinal);
        private readonly TextBlock status = Ui.Text("未连接本机服务");
        private bool closing, finished;
        internal Host(SettingsStore settings)
        {
            this.settings = settings; Title = "Endfield Logs · 独立悬浮窗"; Width = 900; Height = 720;
            manager = new(settings, text => status.Text = text); DockPanel root = new() { Margin = new(12) };
            DockPanel.SetDock(status, Dock.Bottom); root.Children.Add(status); root.Children.Add(new OverlaysPage(settings, manager, text => status.Text = text)); Content = root;
            timer = new DispatcherTimer(TimeSpan.FromMilliseconds(100), DispatcherPriority.Background, (_, _) => Poll(), Dispatcher);
            manager.RequirementsChanged += _ => DemandChanged(); Loaded += (_, _) => { manager.Sync(); DemandChanged(); }; Closing += OnClosing;
        }
        private void DemandChanged()
        {
            if (closing) return;
            var streams = manager.Requirements.ToHashSet(StringComparer.Ordinal); if (streams.SetEquals(clientStreams)) return;
            clientStreams = streams; var request = ++revision; var before = transportChange; transportChange = ChangeClientAsync(before, request, streams);
        }
        private async Task ChangeClientAsync(Task before, long request, HashSet<string> streams)
        {
            await before;
            if (closing || request != revision) return;
            var previous = client; client = null; if (previous is not null) await previous.DisposeAsync();
            if (closing || request != revision) return;
            if (streams.Count == 0) { status.Text = "遮挡浮窗无需数据连接"; return; }
            client = new(settings.Current.Service.WebSocketPort, settings.Current.Service.BrowserToken, subscriptions: streams); client.Start();
        }
        private void Poll()
        {
            if (closing || client is null) return;
            var state = client.Poll(); status.Text = "本机服务：" + state.Status; status.ToolTip = state.Error;
            foreach (var window in manager.Windows.Values) window.Canvas.SetConnected(state.Status == "已连接");
            foreach (var message in state.Messages) manager.Receive(message);
        }
        private async void OnClosing(object? sender, CancelEventArgs args)
        {
            if (finished) return; args.Cancel = true; if (closing) return; closing = true; timer.Stop(); manager.Dispose();
            try { await transportChange; if (client is not null) await client.DisposeAsync(); }
            finally { finished = true; _ = Dispatcher.BeginInvoke(new Action(Close)); }
        }
    }
}
