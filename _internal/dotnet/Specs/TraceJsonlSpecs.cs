using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

internal static class TraceJsonlSpecs
{
    public static void Run(Action<bool, string> check)
    {
        TraceHeader header = new("synthetic", 1, null, "csharp", "0.2.1", "Asia/Shanghai", 480, new Dictionary<string, string>());
        var data = (EvidenceObject)EvidenceJson.Parse("""{"label":"中文／技能","values":{"rate":-0.0},"report":false,"empty":[],"none":null,"wide":123456789012345678901234567890}""");
        var source = (EvidenceObject)EvidenceJson.Parse("""{"owner_id":"18446744073709551615","detail_index":0}""");
        TraceEvent first = new(1, 1793412000123, "damage", data, source, 0);
        TraceEvent second = new(2, 1793411999999, "future_observation", data, new(new Dictionary<string, EvidenceValue>()));
        using MemoryStream stream = new();
        using (TraceJsonlWriter writer = new(stream, header, leaveOpen: true)) { writer.Write(first); writer.Write(second); writer.Flush(); }
        var bytes = stream.ToArray();
        check(bytes[0] == '{' && !bytes.Contains((byte)'\r'), "Structured trace uses BOM-free UTF-8 and LF");
        using TraceJsonlReader reader = new();
        List<TraceRecord> actual = [];
        for (var i = 0; i < bytes.Length - 1; i++) actual.AddRange(reader.Feed(bytes.AsSpan(i, 1)));
        check(actual.Count == 2 && reader.PendingBytes > 0, "An incomplete active-file JSONL tail is retained across UTF-8 byte boundaries");
        actual.AddRange(reader.Feed(bytes.AsSpan(bytes.Length - 1)));
        check(actual.Count == 3 && reader.PendingBytes == 0 && actual[2] is TraceEvent last && last.CapturedAtMs < first.CapturedAtMs,
            "Continuous event sequence does not force capture timestamps to increase");
        check(actual[1] is TraceEvent hit && EvidenceJson.PythonEquals(hit.Data, data) && EvidenceJson.PythonEquals(hit.Source, source)
            && hit.ClientTickMs == 0 && TraceJsonl.Serialize(hit).Contains("\"rate\":-0.0", StringComparison.Ordinal),
            "Structured trace preserves wide identities, raw integers, signed zero and field presence");
        using TraceJsonlReader sharedReader = new();
        sharedReader.Feed(TraceJsonl.Encoding.GetBytes(TraceJsonl.Serialize(header)));
        TraceEvent Read(string fields, int sequence) => (TraceEvent)sharedReader.Feed(TraceJsonl.Encoding.GetBytes(
            "{\"seq\":" + sequence + ",\"captured_at_ms\":0,\"source\":{},\"type\":\"damage\",\"data\":" + fields + "}\n"))[0];
        var retained = Read("""{"label":"first","values":{"rate":-0.0},"b":2,"a":1,"b":3}""", 1);
        var updated = Read("""{"label":"second","values":{"rate":0.4},"b":4,"a":5}""", 2);
        var reordered = Read("""{"a":9,"b":8,"label":"third","values":{"rate":0.8}}""", 3);
        check(retained.Data.Fields.Keys.SequenceEqual(new[] { "label", "values", "b", "a" })
            && retained.Data.Get("b") is EvidenceInteger { Value: var lastWins } && lastWins == 3
            && reordered.Data.Fields.Keys.SequenceEqual(new[] { "a", "b", "label", "values" })
            && retained.Data.Get("label") is EvidenceText { Value: "first" } && updated.Data.Get("label") is EvidenceText { Value: "second" },
            "Shared JSONL parsing preserves per-event values, duplicate last-wins fields and each object's insertion order");
        var copy = (EvidenceObject)EvidenceJson.Clone(retained.Data);
        ((IDictionary<string, EvidenceValue>)((EvidenceObject)copy.Get("values")).Fields)["rate"] = new EvidenceReal(99);
        var protectedRate = ((EvidenceObject)retained.Data.Get("values")).Get("rate");
        var protectedWrite = false;
        try { ((IDictionary<string, EvidenceValue>)retained.Data.Fields)["a"] = new EvidenceInteger(99); }
        catch (Exception error) when (error is InvalidCastException or NotSupportedException) { protectedWrite = true; }
        check(protectedWrite && protectedRate is EvidenceReal { Value: var zero } && BitConverter.DoubleToInt64Bits(zero) == long.MinValue,
            "Read-only shared fields reject writes and editable clones cannot alter signed-zero evidence in retained events");
        var serialized = TraceJsonl.Serialize(retained);
        check(ReferenceEquals(TraceEventSnapshot.Capture(retained), retained)
            && ReferenceEquals(FrozenEvidence.Capture(retained.Data.Get("values")), retained.Data.Get("values")),
            "The trace snapshot boundary reuses parser-owned immutable roots and descendants without rebuilding dictionaries");
        var forgedPairs = new List<KeyValuePair<string, EvidenceValue>> { new("extra", EvidenceJson.Parse("{\"items\":[1]}")) };
        var attached = TraceEventSnapshot.Capture(retained with { Data = retained.Data with { SourcePairs = forgedPairs } });
        ((IList<EvidenceValue>)((EvidenceArray)((EvidenceObject)forgedPairs[0].Value).Get("items")).Items)[0] = new EvidenceInteger(99);
        forgedPairs.Clear();
        check(attached.Data.SourcePairs is { Count: 1 } savedPairs
            && ((EvidenceArray)((EvidenceObject)savedPairs[0].Value).Get("items")).Items[0] is EvidenceInteger { Value: var savedValue } && savedValue == 1,
            "Newly attached duplicate-pair evidence is detached recursively even when parsed object fields are protected");
        sharedReader.Dispose();
        check(serialized == TraceJsonl.Serialize(retained) && TraceJsonl.Parse(serialized, false) is TraceEvent detached
            && EvidenceJson.PythonEquals(detached.Data, retained.Data),
            "Disposing a JSONL reader releases its caches without invalidating previously returned events");
        EvidenceJson.ReadOnlyContext bounded = new();
        EvidenceObject? earliest = null, latest = null;
        for (var index = 0; index < 1100; index++)
        {
            latest = (EvidenceObject)bounded.Parse("{" + string.Join(",", Enumerable.Range(0, 8)
                .Select(field => $"\"field_{index}_{field}\":\"value_{index}_{field}\"")) + "}");
            earliest ??= latest;
        }
        bounded.Clear();
        check(earliest!.Get("field_0_0") is EvidenceText { Value: "value_0_0" }
            && latest!.Get("field_1099_7") is EvidenceText { Value: "value_1099_7" }
            && latest.Fields.Count == 8 && bounded.Strings.Count == 0,
            "Exhausting bounded string and field-shape caches preserves all later evidence and clearing caches preserves retained values");
        var next = header with { Volume = 2, PreviousVolume = new(1, "trace_part1.jsonl") };
        using MemoryStream volume = new();
        using (TraceJsonlWriter writer = new(volume, next, leaveOpen: true)) writer.Write(first with { Sequence = 8 });
        using TraceJsonlReader nextReader = new();
        check(nextReader.Feed(volume.ToArray()) is { Count: 2 } continuation && continuation[1] is TraceEvent { Sequence: 8 },
            "Continuous-volume framing retains sequence instead of resetting it");
        foreach (var json in new[]
        {
            """{"seq":true,"captured_at_ms":0,"source":{},"type":"damage","data":{}}""",
            """{"seq":0,"captured_at_ms":0,"source":{},"type":"damage","data":{}}""",
            """{"seq":1,"captured_at_ms":0,"source":{"owner_id":11},"type":"damage","data":{}}""",
            """{"seq":1,"captured_at_ms":0,"source":{"owner_id":"unknown"},"type":"damage","data":{}}""",
            """{"seq":1,"captured_at_ms":0,"source":{},"type":"damage","data":{"value":NaN}}""",
            """{"seq":1,"captured_at_ms":0,"source":{},"type":"damage","data":{"value":1e999}}""",
        })
        {
            try { TraceJsonl.Parse(json, header: false); throw new InvalidOperationException("Invalid trace accepted"); }
            catch (InvalidDataException) { check(true, "Invalid JSONL envelope or non-finite evidence is rejected"); }
        }
        try { reader.Feed(TraceJsonl.Encoding.GetBytes(TraceJsonl.Serialize(second))); throw new InvalidOperationException("Duplicate sequence accepted"); }
        catch (InvalidDataException) { check(true, "Repeated event sequence cannot silently enter the trace"); }
    }
}
