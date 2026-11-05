using System.Collections.ObjectModel;
using System.Security.Cryptography;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Realtime;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceRecording
{
    public static TraceHeader CreateHeader(ResourceFiles resources, DateTimeOffset? now = null, TimeZoneInfo? timeZone = null)
    {
        var zone = timeZone ?? TimeZoneInfo.Local;
        var stamp = TimeZoneInfo.ConvertTime(now ?? DateTimeOffset.Now, zone);
        Dictionary<string, string> hashes = new(StringComparer.Ordinal);
        foreach (var name in new[] { "resource-manifest.json", "runtime-data.zip" })
        {
            var path = resources.PathFor("data/" + name);
            if (!File.Exists(path)) continue;
            using var stream = File.OpenRead(path);
            hashes[name] = Convert.ToHexStringLower(SHA256.HashData(stream));
        }
        return new(Guid.NewGuid().ToString("N"), 1, null, "csharp",
            typeof(TraceRecording).Assembly.GetName().Version?.ToString(3) ?? "unknown", zone.Id,
            (int)stamp.Offset.TotalMinutes, hashes);
    }

    private readonly Action<IReadOnlyList<TraceEvent>>? eventSink;
    private readonly List<TraceEvent> pendingEvents = [];
    private readonly string? eventDirectory;
    private TraceJsonlWriter? eventWriter;
    private TraceHeader? currentHeader;
    private bool failed;
    public TraceHeader? CurrentHeader { get { lock (gate) return currentHeader; } }
    public long EventsWritten { get; private set; }

    // Explicit until recording, linked history and export have all passed the migration gate.
    public static TraceRecording CreateStructured(LiveBattleSession live, TraceHeader header, string? logDirectory = null,
        SkillResourceCatalog? identities = null, DateTime? archiveTime = null, Action? onChanged = null) =>
        CreateStructured(live.FeedEvents, header, logDirectory, identities, archiveTime, onChanged);

    public static TraceRecording CreateStructured(Action<IReadOnlyList<TraceEvent>> liveSink, TraceHeader header,
        string? logDirectory = null, SkillResourceCatalog? identities = null, DateTime? archiveTime = null,
        Action? onChanged = null) => new(liveSink, header, logDirectory, identities, archiveTime, onChanged);

    private TraceRecording(Action<IReadOnlyList<TraceEvent>> liveSink, TraceHeader header, string? logDirectory,
        SkillResourceCatalog? identities, DateTime? archiveTime, Action? onChanged)
    {
        if (header.Volume != 1 || header.PreviousVolume is not null)
            throw new ArgumentException("A new recording must start at volume 1", nameof(header));
        header = header with { Resources = new ReadOnlyDictionary<string, string>(
            header.Resources.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal)) };
        _ = TraceJsonl.Serialize(header);
        eventSink = liveSink; this.onChanged = onChanged; currentHeader = header;
        catalog = identities;
        eventDirectory = logDirectory is null ? null : Path.GetFullPath(logDirectory);
        bridge = new(_ => throw new InvalidOperationException("Structured recording emitted legacy text"),
            identities, eventSink: pendingEvents.Add);
        if (eventDirectory is not null)
            (filePath, eventWriter) = OpenVolume(header, archiveTime ?? DateTime.Now);
    }

    private (string Path, TraceJsonlWriter Writer) OpenVolume(TraceHeader header, DateTime time)
    {
        // All volumes stay beside the first one, including a manual split after midnight.
        var reserved = ReserveFile(eventDirectory!, time, ".jsonl", filePath is null ? null : Path.GetDirectoryName(filePath));
        TraceJsonlWriter? next = null;
        try
        {
            next = new(reserved.Stream, header); next.Flush();
            return (reserved.Path, next);
        }
        catch
        {
            try { next?.Dispose(); }
            finally { reserved.Stream.Dispose(); }
            throw;
        }
    }

    /// <summary>Continue this recording between complete business calls, without a capture/analysis reset.</summary>
    public string RotateVolume(DateTime? archiveTime = null)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (failed) throw new InvalidOperationException("The recording failed and cannot continue");
            if (currentHeader is null || eventDirectory is null || filePath is null)
                throw new InvalidOperationException("Continuous volumes require a structured file recording");
            var nextHeader = currentHeader with { Volume = checked(currentHeader.Volume + 1),
                PreviousVolume = new(currentHeader.Volume, Path.GetFileName(filePath)) };
            eventWriter!.Flush();
            var next = OpenVolume(nextHeader, archiveTime ?? DateTime.Now);
            var previous = eventWriter;
            filePath = next.Path; eventWriter = next.Writer; currentHeader = nextHeader;
            previous.Dispose(); onChanged?.Invoke(); return next.Path;
        }
    }

    private void Execute(Action produce)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (failed) throw new InvalidOperationException("The recording failed and cannot continue");
            try { produce(); CommitEvents(); }
            catch
            {
                if (eventSink is not null) { failed = true; pendingEvents.Clear(); }
                throw;
            }
        }
    }

    private void CommitEvents()
    {
        if (eventSink is null || pendingEvents.Count == 0) return;
        AppendEvents(pendingEvents);
        // One synchronous flush per completed business group. Visible to readers, not per-event fsync.
        // Disk/encoding errors propagate before publishing any of this group to the live calculator.
        var batch = pendingEvents.ToArray(); pendingEvents.Clear();
        eventSink(batch); EventsWritten += batch.Length; onChanged?.Invoke();
    }
    public void AppendEvents(IReadOnlyList<TraceEvent> source)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (eventWriter is null) return;
            foreach (var item in source) eventWriter.Write(item with { Sequence = ++fileSequence });
            eventWriter.Flush();
        }
    }
}
