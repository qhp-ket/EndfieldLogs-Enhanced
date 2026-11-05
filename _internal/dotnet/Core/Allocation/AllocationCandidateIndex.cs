using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

internal sealed class TemporalCandidates<T>
{
    internal sealed record Entry(BigInteger? Start, int Order, BigInteger? End, T Value);
    private readonly Entry[] rows;
    private readonly SortedDictionary<int, T> active = [];
    private readonly PriorityQueue<int, (BigInteger End, int Order)> expiry = new();
    private BigInteger? lastStamp;
    private int cursor;
    public TemporalCandidates(IEnumerable<Entry> entries) => rows = entries.OrderBy(row => row.Start).ThenBy(row => row.Order).ToArray();
    public IReadOnlyList<T> At(BigInteger stamp)
    {
        if (lastStamp is null || stamp < lastStamp)
        { cursor = 0; active.Clear(); expiry.Clear(); }
        while (cursor < rows.Length && (rows[cursor].Start is null || rows[cursor].Start <= stamp))
        {
            var row = rows[cursor++];
            if (row.End is null || row.End >= stamp)
            {
                active[row.Order] = row.Value;
                if (row.End is BigInteger end) expiry.Enqueue(row.Order, (end, row.Order));
            }
        }
        while (expiry.TryPeek(out var order, out var end) && end.End < stamp) { expiry.Dequeue(); active.Remove(order); }
        lastStamp = stamp;
        return active.Values.ToArray();
    }
}

/// <summary>Inclusive time candidates only. The allocator still checks identity, line and packet evidence.</summary>
public sealed class AllocationConditionIndex
{
    private readonly Dictionary<string, TemporalCandidates<EvidenceObject>> groups = new(StringComparer.Ordinal);
    private static BigInteger? Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceReal real => TraceFields.OptionalInteger(real.Value),
        EvidenceText text => TraceFields.OptionalInteger(text.Value),
        _ => null,
    };
    public AllocationConditionIndex(IReadOnlyList<EvidenceObject>? records)
    {
        Dictionary<string, List<TemporalCandidates<EvidenceObject>.Entry>> entries = new(StringComparer.Ordinal);
        foreach (var (record, order) in (records ?? []).Select((record, order) => (record, order)))
        {
            if (Integer(record.Get("ts_ms")) is not BigInteger start) continue;
            var end = Integer(record.Get("end_ts_ms"));
            if (Integer(record.Get("raw_duration_ms")) is BigInteger duration) end = end is null ? start + duration : BigInteger.Min(end.Value, start + duration);
            // Keep the boundary inclusive: packet evaluation resolves ordering within this millisecond.
            if (Integer(record.Get("snapshot_end_ts_ms")) is BigInteger snapshotEnd) end = end is null ? snapshotEnd : BigInteger.Min(end.Value, snapshotEnd);
            var target = CatalogValues.Text(CatalogValues.Or(record.Get("target_enemy_key"), record.Get("target_character_key"), new EvidenceText("")));
            if (!entries.TryGetValue(target, out var rows)) entries[target] = rows = [];
            rows.Add(new(start, order, end, record));
        }
        foreach (var (key, rows) in entries) groups[key] = new(rows);
    }
    public IReadOnlyList<EvidenceObject> At(string target, BigInteger stamp) => groups.TryGetValue(target, out var group) ? group.At(stamp) : [];
}

public sealed class AllocationWindowIndex
{
    private readonly TemporalCandidates<int> windows;
    public AllocationWindowIndex(IReadOnlyList<EvidenceObject> values) => windows = new(values.Select((window, order) =>
        new TemporalCandidates<int>.Entry((window.Get("start_ts_ms") as EvidenceInteger)?.Value, order,
            (window.Get("end_ts_ms") as EvidenceInteger)?.Value, order)));
    public IReadOnlyList<int> At(BigInteger stamp) => windows.At(stamp);
}
