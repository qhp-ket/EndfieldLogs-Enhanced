using System.Runtime.InteropServices;

namespace EndfieldLogs.Native.Windows;

/// <summary>Optional WGC session options without raising the Windows 10 SDK baseline.</summary>
public static unsafe class CaptureSessionOptions
{
    // IGraphicsCaptureSession3 derives from IInspectable: get/put_IsBorderRequired
    // follow its six slots. WinRT Boolean is a one-byte value.
    private static readonly Guid Session3 = new("f2cdd966-22ae-5ea1-9596-3a289344c3be");

    public static bool TryDisableBorder(nint session)
    {
        var status = Marshal.QueryInterface(session, in Session3, out var options);
        if (status == unchecked((int)0x80004002)) return false; // Older Windows: E_NOINTERFACE.
        Marshal.ThrowExceptionForHR(status);
        try
        {
            Marshal.ThrowExceptionForHR(((delegate* unmanaged[Stdcall]<nint, byte, int>)(*(nint**)options)[7])(options, 0));
            return true;
        }
        finally { Marshal.Release(options); }
    }
}
