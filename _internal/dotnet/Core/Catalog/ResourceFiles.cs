using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

/// <summary>The explicit internal resource root, independent of the working directory.</summary>
public sealed class ResourceFiles(string internalRoot)
{
    private sealed record CompressedResource(long ModifiedTicks, long Length, EvidenceValue Value);
    private readonly object compressedGate = new();
    private readonly Dictionary<string, CompressedResource> compressed = new(OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
    private readonly Dictionary<string, CompressedResource> uncompressed = new(OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
    public string InternalRoot { get; } = Path.GetFullPath(internalRoot);
    public string PathFor(string relative) => Path.GetFullPath(Path.Combine(InternalRoot, relative));

    public IEnumerable<string> TableCandidates(string name)
    {
        yield return PathFor("../endfield_tables/Data/TableCfg/" + name);
        yield return PathFor("data/local_tables/" + name);
    }

    internal static EvidenceValue ReadStrict(string path) =>
        EvidenceJson.Parse(new UTF8Encoding(false, true).GetString(File.ReadAllBytes(path)));

    public EvidenceValue? Read(string path)
    {
        try
        {
            // Keep a UTF-8 BOM visible: the reference JSON loader rejects it too.
            return ReadStrict(path);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException)
        {
            return null;
        }
    }

    public EvidenceValue? ReadRelative(string path) => Read(PathFor(path));

    internal IEnumerable<(string Path, EvidenceObject Payload)> JsonObjects(string relative)
    {
        var directory = PathFor(relative);
        if (!Directory.Exists(directory)) yield break;
        foreach (var path in Directory.EnumerateFileSystemEntries(directory, "*.json"))
            if (Read(path) is EvidenceObject payload) yield return (path, payload);
    }

    public EvidenceValue? ReadBytes(string path)
    {
        try { return JsonByteEncoding.Parse(File.ReadAllBytes(path)); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException or DecoderFallbackException) { return null; }
    }

    // Only catalog consumers opt into shared immutable JSON; ordinary Read/ReadRelative
    // continue returning independent mutable values.
    internal EvidenceValue? ReadOnlyRelative(string path) => ReadCached(path, gzip: false);
    internal EvidenceValue? ReadOnly(string path) => ReadCached(path, gzip: false, propagateEncodingErrors: true);

    public EvidenceValue? ReadGzipRelative(string path) => ReadCached(path, gzip: true);

    private EvidenceValue? ReadCached(string path, bool gzip, bool propagateEncodingErrors = false)
    {
        path = PathFor(path);
        lock (compressedGate)
        {
            var cache = gzip ? compressed : uncompressed;
            try
            {
                FileInfo before = new(path);
                var modifiedTicks = before.LastWriteTimeUtc.Ticks; var length = before.Length;
                if (cache.TryGetValue(path, out var saved) && saved.ModifiedTicks == modifiedTicks
                    && saved.Length == length) return saved.Value;
                var bytes = File.ReadAllBytes(path);
                var value = gzip ? CompiledResource.TryRead(path + ".egr", bytes, out var prepared) ? prepared : GzipMembers.ParseJson(bytes)
                    : EvidenceJson.ParseReadOnlyUtf8(bytes);
                FileInfo after = new(path);
                if (modifiedTicks != after.LastWriteTimeUtc.Ticks || length != after.Length)
                    throw new IOException("Resource changed while loading");
                // Scope is this explicit resource root. Independent calculations share immutable data, never battle state.
                cache[path] = new(after.LastWriteTimeUtc.Ticks, after.Length, value);
                return value;
            }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException
                || !propagateEncodingErrors && error is DecoderFallbackException)
            {
                cache.Remove(path);
                return null;
            }
        }
    }
}

internal static class CatalogValues
{
    public static IEnumerable<EvidenceValue> Iterable(EvidenceValue value) => value switch
    {
        EvidenceArray array => array.Items,
        EvidenceObject obj => obj.Fields.Keys.Select(key => (EvidenceValue)new EvidenceText(key)),
        EvidenceText text => text.Value.EnumerateRunes().Select(unit => (EvidenceValue)new EvidenceText(unit.ToString())),
        _ => throw new InvalidCastException("Resource value is not iterable"),
    };

    public static bool Truth(EvidenceValue? value) => value switch
    {
        null or EvidenceNull => false,
        EvidenceBoolean flag => flag.Value,
        EvidenceInteger number => !number.Value.IsZero,
        EvidenceReal number => number.Value != 0,
        EvidenceText text => text.Value.Length != 0,
        EvidenceArray array => array.Items.Count != 0,
        EvidenceObject obj => obj.Fields.Count != 0,
        _ => throw new InvalidDataException("Unsupported resource value"),
    };

    public static EvidenceValue Or(params EvidenceValue?[] values) => values.FirstOrDefault(Truth) ?? values.LastOrDefault() ?? EvidenceNull.Value;

    public static string Text(EvidenceValue? value) => PythonDisplay.String(value ?? EvidenceNull.Value);

    public static IEnumerable<EvidenceObject> Entries(EvidenceValue? value)
    {
        if (value is EvidenceObject obj) value = obj.Get("entries");
        return value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    }
}
