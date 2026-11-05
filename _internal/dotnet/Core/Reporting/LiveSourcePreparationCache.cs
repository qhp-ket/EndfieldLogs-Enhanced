using System.Runtime.CompilerServices;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Summary annotations for immutable BUFF projections without dynamic source events.</summary>
internal sealed class LiveSourcePreparationCache
{
    private sealed record Entry(long? ModifierTime, EvidenceObject Record);
    private readonly ConditionalWeakTable<EvidenceObject, Entry> entries = new();
    private static readonly EvidenceArray EmptyEvents = (EvidenceArray)FrozenEvidence.Capture(new EvidenceArray([]));

    internal EvidenceObject Prepare(EvidenceObject source, long? modifierTime)
    {
        var frozen = FrozenEvidence.IsFrozenRoot(source);
        if (frozen && entries.TryGetValue(source, out var previous) && previous.ModifierTime == modifierTime)
            return previous.Record;
        var fields = new Dictionary<string, EvidenceValue>(source.Fields, StringComparer.Ordinal)
            { ["dynamic_bb_events"] = EmptyEvents };
        if (modifierTime is { } stamp) fields["packet_modifier_last_seen_ts_ms"] = new EvidenceInteger(stamp);
        var record = new EvidenceObject(fields) { SourcePairs = source.SourcePairs };
        var prepared = (EvidenceObject)(frozen ? FrozenEvidence.TakeOwnership(record) : FrozenEvidence.Capture(record));
        // Only protected inputs can use identity. Mutable public inputs always take a fresh snapshot.
        if (frozen) { entries.Remove(source); entries.Add(source, new(modifierTime, prepared)); }
        return prepared;
    }
}
