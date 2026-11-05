using System.Buffers.Binary;
using System.ComponentModel;
using System.Net;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace EndfieldLogs.Native.Processes;

public sealed record TcpProcessConnection(uint ProcessId, string LocalAddress, int LocalPort,
    string RemoteAddress, int RemotePort);

/// <summary>IPv4 owner-PID TCP table used to select the game's observed connection.</summary>
public static class TcpProcessConnections
{
    [SupportedOSPlatform("windows")]
    public static IReadOnlyList<TcpProcessConnection> Read()
    {
        uint length = 0;
        var result = GetExtendedTcpTable(null, ref length, false, 2, 5, 0); // AF_INET, TCP_TABLE_OWNER_PID_ALL
        for (var attempt = 0; attempt < 8; attempt++)
        {
            if (result != 122 && result != 0) throw new Win32Exception((int)result, "Could not read TCP process owners");
            var buffer = new byte[checked((int)length)];
            result = GetExtendedTcpTable(buffer, ref length, false, 2, 5, 0);
            if (result == 122) continue; // Connections can change between the size query and table copy.
            if (result != 0) throw new Win32Exception((int)result, "Could not read TCP process owners");
            return Parse(buffer);
        }
        throw new IOException("TCP process table changed repeatedly during enumeration");
    }

    public static IReadOnlyList<TcpProcessConnection> Parse(ReadOnlySpan<byte> table)
    {
        if (table.Length < 4) throw new InvalidDataException("TCP process table header is truncated");
        var count = BinaryPrimitives.ReadUInt32LittleEndian(table);
        if (count > (table.Length - 4) / 24) throw new InvalidDataException("TCP process table rows are truncated");
        List<TcpProcessConnection> rows = [];
        for (var index = 0; index < count; index++)
        {
            var row = table.Slice(4 + index * 24, 24);
            rows.Add(new(BinaryPrimitives.ReadUInt32LittleEndian(row[20..]), new IPAddress(row.Slice(4, 4)).ToString(),
                BinaryPrimitives.ReadUInt16BigEndian(row[8..]), new IPAddress(row.Slice(12, 4)).ToString(),
                BinaryPrimitives.ReadUInt16BigEndian(row[16..])));
        }
        return rows;
    }

    [DllImport("iphlpapi.dll")]
    private static extern uint GetExtendedTcpTable([Out] byte[]? table, ref uint size,
        [MarshalAs(UnmanagedType.Bool)] bool order, uint family, int tableClass, uint reserved);
}
