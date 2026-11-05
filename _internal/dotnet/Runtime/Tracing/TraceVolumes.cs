using System.Text;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Runtime.Tracing;

public sealed record TraceVolume(string FilePath, TraceHeader Header, HistoryFileSignature Signature);
public sealed record TraceVolumeChain(IReadOnlyList<TraceVolume> Volumes, IReadOnlyList<string> Issues)
{
    public bool IsComplete => Issues.Count == 0;
}

/// <summary>Find linked volumes by recording identity; stream evidence without reconstructing old text.</summary>
public static class TraceVolumes
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    public static bool SameSources(TraceVolumeChain left, TraceVolumeChain right) => left.IsComplete && right.IsComplete
        && left.Volumes.Count == right.Volumes.Count && left.Volumes.Zip(right.Volumes).All(pair =>
            string.Equals(pair.First.FilePath, pair.Second.FilePath, StringComparison.OrdinalIgnoreCase)
            && pair.First.Signature == pair.Second.Signature && TraceJsonl.Serialize(pair.First.Header) == TraceJsonl.Serialize(pair.Second.Header));

    public static TraceVolumeChain? Find(string directory, string recordingId, CancellationToken cancellationToken = default)
    {
        foreach (var candidate in Directory.EnumerateFiles(directory, "*.jsonl"))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (candidate.EndsWith(".input.jsonl", StringComparison.OrdinalIgnoreCase)) continue;
            TraceVolume volume;
            try { volume = Inspect(candidate); }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException or ArgumentException) { continue; }
            if (volume.Header.RecordingId == recordingId) return Resolve(candidate, cancellationToken);
        }
        return null;
    }
    private static TraceVolume Inspect(string path)
    {
        var signature = HistoryFileSignature.Read(path);
        using FileStream file = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using StreamReader reader = new(file, Utf8, detectEncodingFromByteOrderMarks: false);
        var header = (TraceHeader)TraceJsonl.Parse(reader.ReadLine() ?? throw new InvalidDataException("trace 缺少文件头"), header: true);
        if (header.PreviousVolume is { } previous && (previous.FileName is "." or ".."
            || previous.FileName != Path.GetFileName(previous.FileName) || previous.FileName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0))
            throw new InvalidDataException("trace 前卷引用必须是同目录文件名");
        if (HistoryFileSignature.Read(path) != signature) throw new InvalidDataException("trace 在读取文件头时发生变化，请刷新记录");
        return new(path, header, signature);
    }

    public static TraceVolumeChain Resolve(string path, CancellationToken cancellationToken = default)
    {
        path = Path.GetFullPath(path); cancellationToken.ThrowIfCancellationRequested();
        var selected = Inspect(path);
        List<TraceVolume> volumes = [selected];
        foreach (var candidate in Directory.EnumerateFiles(Path.GetDirectoryName(path)!, "*.jsonl"))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (string.Equals(candidate, path, StringComparison.OrdinalIgnoreCase) || candidate.EndsWith(".input.jsonl", StringComparison.OrdinalIgnoreCase)) continue;
            TraceVolume other;
            try { other = Inspect(candidate); }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException or ArgumentException) { continue; }
            if (other.Header.RecordingId == selected.Header.RecordingId) volumes.Add(other);
        }
        volumes.Sort((left, right) => left.Header.Volume.CompareTo(right.Header.Volume));
        List<string> issues = [];
        var expected = 1;
        foreach (var volume in volumes)
        {
            var header = volume.Header;
            if (header.Volume < expected) throw new InvalidDataException($"trace 录制 {header.RecordingId} 有重复的第 {header.Volume} 卷");
            if (header.Volume > expected) issues.Add($"trace 缺少第 {expected}～{header.Volume - 1} 卷，记录不完整");
            expected = header.Volume + 1;
            if (header.Language != selected.Header.Language || header.GeneratorVersion != selected.Header.GeneratorVersion
                || header.TimeZoneId != selected.Header.TimeZoneId || header.TimeZoneOffsetMinutes != selected.Header.TimeZoneOffsetMinutes
                || header.Resources.Count != selected.Header.Resources.Count
                || header.Resources.Any(pair => !selected.Header.Resources.TryGetValue(pair.Key, out var value) || value != pair.Value))
                throw new InvalidDataException("trace 连续分卷的生成器、时区或资源不一致");
            if (header.PreviousVolume is { } previous)
            {
                var named = Path.Combine(Path.GetDirectoryName(path)!, previous.FileName);
                var predecessor = volumes.FirstOrDefault(item => item.Header.Volume == previous.Volume);
                // A renamed predecessor is found by immutable recording ID + volume, without rewriting user files.
                if (File.Exists(named) && predecessor is not null && !string.Equals(named, predecessor.FilePath, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("trace 前卷文件名与录制身份不一致");
            }
        }
        return new(Array.AsReadOnly(volumes.ToArray()), Array.AsReadOnly(issues.ToArray()));
    }

    public static IEnumerable<TraceEvent> ReadEvents(TraceVolumeChain chain, CancellationToken cancellationToken = default)
    {
        if (!chain.IsComplete) throw new InvalidDataException(string.Join('；', chain.Issues));
        long sequence = 0;
        foreach (var volume in chain.Volumes)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (HistoryFileSignature.Read(volume.FilePath) != volume.Signature) throw new InvalidDataException("trace 已变化，请刷新记录");
            using FileStream file = new(volume.FilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using TraceJsonlReader reader = new();
            byte[] buffer = new byte[64 * 1024]; var remaining = volume.Signature.ByteSize;
            while (remaining > 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var count = (int)Math.Min(remaining, buffer.Length); file.ReadExactly(buffer.AsSpan(0, count)); remaining -= count;
                foreach (var record in reader.Feed(buffer.AsSpan(0, count)))
                {
                    if (record is TraceHeader header && TraceJsonl.Serialize(header) != TraceJsonl.Serialize(volume.Header))
                        throw new InvalidDataException("trace 文件头已变化，请刷新记录");
                    if (record is not TraceEvent item) continue;
                    if (sequence == long.MaxValue || item.Sequence != sequence + 1) throw new InvalidDataException("trace 跨卷事件序号不连续");
                    sequence = item.Sequence; yield return item;
                }
            }
            if (reader.Header is null || reader.PendingBytes != 0) throw new InvalidDataException("trace 有尚未完成的 JSONL 行，请稍后重试");
            if (HistoryFileSignature.Read(volume.FilePath) != volume.Signature) throw new InvalidDataException("trace 在读取时发生变化，请刷新记录");
        }
    }
}
