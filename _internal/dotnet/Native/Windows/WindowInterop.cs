using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace EndfieldLogs.Native.Windows;

[SupportedOSPlatform("windows")]
public static partial class WindowInterop
{
    public const int ExtendedStyle = -20;
    public const long Transparent = 0x20;
    public const long NoActivate = 0x08000000;
    public const long ToolWindow = 0x80;

    [LibraryImport("user32.dll", EntryPoint="GetWindowLongPtrW", SetLastError=true)]
    public static partial nint GetWindowLong(nint handle, int index);

    [LibraryImport("user32.dll", EntryPoint="SetWindowLongPtrW", SetLastError=true)]
    private static partial nint SetWindowLong(nint handle, int index, nint value);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool IsWindowVisible(nint handle);

    [LibraryImport("user32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetWindowRect(nint handle, out WindowRectangle rectangle);

    [LibraryImport("user32.dll")]
    public static partial uint GetDpiForWindow(nint handle);

    public static void ConfigureOverlay(nint handle, bool clickThrough)
    {
        var styles = (long)GetWindowLong(handle, ExtendedStyle);
        // Keep the HWND eligible for external window capture.
        styles &= ~ToolWindow;
        styles |= NoActivate;
        styles = clickThrough ? styles|Transparent : styles&~Transparent;
        Marshal.SetLastPInvokeError(0);
        var previous = SetWindowLong(handle, ExtendedStyle, (nint)styles);
        var error = Marshal.GetLastPInvokeError();
        if (previous == 0 && error != 0) throw new Win32Exception(error);
    }
}

[StructLayout(LayoutKind.Sequential)]
public struct WindowRectangle
{
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}
