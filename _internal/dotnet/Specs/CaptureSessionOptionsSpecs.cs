using System.Runtime.InteropServices;
using EndfieldLogs.Native.Windows;

internal static class CaptureSessionOptionsSpecs
{
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate int Query(nint self, in Guid iid, out nint result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate uint Release(nint self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate int SetBorder(nint self, byte value);

    public static void Run(Action<bool, string> check)
    {
        var table = Marshal.AllocHGlobal(8 * nint.Size);
        var instance = Marshal.AllocHGlobal(nint.Size);
        var supported = true; var calls = 0; var releases = 0; var fail = false;
        byte? border = null;
        Query query = (nint self, in Guid iid, out nint result) =>
        {
            result = supported ? self : 0;
            return supported && iid == new Guid("f2cdd966-22ae-5ea1-9596-3a289344c3be")
                ? 0 : unchecked((int)0x80004002);
        };
        Release release = _ => { releases++; return 1; };
        SetBorder setter = (_, value) => { calls++; border = value; return fail ? unchecked((int)0x80070005) : 0; };
        try
        {
            for (var i = 0; i < 8; i++) Marshal.WriteIntPtr(table, i * nint.Size, 0);
            Marshal.WriteIntPtr(table, Marshal.GetFunctionPointerForDelegate(query));
            Marshal.WriteIntPtr(table, 2 * nint.Size, Marshal.GetFunctionPointerForDelegate(release));
            Marshal.WriteIntPtr(table, 7 * nint.Size, Marshal.GetFunctionPointerForDelegate(setter));
            Marshal.WriteIntPtr(instance, table);
            check(CaptureSessionOptions.TryDisableBorder(instance) && border == 0 && calls == 1 && releases == 1,
                "WGC disables its colored border through the correct optional COM interface and releases it");
            check(CaptureSessionOptions.TryDisableBorder(instance) && calls == 2 && releases == 2,
                "A replacement capture session applies the border option again");
            supported = false;
            check(!CaptureSessionOptions.TryDisableBorder(instance) && calls == 2 && releases == 2,
                "Windows without the optional border interface retains capture support");
            supported = true; fail = true;
            var rejected = false;
            try { CaptureSessionOptions.TryDisableBorder(instance); }
            catch (UnauthorizedAccessException) { rejected = true; }
            check(rejected && releases == 3, "Border option errors propagate and release the native interface");
        }
        finally
        {
            GC.KeepAlive(query); GC.KeepAlive(release); GC.KeepAlive(setter);
            Marshal.FreeHGlobal(instance); Marshal.FreeHGlobal(table);
        }
    }
}
