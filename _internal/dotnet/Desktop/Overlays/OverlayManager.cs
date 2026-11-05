using System.IO;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Window instances, minimal subscriptions and live/history presentation share one application owner.</summary>
internal sealed class OverlayManager : IDisposable
{
    private readonly SettingsStore settings;
    private readonly AvatarCache avatars;
    private readonly Action<string> diagnostic;
    private readonly Dictionary<string, OverlayWindow> windows = new(StringComparer.Ordinal);
    private readonly Dictionary<string, NativeSkin> skins = new(StringComparer.Ordinal);
    private sealed record SkinSource(string Type, string Value, long Modified, long Length);
    private readonly Dictionary<string, SkinSource> sources = new(StringComparer.Ordinal);
    private readonly OverlayFeed feed = new();
    private OverlayGraphicsDevice? graphics;
    private bool closed;
    private HashSet<string> requirements = new(StringComparer.Ordinal);
    internal IReadOnlyDictionary<string, OverlayWindow> Windows => windows;
    internal OverlayFeed Feed => feed;
    internal IReadOnlySet<string> Requirements => requirements;
    internal event Action<IReadOnlySet<string>>? RequirementsChanged;
    internal event Action? EntriesChanged;
    internal OverlayManager(SettingsStore settings, Action<string> diagnostic)
    {
        this.settings = settings; this.diagnostic = diagnostic; avatars = new(settings.Context.ApplicationRoot);
        feed.Changed += (_, message) => { foreach (var window in windows.Values) window.Canvas.Receive(message); };
    }
    internal void Sync()
    {
        if (closed) return;
        var ids = settings.Current.Overlays.Select(entry => entry.Id).ToHashSet(StringComparer.Ordinal);
        foreach (var id in windows.Keys.Where(id => !ids.Contains(id) || !settings.Current.Overlays.Any(entry => entry.Id == id && entry.Enabled)).ToArray()) Remove(id);
        HashSet<string> next = new(StringComparer.Ordinal);
        foreach (var entry in settings.Current.Overlays)
        {
            if (!entry.Enabled) continue;
            try
            {
                var file = entry.SourceType == "file" ? new FileInfo(Path.GetFullPath(entry.SourceValue, settings.Context.WorkingDirectory)) : null;
                var source = new SkinSource(entry.SourceType, entry.SourceValue, file?.LastWriteTimeUtc.Ticks ?? 0, file?.Length ?? 0);
                var reload = sources.GetValueOrDefault(entry.Id) != source;
                if (!skins.TryGetValue(entry.Id, out var skin) || reload)
                { skin = NativeSkins.For(entry, settings.Context); skins[entry.Id] = skin; sources[entry.Id] = source; }
                if (!windows.TryGetValue(entry.Id, out var window))
                {
                    graphics ??= new();
                    window = new(entry, skin, avatars, SaveFromWindow, graphics); windows[entry.Id] = window;
                    window.Canvas.Receive(RecordingMessage(feed.Recording));
                    if (feed.Damage is not null) window.Canvas.Receive(feed.Damage);
                    if (feed.Combo is not null) window.Canvas.Receive(feed.Combo);
                    window.Show();
                }
                else
                {
                    window.Apply(entry, skin);
                    if (reload)
                    {
                        if (feed.Damage is not null) window.Canvas.Receive(feed.Damage);
                        if (feed.Combo is not null) window.Canvas.Receive(feed.Combo);
                    }
                }
                window.ApplyDesktop(!entry.Hidden);
                next.UnionWith(skin.Subscriptions);
            }
            catch (Exception error) { Remove(entry.Id); diagnostic("悬浮窗「" + entry.Name + "」：" + error.Message); }
        }
        if (windows.Count == 0) { graphics?.Dispose(); graphics = null; }
        if (!requirements.SetEquals(next)) { requirements = next; RequirementsChanged?.Invoke(requirements); }
    }
    private void Remove(string id)
    {
        if (windows.Remove(id, out var window)) window.DisposeWindow(); skins.Remove(id); sources.Remove(id);
    }
    private void SaveFromWindow(OverlaySettings entry)
    {
        Update(entry.Id, _ => entry, sync: false); EntriesChanged?.Invoke();
    }
    internal void Update(string id, Func<OverlaySettings, OverlaySettings> update, bool sync = true)
    {
        settings.Update(current => current with { Overlays = current.Overlays.Select(entry => entry.Id == id ? update(entry) : entry).ToArray() });
        if (sync) Sync();
    }
    internal void ToggleVisible()
    {
        var shown = settings.Current.Overlays.Where(entry => entry.Enabled && !entry.Hidden).Select(entry => entry.Id).ToHashSet(StringComparer.Ordinal);
        settings.Update(current => shown.Count > 0
            ? current with { OverlayRestoreIds = current.Overlays.Where(entry => shown.Contains(entry.Id)).Select(entry => entry.Id).ToArray(),
                Overlays = current.Overlays.Select(entry => shown.Contains(entry.Id) ? entry with { Hidden = true } : entry).ToArray() }
            : current with { Overlays = current.Overlays.Select(entry => entry.Enabled && (current.OverlayRestoreIds.Count == 0 || current.OverlayRestoreIds.Contains(entry.Id)) ? entry with { Hidden = false } : entry).ToArray(), OverlayRestoreIds = [] });
        Sync(); EntriesChanged?.Invoke();
    }
    internal void Receive(EvidenceObject message) { if (!closed) feed.Receive(message); }
    private static EvidenceObject RecordingMessage(bool active) => new(new Dictionary<string, EvidenceValue>
        { ["type"] = new EvidenceText("recording_state"), ["recording"] = new EvidenceBoolean(active) });
    internal void SetRecording(bool active) { if (!closed) feed.Receive(RecordingMessage(active)); }
    internal void ClearLive() { if (!closed) feed.ClearLive(); }
    internal void ShowHistory(EvidenceObject report, string label)
    {
        if (closed) return;
        // Damage rendering consumes the same compact fields as live summaries. Keep
        // full hit/timeline/raw evidence owned by the analysis page, outside the feed.
        var fields = new Dictionary<string, EvidenceValue>(StringComparer.Ordinal);
        foreach (var key in new[] { "battle", "participants", "quality_summary", "snapshot_quality" })
            if (report.Fields.TryGetValue(key, out var value)) fields[key] = value;
        feed.ShowHistory(new(fields), label);
    }
    internal void ReturnLive() { if (!closed) feed.ReturnLive(); }
    public void Dispose()
    {
        if (closed) return; closed = true;
        foreach (var window in windows.Values) window.DisposeWindow(); windows.Clear(); skins.Clear(); sources.Clear();
        graphics?.Dispose(); graphics = null;
        if (requirements.Count > 0) { requirements.Clear(); RequirementsChanged?.Invoke(requirements); }
    }
}
