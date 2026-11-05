using System.Buffers.Binary;

namespace EndfieldLogs.Capture.Framing;

public sealed record SessionFrame(byte[] Head, byte[] Body)
{
    public int HeadLength => Head.Length;
}
public sealed record MergedSessionFrame(int Offset, SessionFrame Frame);

public sealed class SessionFrameBuffer
{
    private readonly List<byte> buffer = [];
    public int Count => buffer.Count;
    public byte[] Pending => buffer.ToArray();
    public void Append(byte[] data) => buffer.AddRange(data);
    public void Reset() => buffer.Clear();

    public SessionFrame? Pop()
    {
        if (buffer.Count < 3) return null;
        var headLength = buffer[0];
        var bodyLength = buffer[1] | (buffer[2] << 8);
        var end = 3+headLength+bodyLength;
        if (end > buffer.Count) return null;
        var head = buffer.GetRange(3, headLength).ToArray();
        var body = buffer.GetRange(3+headLength, bodyLength).ToArray();
        buffer.RemoveRange(0, end);
        return new(head, body);
    }

    public static IEnumerable<MergedSessionFrame> Merged(byte[] data)
    {
        var offset = 0;
        while (offset+3 <= data.Length)
        {
            var headLength = data[offset];
            var bodyLength = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(offset+1, 2));
            var start = offset+3;
            var end = start+headLength+bodyLength;
            if (end > data.Length) yield break;
            yield return new(offset, new(data[start..(start+headLength)], data[(start+headLength)..end]));
            offset = end;
        }
    }
}
