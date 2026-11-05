using System.Globalization;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Runtime.Realtime;

namespace EndfieldLogs.Runtime.Tracing;

/// <summary>Ordered trace recording and live ingestion. The capture owner serializes business events here.</summary>
public sealed partial class TraceRecording : IDisposable
{
    private readonly object gate = new();
    private readonly TraceBridge bridge;
    private readonly Action<string>? liveSink;
    private readonly Action? onChanged;
    private StreamWriter? writer;
    private bool disposed;
    private string? filePath;
    private SkillResourceCatalog? catalog;
    private TimeZoneInfo? zone;
    private long fileSequence;
    public string? FilePath { get { lock (gate) return filePath; } }
    public long LinesWritten { get; private set; }

    public TraceRecording(LiveBattleSession live, string? logDirectory = null, SkillResourceCatalog? identities = null,
        TimeZoneInfo? timeZone = null, DateTime? archiveTime = null, Action? onChanged = null)
        : this(live.FeedLine, logDirectory, identities, timeZone, archiveTime, onChanged) { }

    public TraceRecording(Action<string> liveSink, string? logDirectory = null, SkillResourceCatalog? identities = null,
        TimeZoneInfo? timeZone = null, DateTime? archiveTime = null, Action? onChanged = null)
    {
        this.liveSink = liveSink; this.onChanged = onChanged;
        catalog = identities; zone = timeZone;
        if (logDirectory is not null)
        {
            var reserved = ReserveFile(logDirectory, archiveTime ?? DateTime.Now, ".log");
            writer = new(reserved.Stream, new UTF8Encoding(false, true)) { AutoFlush = true, NewLine = "\n" };
            filePath = reserved.Path;
        }
        bridge = new(WriteLine, identities, timeZone);
    }

    public bool IsWriting(string path)
    {
        lock (gate) return !disposed && (writer is not null || eventWriter is not null)
            && string.Equals(filePath, Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase);
    }
    public TraceRecording NewFileRecording(string directory)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            return currentHeader is { } header
                ? CreateStructured(_ => { }, header with { RecordingId = Guid.NewGuid().ToString("N"), Volume = 1, PreviousVolume = null }, directory, catalog)
                : new TraceRecording(_ => { }, directory, catalog, zone);
        }
    }
    public void Handle(BattleLogEvent value)
    {
        Execute(() => bridge.Handle(value));
    }
    public void BeginSession(long timestampMs)
    {
        Execute(() => bridge.BeginCaptureSession(timestampMs));
    }
    public void EndSession(long? timestampMs = null)
    {
        Execute(() => bridge.EndCaptureSession(timestampMs));
    }
    public void FlushPending() { lock (gate) { if (!disposed) Execute(bridge.FlushPending); } }
    public void AppendLine(string line) { lock (gate) { writer?.Write(line); writer?.Flush(); } }
    private void WriteLine(string line)
    {
        writer?.Write(line); // A disk error propagates to the capture owner before publishing unrecorded evidence.
        liveSink!(line); LinesWritten++; onChanged?.Invoke();
    }
    private static (string Path, FileStream Stream) ReserveFile(string directory, DateTime now, string extension, string? volumeFolder = null)
    {
        var folder = volumeFolder ?? Path.Combine(Path.GetFullPath(directory), now.ToString("yyyyMMdd", CultureInfo.InvariantCulture));
        Directory.CreateDirectory(folder);
        var stem = "trace_" + now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        for (var suffix = 0; ; suffix++)
        {
            var path = Path.Combine(folder, stem + (suffix == 0 ? "" : "_" + suffix.ToString("00", CultureInfo.InvariantCulture)) + extension);
            try { return (path, new(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 16 * 1024)); }
            catch (IOException) when (File.Exists(path)) { }
        }
    }
    public void CloseFile() => Close(false);
    public void Dispose() => Close(true);
    private void Close(bool finishSession)
    {
        lock (gate)
        {
            if (disposed) return;
            try { if (!failed) Execute(() => { if (finishSession) bridge.EndCaptureSession(); else bridge.FlushPending(); }); }
            finally
            {
                disposed = true;
                try { eventWriter?.Dispose(); }
                finally { eventWriter = null; writer?.Dispose(); writer = null; }
            }
        }
    }
}
