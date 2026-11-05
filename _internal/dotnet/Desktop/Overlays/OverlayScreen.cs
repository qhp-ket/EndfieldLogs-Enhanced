using System.Runtime.InteropServices;
using System.Windows;
using EndfieldLogs.Native.Windows;

namespace EndfieldLogs.Desktop.Overlays;

internal static class OverlayScreen
{
    [StructLayout(LayoutKind.Sequential)] private struct MonitorInfo { internal int Size; internal WindowRectangle Monitor, Work; internal int Flags; }
    [DllImport("user32.dll")] private static extern nint MonitorFromWindow(nint window, int flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetMonitorInfo(nint monitor, ref MonitorInfo info);
    internal static Rect WorkArea(nint handle, double scale)
    {
        var info = new MonitorInfo { Size = Marshal.SizeOf<MonitorInfo>() };
        if (handle == 0 || !GetMonitorInfo(MonitorFromWindow(handle, 2), ref info)) return SystemParameters.WorkArea;
        return new(info.Work.Left / scale, info.Work.Top / scale, (info.Work.Right - info.Work.Left) / scale, (info.Work.Bottom - info.Work.Top) / scale);
    }
}
