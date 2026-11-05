using System.Numerics;

namespace EndfieldLogs.Capture.Framing;

public sealed record MultiPackKey(string Direction, BigInteger MessageId, BigInteger BaseSequenceId);
public sealed class PendingMultiPack(BigInteger total, SessionHead head, long firstTimestampMs)
{
    public BigInteger TotalPackCount { get; } = total;
    public SessionHead Head { get; } = head;
    public Dictionary<BigInteger, byte[]> Parts { get; } = [];
    public long FirstTimestampMs { get; } = firstTimestampMs;
    public long LastTimestampMs { get; internal set; } = firstTimestampMs;
}
public sealed record AssembledMessage(SessionHead Head, byte[] Body, bool AlreadyDecompressed);
public sealed record MultiPackProgress(MultiPackKey Key, BigInteger SequenceId, BigInteger TotalPackCount,
    BigInteger CurrentPackIndex, IReadOnlyList<BigInteger> ReceivedIndexes, long TimestampMs);

/// <summary>One ordered session owns this state. Parts use the reference's per-part decompression.</summary>
public sealed class MultiPackAssembler(Action<MultiPackProgress>? onPending=null)
{
    public Dictionary<MultiPackKey, PendingMultiPack> Pending { get; } = [];

    public AssembledMessage? Assemble(string direction, SessionHead head, byte[] body, long timestampMs)
    {
        var total = head.TotalPackCount is { IsZero:false } count ? count : BigInteger.One;
        if (total <= 1) return new(head, body, false);
        var index = head.CurrentPackIndex ?? BigInteger.Zero;
        var sequence = head.DownSequenceId ?? head.UpSequenceId ?? BigInteger.Zero;
        if (sequence <= 0) return null;
        MultiPackKey key = new(direction, head.MessageId ?? BigInteger.Zero, sequence-index);
        if (!Pending.TryGetValue(key, out var state)) Pending[key] = state = new(total, head, timestampMs);
        state.Parts[index] = SessionBodyCodec.Decode(head, body);
        state.LastTimestampMs = timestampMs;
        if (state.Parts.Count < total)
        {
            onPending?.Invoke(new(key, sequence, total, index, state.Parts.Keys.Order().ToArray(), timestampMs));
            return null;
        }
        if (state.Parts.Count != total) return null;
        using MemoryStream combined = new();
        for (BigInteger part = 0; part < total; part++)
            if (state.Parts.TryGetValue(part, out var bytes)) combined.Write(bytes);
        Pending.Remove(key);
        return new(state.Head with { IsCompressed=false }, combined.ToArray(), true);
    }

    public void Reset() => Pending.Clear();
}
