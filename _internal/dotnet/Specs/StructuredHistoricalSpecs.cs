using System.Numerics;
using System.Text.Json;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredHistoricalSpecs
{
    internal static void Run(Action<bool, string> check)
    {
        var path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../Fixtures/trace-historical-contract.json"));
        var fixture = (EvidenceObject)EvidenceJson.Parse(File.ReadAllText(path));
        var timestamp = (long)((EvidenceInteger)fixture.Get("captured_at_ms")).Value;
        var old = StructuredDamageSpecs.Stream(); var typed = StructuredDamageSpecs.Stream();
        foreach (var stream in new[] { old, typed })
        {
            var index = 0;
            foreach (var line in ((EvidenceArray)fixture.Get("setup")).Items.Cast<EvidenceText>()) stream.Accept(++index, line.Value);
        }
        check(typed.Buffs.PendingRecord is not null, "Historical fixture begins with a pending BB window");
        var evidence = 2;
        foreach (var row in ((EvidenceArray)fixture.Get("observations")).Items.Cast<EvidenceObject>())
        {
            var text = ((EvidenceText)row.Get("line")).Value;
            var (kind, raw) = HistoricalEvidenceWire.Data(text) ?? throw new InvalidDataException("Missing historical event");
            check(kind == ((EvidenceText)row.Get("type")).Value, "Historical marker has its own family: " + kind);
            var projected = TraceValueProjection.Capture(raw);
            var data = ((EvidenceObject)projected.Value).Fields.ToDictionary(); data["legacy_layout"] = projected.Layout;
            var item = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(evidence - 1, timestamp, kind, new(data), new(new Dictionary<string, EvidenceValue>()))), header: false);
            check(TraceLegacyExporter.Lines(item, 0).Single() == text + "\n", "Independent historical export keeps fixed row bytes: " + kind);
            old.Accept(++evidence, text); typed.Accept(evidence, item);
            var oldHit = old.Packets.HitsBySequence[7]; var typedHit = typed.Packets.HitsBySequence[7];
            check(JsonSerializer.Serialize(oldHit.RawDamage) == JsonSerializer.Serialize(typedHit.RawDamage)
                && (oldHit.Baseline is null ? typedHit.Baseline is null : oldHit.Baseline.SequenceEqual(typedHit.Baseline!)),
                "Historical raw/baseline state matches the legacy reader after " + kind);
            check(JsonSerializer.Serialize(old.Buffs.PendingModifiers) == JsonSerializer.Serialize(typed.Buffs.PendingModifiers)
                && (old.Buffs.PendingRecord is null) == (typed.Buffs.PendingRecord is null),
                "Historical modifiers and pending window match the legacy reader after " + kind);
        }
        var hit = typed.Packets.HitsBySequence[7];
        check(hit.RawDamage!.Calculation == 123.45678901234567 && hit.RawDamage.AttackerZones.SequenceEqual(new double?[] { 1, null, -0d, .001 })
            && hit.Baseline![BigInteger.One] == 1.2345678901234567 && BitConverter.DoubleToInt64Bits(hit.Baseline[2]) == long.MinValue,
            "Historical numbers keep double precision, ordered last-wins attributes, unknown zones and signed zero");
        check(typed.Hits.Hits.Count == 1 && typed.Packets.HitsBySequence.Count == 1 && typed.Buffs.PendingRecord is null,
            "Orphan historical evidence does not create or bind another hit");
        check(typed.HasIdentityInference && typed.PartyActorIds.Count == 0 && typed.Loadouts.SquadActorKeys.Count == 0,
            "Inferred identities stay diagnostic and grant no actor authority");
        check(typed.TimerObservedTimes.Count == 1 && typed.TimerObservedTimes[8] == timestamp
            && typed.Timers.GameElapsedMs is null && typed.Timers.OfficialElapsedMs is null,
            "Legacy timer ticks remain observations without inferred authoritative elapsed time");
        foreach (var row in ((EvidenceArray)fixture.Get("observations")).Items.Cast<EvidenceObject>()
            .Where(row => row.Get("type") is EvidenceText { Value: "identity_inference" or "clock_tick" }))
        {
            var line = ((EvidenceText)row.Get("line")).Value;
            var before = StructuredDamageSpecs.Stream(); var after = StructuredDamageSpecs.Stream();
            var start = ((EvidenceText)((EvidenceArray)fixture.Get("setup")).Items[1]).Value;
            before.Accept(1, start); after.Accept(1, start);
            var (kind, raw) = HistoricalEvidenceWire.Data(line)!.Value;
            var projected = TraceValueProjection.Capture(raw);
            before.Accept(2, line); after.Accept(2, new TraceEvent(1, timestamp, kind, (EvidenceObject)projected.Value, new(new Dictionary<string, EvidenceValue>())));
            check(before.Buffs.PendingRecord is null && after.Buffs.PendingRecord is null,
                "Historical diagnostic closes the pending BB window: " + kind);
        }
    }
}
