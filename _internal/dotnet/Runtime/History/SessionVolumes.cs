using System.Text;
using System.Text.Json;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Capture;

namespace EndfieldLogs.Runtime.History;

public sealed record SessionVolume(string FilePath, SessionVolumeHeader? Header, HistoryFileSignature Signature);
public sealed record SessionVolumeChain(IReadOnlyList<SessionVolume> Volumes, IReadOnlyList<string> Issues)
{
    public bool IsComplete => Issues.Count == 0;
}

/// <summary>Continuous raw business-event files. Headers are transport metadata, never replayed as business events.</summary>
public static class SessionVolumes
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static SessionVolume Inspect(string path)
    {
        var signature = HistoryFileSignature.Read(path);
        using FileStream file = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using StreamReader reader = new(file, Utf8, detectEncodingFromByteOrderMarks: false);
        SessionVolumeHeader? header = null;
        var linked = false;
        try
        {
            var line = reader.ReadLine();
            if (line is not null)
            {
                using var document = JsonDocument.Parse(line);
                if (document.RootElement.ValueKind == JsonValueKind.Object
                    && document.RootElement.TryGetProperty("type", out var type) && type.ValueKind == JsonValueKind.String
                    && type.GetString() == "session_volume")
                {
                    linked = true;
                    header = JsonSerializer.Deserialize<SessionVolumeHeader>(line, JsonContract.Options)
                        ?? throw new InvalidDataException("session 缺少分卷文件头");
                }
            }
        }
        catch (JsonException error)
        { if (linked) throw new InvalidDataException("session 分卷文件头无效", error); /* Old raw logs may start with a malformed event. */ }
        if (header is not null && (header.SchemaVersion != 1 || string.IsNullOrEmpty(header.RecordingId)
            || string.IsNullOrEmpty(header.SessionId) || string.IsNullOrEmpty(header.TraceRecordingId)
            || header.Volume < 1 || header.TraceVolume < 1 || header.EventOffset < 0
            || header.TimeZoneOffsetMinutes is < -840 or > 840
            || (header.Volume == 1 ? header.PreviousVolume is not null || header.EventOffset != 0
                : header.PreviousVolume is null || header.PreviousVolume.Volume != header.Volume - 1)))
            throw new InvalidDataException("session 分卷文件头无效");
        if (header?.PreviousVolume is { } previous && (string.IsNullOrEmpty(previous.File) || previous.File is "." or ".."
            || previous.File != Path.GetFileName(previous.File) || previous.File.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0))
            throw new InvalidDataException("session 前卷引用必须是同目录文件名");
        if (!Matches(path, signature, true)) throw new InvalidDataException("session 在读取文件头时发生变化，请刷新记录");
        return new(path, header, signature);
    }

    public static SessionVolumeChain Resolve(string path, CancellationToken token = default)
    {
        path = Path.GetFullPath(path); token.ThrowIfCancellationRequested();
        var selected = Inspect(path);
        if (selected.Header is null) return new([selected], []);
        List<SessionVolume> volumes = [selected];
        foreach (var candidate in Directory.EnumerateFiles(Path.GetDirectoryName(path)!, "session_*.ndjson"))
        {
            token.ThrowIfCancellationRequested();
            if (string.Equals(candidate, path, StringComparison.OrdinalIgnoreCase)) continue;
            SessionVolume other;
            try { other = Inspect(candidate); }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException) { continue; }
            if (other.Header?.RecordingId == selected.Header.RecordingId) volumes.Add(other);
        }
        volumes.Sort((left, right) => left.Header!.Volume.CompareTo(right.Header!.Volume));
        List<string> issues = []; var expected = 1;
        foreach (var volume in volumes)
        {
            var header = volume.Header!;
            if (header.Volume < expected) throw new InvalidDataException($"session 有重复的第 {header.Volume} 卷");
            if (header.Volume > expected) issues.Add($"session 缺少第 {expected}～{header.Volume - 1} 卷，记录不完整");
            expected = header.Volume + 1;
            if (header.SessionId != selected.Header.SessionId || header.TraceRecordingId != selected.Header.TraceRecordingId
                || header.TimeZoneOffsetMinutes != selected.Header.TimeZoneOffsetMinutes)
                throw new InvalidDataException("session 连续分卷的会话、trace 或时区不一致");
            if (header.PreviousVolume is { } previous)
            {
                var named = Path.Combine(Path.GetDirectoryName(path)!, previous.File);
                var predecessor = volumes.FirstOrDefault(item => item.Header!.Volume == previous.Volume);
                if (File.Exists(named) && predecessor is not null && !string.Equals(named, predecessor.FilePath, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("session 前卷文件名与录制身份不一致");
            }
        }
        return new(volumes.AsReadOnly(), issues.AsReadOnly());
    }

    public static bool SameSources(SessionVolumeChain left, SessionVolumeChain right) => left.IsComplete && right.IsComplete
        && left.Volumes.Count == right.Volumes.Count && left.Volumes.Zip(right.Volumes).All(pair =>
            string.Equals(pair.First.FilePath, pair.Second.FilePath, StringComparison.OrdinalIgnoreCase)
            && pair.First.Signature == pair.Second.Signature && pair.First.Header == pair.Second.Header);

    public static bool RetainsSources(SessionVolumeChain original, SessionVolumeChain current) => current.IsComplete
        && original.Volumes.All(old => current.Volumes.Any(item =>
            string.Equals(old.FilePath, item.FilePath, StringComparison.OrdinalIgnoreCase)
            && old.Header == item.Header && item.Signature.ByteSize >= old.Signature.ByteSize));

    private static bool Matches(string path, HistoryFileSignature expected, bool allowAppend)
    {
        var actual = HistoryFileSignature.Read(path);
        return actual == expected || allowAppend && actual.ByteSize > expected.ByteSize;
    }
    public static IEnumerable<string> ReadLines(SessionVolumeChain chain, CancellationToken token = default, bool allowAppend = false)
    {
        if (!chain.IsComplete) throw new InvalidDataException(string.Join('；', chain.Issues));
        long events = 0;
        foreach (var volume in chain.Volumes)
        {
            if (!Matches(volume.FilePath, volume.Signature, allowAppend)) throw new InvalidDataException("session 已变化，请刷新记录");
            if (volume.Header is { } header && header.EventOffset != events) throw new InvalidDataException("session 跨卷事件位置不连续");
            using FileStream file = new(volume.FilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            if (volume.Header is null)
            {
                using StreamReader legacy = new(file, Utf8, detectEncodingFromByteOrderMarks: false);
                while (legacy.ReadLine() is { } raw) { token.ThrowIfCancellationRequested(); yield return raw; }
            }
            else
            {
                using MemoryStream line = new(); byte[] buffer = new byte[64 * 1024]; var remaining = volume.Signature.ByteSize;
                var first = true;
                while (remaining > 0)
                {
                    token.ThrowIfCancellationRequested(); var count = (int)Math.Min(remaining, buffer.Length);
                    file.ReadExactly(buffer.AsSpan(0, count)); remaining -= count; var start = 0;
                    for (var at = 0; at < count; at++)
                    {
                        if (buffer[at] != (byte)'\n') continue;
                        line.Write(buffer.AsSpan(start, at - start)); var raw = Utf8.GetString(line.GetBuffer(), 0, (int)line.Length);
                        line.SetLength(0); start = at + 1;
                        if (first)
                        {
                            if (JsonSerializer.Deserialize<SessionVolumeHeader>(raw, JsonContract.Options) != volume.Header)
                                throw new InvalidDataException("session 分卷文件头已变化，请刷新记录");
                            first = false;
                        }
                        else { events++; yield return raw; }
                    }
                    line.Write(buffer.AsSpan(start, count - start));
                }
                if (first || line.Length != 0) throw new InvalidDataException("session 有尚未完成的 NDJSON 行，请稍后重试");
            }
            if (!Matches(volume.FilePath, volume.Signature, allowAppend)) throw new InvalidDataException("session 在读取时发生变化，请刷新记录");
        }
    }
}
