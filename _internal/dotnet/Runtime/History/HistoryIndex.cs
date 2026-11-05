using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

/// <summary>Disposable per-source summary cache. Full analysis snapshots never enter index files.</summary>
public sealed class HistoryIndex(string directory, HistoryCatalog? catalog = null)
{
    private readonly HistoryCatalog catalog = catalog ?? new();
    private sealed record Envelope(int Version, string Source, bool Trace, HistoryFileSignature Signature, IReadOnlyList<HistoryRecord> Records);
    private string CachePath(string path, bool trace) => Path.Combine(directory,
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes("dotnet-history-v1|" + (trace ? "trace" : "ndjson") + path))) + ".json");
    public IReadOnlyList<HistoryRecord> Records(string path, bool trace = false, CancellationToken cancellationToken = default)
    {
        path = Path.GetFullPath(path); var signature = HistoryFileSignature.Read(path); var cache = CachePath(path, trace);
        cancellationToken.ThrowIfCancellationRequested();
        var saved = Read(cache);
        var structured = trace && Path.GetExtension(path).Equals(".jsonl", StringComparison.OrdinalIgnoreCase)
            ? TraceVolumes.Resolve(path, cancellationToken) : null;
        var session = trace ? null : SessionVolumes.Resolve(path, cancellationToken);
        if (saved is { Version: 2 } && saved.Source == path && saved.Trace == trace && saved.Signature == signature
            && (structured is null || saved.Records.All(row => row.StructuredSource is { } previous && TraceVolumes.SameSources(previous, structured)))
            && (session?.Volumes[0].Header is null || saved.Records.Count > 0
                && saved.Records.All(row => row.SessionSource is { } previous && SessionVolumes.SameSources(previous, session))))
            return saved.Records.Select(row => row with { Players = row.Players.ToArray() }).ToArray();
        var records = structured is not null ? HistoryCatalog.ReadStructured(structured, cancellationToken)
            : session?.Volumes[0].Header is not null ? HistoryCatalog.ReadSession(session, cancellationToken) : catalog.Read(path, trace, cancellationToken);
        if (signature != HistoryFileSignature.Read(path)) throw new InvalidDataException("日志正在变化，请稍后刷新记录");
        Save(cache, new(2, path, trace, signature, records)); return records;
    }
    public void Relocate(string oldPath, string newPath)
    {
        oldPath = Path.GetFullPath(oldPath); newPath = Path.GetFullPath(newPath);
        HistoryFileSignature signature;
        try { signature = HistoryFileSignature.Read(newPath); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return; }
        foreach (var trace in new[] { true, false })
        {
            var oldCache = CachePath(oldPath, trace); var saved = Read(oldCache);
            if (saved is not { Version: 2 } || saved.Source != oldPath || saved.Trace != trace || saved.Signature != signature) continue;
            var records = saved.Records.Select(row => HistoryFiles.Relocate(row, oldPath, newPath)).ToArray();
            if (Save(CachePath(newPath, trace), new(2, newPath, trace, saved.Signature, records)))
                try { File.Delete(oldCache); } catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        }
    }
    public static string ResolveLogDirectory(string preferred, SettingsContext context)
    {
        foreach (var candidate in new[] { preferred, Path.Combine(context.ApplicationRoot, "logs"),
            Path.Combine(context.ApplicationRoot, "_internal", "logs"), Path.Combine(context.WorkingDirectory, "logs") }.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                if (!Directory.Exists(candidate)) continue;
                foreach (var file in Directory.EnumerateFiles(candidate, "session_*.ndjson", SearchOption.AllDirectories))
                    try { if (new FileInfo(file).Length > 0) return Path.GetFullPath(candidate); }
                    catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        }
        return Path.GetFullPath(preferred);
    }
    private static Envelope? Read(string path)
    {
        try
        {
            var result = JsonSerializer.Deserialize<Envelope>(File.ReadAllText(path, new UTF8Encoding(false, true)), JsonContract.Options);
            return result?.Records is not null && result.Records.All(row => row is not null && row.Players is not null) ? result : null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or FormatException or ArgumentException) { return null; }
    }
    private static bool Save(string path, Envelope payload)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllText(temporary, JsonSerializer.Serialize(payload, JsonContract.Options), new UTF8Encoding(false));
            File.Move(temporary, path, overwrite: true); return true;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or ArgumentException) { return false; }
        finally { try { File.Delete(temporary); } catch (Exception error) when (error is IOException or UnauthorizedAccessException) { } }
    }
}
