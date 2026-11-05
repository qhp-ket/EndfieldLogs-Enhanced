using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Microsoft.Win32.SafeHandles;

namespace EndfieldLogs.Native.Cryptography;

public sealed class SrsaBridgeException(string message, Exception? inner=null) : Exception(message, inner);

[SupportedOSPlatform("windows")]
public sealed class SrsaBridge : IDisposable
{
    private const ulong ReturnMask = 0x0f91a4399a0, SetMask = 0x971ab5c8ff;
    private const ulong MinimumHandle = 0x100000;
    private const int MaximumLength = 0x100000;
    private readonly object gate = new();
    private readonly LibraryHandle library;
    private readonly GetVersion getVersion;
    private readonly SetCode setCode;
    private readonly RemoveCode removeCode;

    public SrsaBridge(string directory)
    {
        var path = Path.Combine(Path.GetFullPath(directory.Trim('"').Trim('\'')), "GameAssembly.dll");
        if (!File.Exists(path)) throw new SrsaBridgeException("GameAssembly.dll not found: "+path);
        library = new(LoadLibraryEx(path, 0, 0x100|0x1000));
        if (library.IsInvalid)
        {
            var error = new Win32Exception(Marshal.GetLastPInvokeError());
            library.Dispose();
            throw new SrsaBridgeException("Could not load "+path+": "+error.Message, error);
        }
        try
        {
            getVersion=Export<GetVersion>("mono_method_h_get_ver");
            _=Export<GetCode>("mono_method_h_get_code");
            setCode=Export<SetCode>("mono_method_h_set_code");
            removeCode=Export<RemoveCode>("mono_method_h_remove_code");
        }
        catch { library.Dispose(); throw; }
    }

    private T Export<T>(string name) where T : Delegate =>
        Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library.DangerousGetHandle(), name));

    public ulong Version
    {
        get { lock (gate) { ObjectDisposedException.ThrowIf(library.IsClosed,this); return getVersion(); } }
    }

    public byte[] DecryptLoginBody(byte[] encrypted)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(library.IsClosed,this);
            var pinned = GCHandle.Alloc(encrypted, GCHandleType.Pinned);
            try
            {
                var pointer = pinned.AddrOfPinnedObject();
                if (pointer == 0) throw new SrsaBridgeException("decrypt ptr is null");
                var handle = setCode(unchecked((ulong)pointer)^SetMask);
                if (handle < MinimumHandle) throw new SrsaBridgeException("mono_method_h_set_code failed code="+handle);
                try
                {
                    var decoded = unchecked((nint)(handle^ReturnMask));
                    var length = Marshal.ReadInt32(decoded);
                    if (length < 0 || length > MaximumLength) throw new SrsaBridgeException("decrypt out_len invalid: "+length);
                    byte[] output = new byte[length];
                    Marshal.Copy(decoded+4,output,0,length);
                    return output;
                }
                finally { removeCode(handle); }
            }
            finally { pinned.Free(); }
        }
    }

    public void Dispose() { lock (gate) library.Dispose(); }

    [DllImport("kernel32.dll", EntryPoint="LoadLibraryExW", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern nint LoadLibraryEx(string name, nint file, uint flags);
    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FreeLibrary(nint module);
    private sealed class LibraryHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        public LibraryHandle(nint value) : base(true) => SetHandle(value);
        protected override bool ReleaseHandle() => FreeLibrary(handle);
    }
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate ulong GetVersion();
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate ulong GetCode(ulong value, uint code);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate ulong SetCode(ulong pointer);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] private delegate void RemoveCode(ulong handle);
}
