using System.Buffers.Binary;
using System.Net;
using EndfieldLogs.Core.Models;

namespace EndfieldLogs.Capture.Transport;

public static class PacketDecoder
{
    private sealed record Ipv4(byte[] Source, byte[] Destination, byte Protocol, int FragmentOffset, byte[] Payload);
    private static ushort U16(ReadOnlySpan<byte> data, int offset) => BinaryPrimitives.ReadUInt16BigEndian(data.Slice(offset, 2));

    // The reference's IPv4 parser accepts truncated payloads, IP options, and zero total length
    // (TCP offload), while a malformed TCP header remains undecoded bytes.
    private static Ipv4? Ip(ReadOnlySpan<byte> data)
    {
        if (data.Length < 20) return null;
        var header = (data[0] & 15)*4;
        if (header < 20) return null;
        var length = U16(data, 2);
        var end = length == 0 ? data.Length : Math.Min(length, data.Length);
        var payload = header >= end ? [] : data[header..end].ToArray();
        return new(data[12..16].ToArray(), data[16..20].ToArray(), data[9], U16(data, 6) & 8191, payload);
    }

    private static Ipv4? Ethernet(ReadOnlySpan<byte> data)
    {
        if (data.Length < 14) return null;
        var type = U16(data, 12);
        if (type <= 1500)
        {
            if (data[..5].SequenceEqual(new byte[] { 1,0,12,0,0 }) || data[..5].SequenceEqual(new byte[] { 3,0,12,0,0 }))
                return data.Length < 26 ? null : Ethernet(data[26..]);
            return null;
        }
        var start = 14;
        // Ethernet.__init__ retries undecoded bytes once, retaining the next type from
        // unpack(). This also exposes a second nested VLAN/MPLS stack in the reference.
        for (var pass = 0; pass < 2; pass++)
        {
            if (type is 0x8100 or 0x88a8 or 0x9100 or 0x9200)
            {
                for (var tag = 0; tag < 2; tag++)
                {
                    if (data.Length-start < 4) return null;
                    type = U16(data, start+2);
                    start += 4;
                    if (type != 0x8100) break;
                }
            }
            else if (type is 0x8847 or 0x8848)
            {
                for (var label = 0; label < 24; label++)
                {
                    if (data.Length-start < 4) return null;
                    var bottom = (data[start+2] & 1) != 0;
                    start += 4;
                    if (bottom) break;
                }
                // dpkt's MPLS heuristic only promotes a directly nested 0x45 IPv4 header.
                if (start >= data.Length) throw new IndexOutOfRangeException("index out of range");
                type = data[start] == 0x45 ? (ushort)0x0800 : (ushort)0;
            }
            if (type == 0x0800) return Ip(data[start..]);
            if (type is not (0x8100 or 0x88a8 or 0x9100 or 0x9200 or 0x8847 or 0x8848)) return null;
        }
        return null;
    }

    public static CapturedPacket? Decode(long timestampMs, byte[] data, string deviceName)
    {
        if (data.Length == 0) return null;
        var ip = Ethernet(data);
        if (ip is null && data[0] >> 4 == 4) ip = Ip(data);
        if (ip is null)
            foreach (var offset in new[] { 4, 14, 16 })
            {
                if (data.Length <= offset || data[offset] >> 4 != 4) continue;
                ip = Ip(data.AsSpan(offset));
                if (ip is not null) break;
            }
        if (ip is null || ip.Protocol != 6 || ip.FragmentOffset != 0 || ip.Payload.Length < 20) return null;
        var tcp = ip.Payload;
        var headerLength = (tcp[12] >> 4)*4;
        if (headerLength < 20 || headerLength >= tcp.Length) return null;
        return new(timestampMs, new(new IPAddress(ip.Source).ToString(), U16(tcp, 0)),
            new(new IPAddress(ip.Destination).ToString(), U16(tcp, 2)), BinaryPrimitives.ReadUInt32BigEndian(tcp.AsSpan(4, 4)),
            tcp[headerLength..], deviceName);
    }
}
