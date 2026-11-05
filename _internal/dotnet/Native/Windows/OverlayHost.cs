using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace EndfieldLogs.Native.Windows;

/// <summary>A Win32 window owned by the dispatcher thread, without WPF's layered-window compositor.</summary>
[SupportedOSPlatform("windows")]
public sealed class OverlayHost : IDisposable
{
    public delegate nint MessageHandler(nint window, int message, nint wParam, nint lParam, ref bool handled);
    private delegate nint WindowProcedure(nint window, uint message, nint wParam, nint lParam);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct WindowClass
    {
        public uint Style; public WindowProcedure Procedure; public int ClassExtra, WindowExtra;
        public nint Instance, Icon, Cursor, Background;
        [MarshalAs(UnmanagedType.LPWStr)] public string? Menu;
        [MarshalAs(UnmanagedType.LPWStr)] public string Name;
    }
    [StructLayout(LayoutKind.Sequential)] private struct Margins { public int Left, Right, Top, Bottom; }
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern ushort RegisterClassW(ref WindowClass value);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint CreateWindowExW(uint extended, string name, string title, uint style, int x, int y, int width, int height, nint parent, nint menu, nint instance, nint parameter);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern nint DefWindowProcW(nint window, uint message, nint wParam, nint lParam);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DestroyWindow(nint window);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern nint GetModuleHandleW(string? name);
    [DllImport("dwmapi.dll")] private static extern int DwmExtendFrameIntoClientArea(nint window, ref Margins margins);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetLayeredWindowAttributes(nint window, uint color, byte alpha, uint flags);
    private static readonly WindowProcedure procedure = Dispatch;
    private static readonly Dictionary<nint, OverlayHost> windows = [];
    private static readonly string className = "EndfieldLogs.NativeOverlay." + Environment.ProcessId;
    private static bool registered;
    public nint Handle { get; private set; }
    public MessageHandler? Message { get; set; }

    public OverlayHost(string title)
    {
        var instance = GetModuleHandleW(null);
        lock (windows)
        {
            if (!registered)
            {
                WindowClass value = new() { Name = className, Procedure = procedure, Instance = instance };
                if (RegisterClassW(ref value) == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
                registered = true;
            }
            Handle = CreateWindowExW(0x00080008 | (uint)WindowInterop.NoActivate, className, title, 0x80000000, 0, 0, 1, 1, 0, 0, instance, 0);
            if (Handle == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            windows.Add(Handle, this);
        }
        try
        {
            Margins margins = new() { Left = -1, Right = -1, Top = -1, Bottom = -1 };
            Marshal.ThrowExceptionForHR(DwmExtendFrameIntoClientArea(Handle, ref margins));
            SetOpacity(1);
        }
        catch { Dispose(); throw; }
    }
    public void SetOpacity(double opacity)
    {
        if (!SetLayeredWindowAttributes(Handle, 0, (byte)Math.Clamp((int)Math.Round(opacity * 255), 0, 255), 2))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    private static nint Dispatch(nint window, uint message, nint wParam, nint lParam)
    {
        OverlayHost? host; lock (windows) windows.TryGetValue(window, out host);
        if (host?.Message is { } callback)
        {
            var handled = false; var result = callback(window, unchecked((int)message), wParam, lParam, ref handled);
            if (handled) return result;
        }
        return message == 0x14 ? 1 : DefWindowProcW(window, message, wParam, lParam);
    }
    public void Dispose()
    {
        if (Handle == 0) return;
        var handle = Handle; Message = null;
        lock (windows) windows.Remove(handle);
        DestroyWindow(handle); Handle = 0;
    }
}
