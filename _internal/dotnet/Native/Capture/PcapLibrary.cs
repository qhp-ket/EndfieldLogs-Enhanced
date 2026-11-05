using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Microsoft.Win32.SafeHandles;

namespace EndfieldLogs.Native.Capture;

public sealed record DeviceInfo(string Name, string? Description, IReadOnlyList<string> Ipv4Addresses, uint Flags);
public sealed record NativePacket(long TimestampMs, byte[] Data);

[SupportedOSPlatform("windows")]
public sealed class PcapLibrary : IDisposable
{
    private readonly object lifetime = new();
    private readonly LibraryHandle library;
    private readonly FindDevices findDevices;
    private readonly FreeDevices freeDevices;
    private readonly Create create;
    private readonly OpenLive openLive;
    private readonly SetValue snapLength, promiscuous, timeout, bufferSize;
    private readonly Activate activate;
    private readonly Compile compile;
    private readonly SetFilter setFilter;
    private readonly FreeCode freeCode;
    private readonly Close close;
    private readonly Next next;
    private readonly Stats stats;
    private readonly GetError getError;

    public PcapLibrary()
    {
        var system = Environment.GetFolderPath(Environment.SpecialFolder.System);
        var path = new[] { Path.Combine(system, "Npcap", "wpcap.dll"), Path.Combine(system, "wpcap.dll") }
            .FirstOrDefault(File.Exists) ?? throw new DllNotFoundException("Npcap wpcap.dll is not installed");
        library = new(LoadLibraryEx(path, 0, 0x100|0x1000));
        if (library.IsInvalid) throw new Win32Exception(Marshal.GetLastPInvokeError());
        try
        {
            findDevices=Export<FindDevices>("pcap_findalldevs"); freeDevices=Export<FreeDevices>("pcap_freealldevs");
            create=Export<Create>("pcap_create"); openLive=Export<OpenLive>("pcap_open_live");
            snapLength=Export<SetValue>("pcap_set_snaplen"); promiscuous=Export<SetValue>("pcap_set_promisc");
            timeout=Export<SetValue>("pcap_set_timeout"); bufferSize=Export<SetValue>("pcap_set_buffer_size");
            activate=Export<Activate>("pcap_activate"); compile=Export<Compile>("pcap_compile");
            setFilter=Export<SetFilter>("pcap_setfilter"); freeCode=Export<FreeCode>("pcap_freecode");
            close=Export<Close>("pcap_close"); next=Export<Next>("pcap_next_ex");
            stats=Export<Stats>("pcap_stats"); getError=Export<GetError>("pcap_geterr");
        }
        catch { library.Dispose(); throw; }
    }

