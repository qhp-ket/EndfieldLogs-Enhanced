using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using EndfieldLogs.Native.Input;

namespace EndfieldLogs.Native.Windows;

public readonly record struct ClientPixels(int X, int Y, int Width, int Height);

/// <summary>Visible top-level windows matched by executable identity, with physical-pixel client geometry.</summary>
[SupportedOSPlatform("windows")]
public sealed class GameWindows(string executable)
{
    private readonly GameForeground identity = new(executable);
    public (IReadOnlyList<long> Windows, long? Foreground) Discover()
    {
        List<long> windows = [];
        EnumWindows((window, _) =>
        {
            if (IsWindowVisible(window) && GetClientRect(window, out var client) && client.Right > 0 && client.Bottom > 0
                && identity.IsTarget(window)) windows.Add(window);
            return true;
        }, 0);
        var foreground = GameForeground.GetForegroundWindow();
        return (windows, windows.Contains(foreground) ? (long?)foreground : null);
    }
    public static ClientPixels ClientInFrame(nint window, int width, int height)
    {
        Point origin = default;
        if (DwmGetWindowAttribute(window, 9, out var frame, Marshal.SizeOf<Rect>()) < 0
            || !GetClientRect(window, out var client) || !ClientToScreen(window, ref origin)) return new(0, 0, width, height);
        var sx = width / (double)Math.Max(1, frame.Right - frame.Left);
        var sy = height / (double)Math.Max(1, frame.Bottom - frame.Top);
        var x = Math.Clamp((int)Math.Round((origin.X - frame.Left) * sx), 0, width);
        var y = Math.Clamp((int)Math.Round((origin.Y - frame.Top) * sy), 0, height);
        return new(x, y, Math.Max(0, Math.Min(width - x, (int)Math.Round(client.Right * sx))),
            Math.Max(0, Math.Min(height - y, (int)Math.Round(client.Bottom * sy))));
    }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    private delegate bool EnumWindow(nint window, nint parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool EnumWindows(EnumWindow callback, nint parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindowVisible(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetClientRect(nint window, out Rect rectangle);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ClientToScreen(nint window, ref Point point);
    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(nint window, int attribute, out Rect value, int size);
}
