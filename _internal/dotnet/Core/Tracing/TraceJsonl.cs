using System.Numerics;
using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

public abstract record TraceRecord;
public sealed record TracePreviousVolume(int Volume, string FileName);
public sealed record TraceHeader(string RecordingId, int Volume, TracePreviousVolume? PreviousVolume,
    string Language, string GeneratorVersion, string TimeZoneId, int TimeZoneOffsetMinutes,
    IReadOnlyDictionary<string, string> Resources, int Version = 2) : TraceRecord;
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
        TraceHeader header => Object(("format", Text("endfield.trace")), ("version", Number(header.Version)),
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
        var value = ValidatedObject(record);
        return PythonSortedJson.Serialize(value, compact: true) + "\n";
    }

    internal static EvidenceObject ValidatedObject(TraceRecord record)
    {
        var value = ToObject(record); Validate(value, record is TraceHeader); Finite(value); return value;
    }

    public static TraceRecord Parse(string line, bool header)
        => Parse(line, header, null);

    internal static TraceRecord Parse(string line, bool header, EvidenceJson.ReadOnlyContext? context)
        => Validate(ReadObject(line, context), header);

    internal static EvidenceObject ReadObject(string line, EvidenceJson.ReadOnlyContext? context)
    {
        EvidenceObject value;
        try { value = RequireObject(context is null ? EvidenceJson.ParseReadOnly(line) : context.Parse(line)); }
        catch (FormatException error) { throw new InvalidDataException("Invalid trace JSON", error); }
        Finite(value);
        return value;
    }

    internal static TraceRecord Validate(EvidenceObject value, bool header)
    {
        if (header)
        {
            if (RequireText(value.Get("format")) != "endfield.trace" || RequireInteger(value.Get("version")) is not (1 or 2))
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
                RequireObject(value.Get("resources")).Fields.ToDictionary(pair => pair.Key, pair => RequireText(pair.Value), StringComparer.Ordinal), RequireInt32(value.Get("version")));
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
    private readonly Dictionary<long, string> sessions = [];
    private readonly TraceReferences references = new();
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
            var value = TraceJsonl.ReadObject(line, context);
            if (Header?.Version == 2)
            {
                if (value.Get("type") is EvidenceText { Value: "definition" })
                {
                    if (value.Get("kind") is EvidenceText { Value: "capture_session" })
                    {
                        if (value.Get("ref") is not EvidenceInteger reference || reference.Value != sessions.Count + 1
                            || value.Get("session_id") is not EvidenceText { Value.Length: > 0 } session || sessions.ContainsValue(session.Value))
                            throw new InvalidDataException("Invalid or duplicate trace session definition");
                        sessions[(long)reference.Value] = session.Value;
                    }
                    else references.Define(value);
                    pending.SetLength(0); bytes = bytes[(newline + 1)..]; continue;
                }
                if (value.Get("source") is EvidenceObject source && source.Fields.ContainsKey("session_ref"))
                {
                    if (source.Get("session_ref") is not EvidenceInteger reference || reference.Value < 1 || reference.Value > long.MaxValue
                        || source.Fields.ContainsKey("session_id") || !sessions.TryGetValue((long)reference.Value, out var session))
                        throw new InvalidDataException("Invalid trace session reference");
                    var fields = source.Fields.Where(pair => pair.Key != "session_ref").ToDictionary(); fields["session_id"] = new EvidenceText(session);
                    var envelope = value.Fields.ToDictionary(); envelope["source"] = new EvidenceObject(fields);
                    value = (EvidenceObject)FrozenEvidence.Capture(new EvidenceObject(envelope));
                }
                value = (EvidenceObject)references.Decode(value);
                if (value.Get("data") is EvidenceObject data && data.Fields.ContainsKey("legacy_layout"))
                    throw new InvalidDataException("V2 events cannot contain legacy layouts");
            }
            var record = TraceJsonl.Validate(value, header: Header is null);
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
    private readonly Dictionary<string, int> sessions = new(StringComparer.Ordinal);
    private readonly int version;
    private readonly TraceReferences references = new();
    public TraceJsonlWriter(Stream destination, TraceHeader header, bool leaveOpen = false)
    {
        var line = TraceJsonl.Serialize(header);
        writer = new(destination, TraceJsonl.Encoding, 16 * 1024, leaveOpen) { NewLine = "\n" };
        try { writer.Write(line); }
        catch { writer.Dispose(); throw; }
        lastSequence = header.Volume == 1 ? 0 : null;
        version = header.Version;
    }
    public void Write(TraceEvent item)
    {
        if (lastSequence is long previous && (previous == long.MaxValue || item.Sequence != previous + 1))
            throw new InvalidDataException("Trace sequence is not continuous");
        var value = TraceJsonl.ValidatedObject(item);
        if (version == 2 && item.Data.Fields.ContainsKey("legacy_layout"))
            throw new InvalidDataException("V2 events cannot contain legacy layouts");
        if (version == 2 && item.Source.Get("session_id") is EvidenceText { Value.Length: > 0 } session)
        {
            if (!sessions.TryGetValue(session.Value, out var reference))
            {
                reference = sessions.Count + 1;
                WriteObject(new EvidenceObject(new Dictionary<string, EvidenceValue>
                {
                    ["type"] = new EvidenceText("definition"), ["kind"] = new EvidenceText("capture_session"),
                    ["ref"] = new EvidenceInteger(reference), ["session_id"] = session,
                }));
                sessions[session.Value] = reference;
            }
            var source = item.Source.Fields.Where(pair => pair.Key != "session_id").ToDictionary(); source["session_ref"] = new EvidenceInteger(reference);
            var envelope = value.Fields.ToDictionary(); envelope["source"] = new EvidenceObject(source); value = new(envelope);
        }
        if (version == 2) value = (EvidenceObject)references.Encode(value, WriteObject);
        WriteObject(value); lastSequence = item.Sequence;
    }
    private void WriteObject(EvidenceObject value) => writer.Write(PythonSortedJson.Serialize(value, compact: true) + "\n");
    public void Flush() => writer.Flush();
    public void Dispose() => writer.Dispose();
}