    private T Export<T>(string name) where T : Delegate =>
        Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library.DangerousGetHandle(), name));
    private static string Text(nint value) => Marshal.PtrToStringUTF8(value) ?? string.Empty;
    private string Error(nint handle) => Text(getError(handle));

    public IReadOnlyList<DeviceInfo> ListDevices()
    {
        lock (lifetime) return ListDevicesCore();
    }

    private IReadOnlyList<DeviceInfo> ListDevicesCore()
    {
        ObjectDisposedException.ThrowIf(library.IsClosed, this);
        byte[] error = new byte[256];
        if (findDevices(out var devices, error) != 0)
            throw new IOException(System.Text.Encoding.UTF8.GetString(error).TrimEnd('\0'));
        List<DeviceInfo> result = [];
        try
        {
            for (var pointer = devices; pointer != 0;)
            {
                var device = Marshal.PtrToStructure<PcapDevice>(pointer);
                List<string> addresses = [];
                for (var node = device.Addresses; node != 0;)
                {
                    var address = Marshal.PtrToStructure<PcapAddress>(node);
                    if (address.Address != 0 && Marshal.ReadInt16(address.Address) == 2)
                    {
                        byte[] bytes = new byte[4];
                        Marshal.Copy(address.Address+4, bytes, 0, bytes.Length);
                        addresses.Add(new System.Net.IPAddress(bytes).ToString());
                    }
                    node = address.Next;
                }
                result.Add(new(Text(device.Name), device.Description == 0 ? null : Text(device.Description), addresses, device.Flags));
                pointer = device.Next;
            }
        }
        finally { freeDevices(devices); }
        return result;
    }

    public PcapHandle Open(string name, string filter)
    {
        lock (lifetime) return OpenCore(name, filter);
    }

    private PcapHandle OpenCore(string name, string filter)
    {
        ObjectDisposedException.ThrowIf(library.IsClosed, this);
        try { return OpenActivated(name, filter); }
        catch (Exception activationError) when (activationError is IOException)
        {
            byte[] error = new byte[256];
            var pointer = openLive(name, 65535, 0, 100, error);
            if (pointer == 0) throw new IOException(System.Text.Encoding.UTF8.GetString(error).TrimEnd('\0'), activationError);
            var handle = new PcapHandle(pointer, library, close);
            try { ApplyFilter(pointer, filter); return handle; }
            catch { handle.Dispose(); throw; }
        }
    }

    private PcapHandle OpenActivated(string name, string filter)
    {
        byte[] error = new byte[256];
        var pointer = create(name, error);
        if (pointer == 0) throw new IOException(System.Text.Encoding.UTF8.GetString(error).TrimEnd('\0'));
        var handle = new PcapHandle(pointer, library, close);
        try
        {
            Check(pointer, snapLength(pointer,65535), "pcap_set_snaplen");
            Check(pointer, promiscuous(pointer,0), "pcap_set_promisc");
            Check(pointer, timeout(pointer,100), "pcap_set_timeout");
            Check(pointer, bufferSize(pointer,32*1024*1024), "pcap_set_buffer_size");
            Check(pointer, activate(pointer), "pcap_activate");
            ApplyFilter(pointer,filter);
            return handle;
        }
        catch { handle.Dispose(); throw; }
    }

    private void Check(nint pointer, int result, string operation)
    {
        if (result != 0) throw new IOException($"{operation}: {Error(pointer)} (code {result})");
    }

    private void ApplyFilter(nint pointer, string filter)
    {
        Check(pointer, compile(pointer,out var program,filter,1,uint.MaxValue), "pcap_compile");
        try { Check(pointer,setFilter(pointer,ref program), "pcap_setfilter"); }
        finally { freeCode(ref program); }
    }

    public NativePacket? Read(PcapHandle handle)
    {
        var held = false;
        try
        {
            handle.DangerousAddRef(ref held);
            var pointer = handle.DangerousGetHandle();
            var code = next(pointer,out var headerPointer,out var dataPointer);
            if (code == 0) return null;
            if (code < 0) throw new IOException($"pcap_next_ex failed with code {code}: {Error(pointer)}");
            var header = Marshal.PtrToStructure<PcapPacketHeader>(headerPointer);
            var data = new byte[checked((int)header.CapturedLength)];
            Marshal.Copy(dataPointer,data,0,data.Length);
            return new(header.TimestampMs,data);
        }
        finally { if (held) handle.DangerousRelease(); }
    }

    public PcapStatistics? Statistics(PcapHandle handle)
    {
        var held = false;
        try
        {
            handle.DangerousAddRef(ref held);
            return stats(handle.DangerousGetHandle(),out var result) == 0 ? result : null;
        }
        finally { if (held) handle.DangerousRelease(); }
    }

    public void Dispose()
    {
        lock (lifetime) library.Dispose();
    }

    [DllImport("kernel32.dll", EntryPoint="LoadLibraryExW", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern nint LoadLibraryEx(string name, nint file, uint flags);
    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FreeLibrary(nint module);
    internal sealed class LibraryHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        public LibraryHandle(nint value) : base(true) => SetHandle(value);
        protected override bool ReleaseHandle() => FreeLibrary(handle);
    }
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int FindDevices(out nint devices, [Out] byte[] error);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void FreeDevices(nint devices);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint Create([MarshalAs(UnmanagedType.LPUTF8Str)] string name, [Out] byte[] error);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint OpenLive([MarshalAs(UnmanagedType.LPUTF8Str)] string name,int snap,int promiscuous,int timeout,[Out] byte[] error);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int SetValue(nint handle,int value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Activate(nint handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Compile(nint handle,out BpfProgram program,[MarshalAs(UnmanagedType.LPUTF8Str)] string filter,int optimize,uint netmask);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int SetFilter(nint handle,ref BpfProgram program);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void FreeCode(ref BpfProgram program);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] internal delegate void Close(nint handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Next(nint handle,out nint header,out nint data);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Stats(nint handle,out PcapStatistics stats);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint GetError(nint handle);
}

[SupportedOSPlatform("windows")]
public sealed class PcapHandle : SafeHandleZeroOrMinusOneIsInvalid
{
    private readonly PcapLibrary.LibraryHandle library;
    private readonly PcapLibrary.Close close;
    internal PcapHandle(nint value, PcapLibrary.LibraryHandle library, PcapLibrary.Close close) : base(true)
    {
        var held = false;
        library.DangerousAddRef(ref held);
        this.library = library;
        this.close = close;
        SetHandle(value);
    }
    protected override bool ReleaseHandle()
    {
        try { close(handle); return true; }
        finally { library.DangerousRelease(); }
    }
}
