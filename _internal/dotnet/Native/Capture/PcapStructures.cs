using System.Runtime.InteropServices;

namespace EndfieldLogs.Native.Capture;

[StructLayout(LayoutKind.Sequential)]
public struct PcapPacketHeader
{
    // Win32 long remains 32 bits on x64.
    public int Seconds;
    public int Microseconds;
    public uint CapturedLength;
    public uint OriginalLength;
    public readonly long TimestampMs => (long)(Seconds*1000d + Microseconds/1000d);
}

[StructLayout(LayoutKind.Sequential)]
public struct PcapStatistics
{
    public uint Received;
    public uint Dropped;
    public uint InterfaceDropped;
}

[StructLayout(LayoutKind.Sequential)]
public struct PcapDevice
{
    public nint Next;
    public nint Name;
    public nint Description;
    public nint Addresses;
    public uint Flags;
}

[StructLayout(LayoutKind.Sequential)]
public struct PcapAddress
{
    public nint Next;
    public nint Address;
    public nint Netmask;
    public nint BroadcastAddress;
    public nint DestinationAddress;
}

[StructLayout(LayoutKind.Sequential)]
public struct BpfProgram
{
    public uint Length;
    public nint Instructions;
}
