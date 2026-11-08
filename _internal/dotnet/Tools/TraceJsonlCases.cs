using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class TraceJsonlCases
{
    public static int HistoricalEvents(string fixturePath, string outputPath)
    {
        var fixture = (EvidenceObject)EvidenceJson.Parse(File.ReadAllText(fixturePath));
        var time = (long)((EvidenceInteger)fixture.Get("captured_at_ms")).Value;
        var offset = (int)((EvidenceInteger)fixture.Get("timezone_offset_minutes")).Value;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        using var stream = File.Create(outputPath);
        using TraceJsonlWriter writer = new(stream, new("historical-contract", 1, null, "contract", "0.2.1", "UTC", offset, new Dictionary<string, string>()));
        var sequence = 0;
        foreach (var row in ((EvidenceArray)fixture.Get("observations")).Items.Cast<EvidenceObject>())
        {
            var (kind, raw) = HistoricalEvidenceWire.Data(((EvidenceText)row.Get("line")).Value) ?? throw new InvalidDataException("Expected historical observation");
            var source = new EvidenceObject(new Dictionary<string, EvidenceValue>());
            writer.Write(new TraceEvent(++sequence, time, kind, TraceModel.Compact(raw, source, null, kind), source));
        }
        Console.WriteLine($"Historical observations: {sequence}"); return 0;
    }
    internal static IReadOnlyList<string> ConnectedLines(TraceEvent item, int offset) => TraceLegacyExporter.Lines(item, offset);
    public static int ExportDamage(string inputPath, string outputPath, bool includeEntities = false)
    {
        using var input = File.OpenRead(inputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        using var output = new StreamWriter(outputPath, append: false, new UTF8Encoding(false, true));
        using TraceJsonlReader reader = new();
        var count = 0;
        byte[] chunk = new byte[4096];
        int size;
        while ((size = input.Read(chunk)) > 0)
            foreach (var record in reader.Feed(chunk.AsSpan(0, size)))
            {
                if (record is TraceHeader header && header.Volume != 1)
                    throw new NotSupportedException("Damage-only verification requires a complete first volume");
                if (record is not TraceEvent item) continue;
                var lines = includeEntities ? ConnectedLines(item, reader.Header!.TimeZoneOffsetMinutes)
                    : DamageLegacyExporter.Lines(item, reader.Header!.TimeZoneOffsetMinutes);
                foreach (var line in lines) output.Write(line);
                count++;
            }
        if (reader.Header is null || reader.PendingBytes != 0) throw new InvalidDataException("Damage JSONL fixture is incomplete");
        Console.WriteLine($"Independent JSONL damage export: {count} events");
        return 0;
    }

    public static int RoundTrip(string inputPath, string outputPath)
    {
        using var input = File.OpenRead(inputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        using var output = new FileStream(outputPath, FileMode.Create, FileAccess.Write, FileShare.Read);
        using TraceJsonlReader reader = new();
        TraceJsonlWriter? writer = null;
        var count = 0;
        try
        {
            byte[] chunk = new byte[7];
            int size;
            while ((size = input.Read(chunk)) > 0)
                foreach (var record in reader.Feed(chunk.AsSpan(0, size)))
                {
                    if (record is TraceHeader header) writer = new(output, header, leaveOpen: true);
                    else if (record is TraceEvent item) { writer!.Write(item); count++; }
                }
            if (reader.Header is null || reader.PendingBytes != 0) throw new InvalidDataException("Cross-language fixture is incomplete");
        }
        finally { writer?.Dispose(); }
        Console.WriteLine($"Structured trace roundtrip: {count} events");
        return 0;
    }
}
