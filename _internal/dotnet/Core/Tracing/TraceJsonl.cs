using System.Numerics;
using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

public abstract record TraceRecord;
public sealed record TracePreviousVolume(int Volume, string FileName);
public sealed record TraceHeader(string RecordingId, int Volume, TracePreviousVolume? PreviousVolume,
    string Language, string GeneratorVersion, string TimeZoneId, int TimeZoneOffsetMinutes,
    IReadOnlyDictionary<string, string> Resources) : TraceRecord;
public sealed record TraceEvent(long Sequence, long CapturedAtMs, string Type, EvidenceObject Data,
    EvidenceObject Source, long? ClientTickMs = null) : TraceRecord;

/// <summary>Disk-only JSON boundary. Live consumers receive TraceEvent objects directly.</summary>
public static class TraceJsonl
{
    internal static readonly UTF8Encoding Encoding = new(false, true);
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) =>
        new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceInteger Number(long value) => new(value);
    private static EvidenceObject RequireObject(EvidenceValue value) => value as EvidenceObject ?? throw new InvalidDataException("Expected trace object");
    private static string RequireText(EvidenceValue value) => value is EvidenceText { Value.Length: > 0 } text ? text.Value
        : throw new InvalidDataException("Expected nonempty trace text");
    private static long RequireInteger(EvidenceValue value) => value is EvidenceInteger integer && integer.Value >= long.MinValue && integer.Value <= long.MaxValue
        ? (long)integer.Value : throw new InvalidDataException("Expected trace integer");
    private static int RequireInt32(EvidenceValue value) => RequireInteger(value) is var integer && integer >= int.MinValue && integer <= int.MaxValue
        ? (int)integer : throw new InvalidDataException("Trace integer out of range");

    public static EvidenceObject ToObject(TraceRecord record) => record switch
    {
        TraceHeader header => Object(("format", Text("endfield.trace")), ("version", Number(1)),
            ("recording_id", Text(header.RecordingId)), ("volume", Number(header.Volume)),
            ("previous_volume", header.PreviousVolume is { } previous
                ? Object(("volume", Number(previous.Volume)), ("file", Text(previous.FileName))) : EvidenceNull.Value),
            ("generator", Object(("language", Text(header.Language)), ("version", Text(header.GeneratorVersion)))),
            ("timezone", Object(("id", Text(header.TimeZoneId)), ("offset_minutes", Number(header.TimeZoneOffsetMinutes)))),
            ("resources", new EvidenceObject(header.Resources.ToDictionary(pair => pair.Key, pair => (EvidenceValue)Text(pair.Value), StringComparer.Ordinal)))),
        TraceEvent item => EventObject(item),
        _ => throw new InvalidDataException("Unsupported trace record"),
    };

    private static EvidenceObject EventObject(TraceEvent item)
    {
        var result = Object(("seq", Number(item.Sequence)), ("captured_at_ms", Number(item.CapturedAtMs)),
            ("source", item.Source), ("type", Text(item.Type)), ("data", item.Data));
        if (item.ClientTickMs is long tick) ((Dictionary<string, EvidenceValue>)result.Fields)["client_tick_ms"] = Number(tick);
        return result;
    }

    private static void Finite(EvidenceValue value)
    {
        switch (value)
        {
            case EvidenceReal real when !double.IsFinite(real.Value): throw new InvalidDataException("Non-finite trace number requires explicit evidence status");
            case EvidenceObject obj: foreach (var child in obj.Fields.Values) Finite(child); break;
            case EvidenceArray array: foreach (var child in array.Items) Finite(child); break;
        }
    }

    public static string Serialize(TraceRecord record)
    {
        var value = ToObject(record); Validate(value, record is TraceHeader); Finite(value);
        return PythonSortedJson.Serialize(value, compact: true) + "\n";
    }

    public static TraceRecord Parse(string line, bool header)
        => Parse(line, header, null);

    internal static TraceRecord Parse(string line, bool header, EvidenceJson.ReadOnlyContext? context)
    {
        EvidenceObject value;
        try { value = RequireObject(context is null ? EvidenceJson.ParseReadOnly(line) : context.Parse(line)); }
        catch (FormatException error) { throw new InvalidDataException("Invalid trace JSON", error); }
        Finite(value);
        return Validate(value, header);
    }

    private static TraceRecord Validate(EvidenceObject value, bool header)
    {
        if (header)
        {
            if (RequireText(value.Get("format")) != "endfield.trace" || RequireInteger(value.Get("version")) != 1)
                throw new InvalidDataException("Unsupported trace format or version");
            var volume = RequireInt32(value.Get("volume"));
            if (volume < 1) throw new InvalidDataException("Trace volume must be positive");
            TracePreviousVolume? previous = null;
            if (value.Get("previous_volume") is not EvidenceNull)
            {
                var raw = RequireObject(value.Get("previous_volume"));
                previous = new(RequireInt32(raw.Get("volume")), RequireText(raw.Get("file")));
            }
            if ((volume == 1 && previous is not null) || (volume > 1 && (previous is null || previous.Volume != volume - 1)))
                throw new InvalidDataException("Trace previous-volume reference is inconsistent");
            var generator = RequireObject(value.Get("generator")); var timezone = RequireObject(value.Get("timezone"));
            return new TraceHeader(RequireText(value.Get("recording_id")), volume, previous,
                RequireText(generator.Get("language")), RequireText(generator.Get("version")),
                RequireText(timezone.Get("id")), RequireInt32(timezone.Get("offset_minutes")),
                RequireObject(value.Get("resources")).Fields.ToDictionary(pair => pair.Key, pair => RequireText(pair.Value), StringComparer.Ordinal));
        }
        var sequence = RequireInteger(value.Get("seq"));
        if (sequence < 1) throw new InvalidDataException("Trace sequence must be positive");
        var source = RequireObject(value.Get("source"));
        if (source.Fields.TryGetValue("owner_id", out var owner) && owner is not EvidenceNull
            && (owner is not EvidenceText ownerText || ownerText.Value.Length == 0 || ownerText.Value.Any(unit => unit is < '0' or > '9')))
            throw new InvalidDataException("Trace instance IDs must be decimal strings");
        return new TraceEvent(sequence, RequireInteger(value.Get("captured_at_ms")), RequireText(value.Get("type")),
            RequireObject(value.Get("data")), source, value.Get("client_tick_ms") is EvidenceNull ? null : RequireInteger(value.Get("client_tick_ms")));
    }
}

