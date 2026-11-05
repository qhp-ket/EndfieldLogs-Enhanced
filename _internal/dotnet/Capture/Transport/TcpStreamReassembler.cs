namespace EndfieldLogs.Capture.Transport;

/// <summary>Preserves the reference's sequence and retransmission semantics.</summary>
public sealed class TcpStreamReassembler
{
    private readonly SortedDictionary<long, byte[]> segments = [];
    private long? nextSequence;

    public void Reset()
    {
        segments.Clear();
        nextSequence = null;
    }

    public (long Expected, long Lowest, long Missing)? GapState()
    {
        if (nextSequence is not long next || segments.Count == 0) return null;
        var lowest = segments.First().Key;
        return lowest <= next ? null : (next, lowest, lowest - next);
    }

    public IReadOnlyList<byte[]> Accept(long sequence, ReadOnlySpan<byte> payload)
    {
        if (payload.IsEmpty) return [];
        nextSequence ??= sequence;
        var next = nextSequence.Value;
        if (sequence + payload.Length <= next) return [];
        if (sequence < next)
        {
            payload = payload[checked((int)(next - sequence))..];
            sequence = next;
        }
        if (!segments.TryGetValue(sequence, out var existing) || payload.Length > existing.Length)
            segments[sequence] = payload.ToArray();
        List<byte[]> flushed = [];
        while (segments.Remove(next, out var chunk))
        {
            flushed.Add(chunk);
            next += chunk.Length;
        }
        nextSequence = next;
        return flushed;
    }
}