/// <summary>Incremental UTF-8 framing; a partial active-file tail remains pending.</summary>
public sealed class TraceJsonlReader : IDisposable
{
    private readonly MemoryStream pending = new();
    private readonly EvidenceJson.ReadOnlyContext context = new();
    private long? lastSequence;
    public TraceHeader? Header { get; private set; }
    public long PendingBytes => pending.Length;

    public IReadOnlyList<TraceRecord> Feed(ReadOnlySpan<byte> bytes)
    {
        List<TraceRecord> records = [];
        while (!bytes.IsEmpty)
        {
            var newline = bytes.IndexOf((byte)'\n');
            var length = newline < 0 ? bytes.Length : newline;
            pending.Write(bytes[..length]);
            if (newline < 0) break;
            var line = TraceJsonl.Encoding.GetString(pending.GetBuffer(), 0, checked((int)pending.Length));
            var record = TraceJsonl.Parse(line, header: Header is null, context);
            if (record is TraceHeader header) { Header = header; lastSequence = header.Volume == 1 ? 0 : null; }
            else if (record is TraceEvent item)
            {
                if (lastSequence is long previous && (previous == long.MaxValue || item.Sequence != previous + 1))
                    throw new InvalidDataException("Trace sequence is not continuous");
                lastSequence = item.Sequence;
            }
            records.Add(record); pending.SetLength(0); bytes = bytes[(newline + 1)..];
        }
        return records;
    }
    public void Dispose() { pending.Dispose(); context.Clear(); }
}

public sealed class TraceJsonlWriter : IDisposable
{
    private readonly StreamWriter writer;
    private long? lastSequence;
    public TraceJsonlWriter(Stream destination, TraceHeader header, bool leaveOpen = false)
    {
        var line = TraceJsonl.Serialize(header);
        writer = new(destination, TraceJsonl.Encoding, 16 * 1024, leaveOpen) { NewLine = "\n" };
        try { writer.Write(line); }
        catch { writer.Dispose(); throw; }
        lastSequence = header.Volume == 1 ? 0 : null;
    }
    public void Write(TraceEvent item)
    {
        if (lastSequence is long previous && (previous == long.MaxValue || item.Sequence != previous + 1))
            throw new InvalidDataException("Trace sequence is not continuous");
        writer.Write(TraceJsonl.Serialize(item)); lastSequence = item.Sequence;
    }
    public void Flush() => writer.Flush();
    public void Dispose() => writer.Dispose();
}
