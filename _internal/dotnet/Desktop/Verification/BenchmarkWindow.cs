using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Visible benchmark windows never activate or accept user input.</summary>
internal static class BenchmarkWindow
{
    internal const string Protocol = "EndfieldLogs.InterfaceBenchmark.NoInputWindows.v1";
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern nint GetWindowLong(nint window, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
    private static extern nint SetWindowLong(nint window, int index, nint value);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnableWindow(nint window, bool enabled);
    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(nint window, nint after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")]
    private static extern nint GetForegroundWindow();
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(nint window, out uint process);
    [DllImport("user32.dll")]
    private static extern nint GetCapture();

    internal static void Prepare(Window window)
    {
        window.ShowActivated = false;
        window.ShowInTaskbar = false;
        window.Topmost = false;
        window.IsHitTestVisible = false;
        window.SourceInitialized += (_, _) =>
        {
            var handle = new WindowInteropHelper(window).Handle;
            Marshal.SetLastPInvokeError(0);
            var previous = SetWindowLong(handle, -20, GetWindowLong(handle, -20) | (nint)0x08000020);
            if (previous == 0 && Marshal.GetLastPInvokeError() != 0) throw new Win32Exception();
            EnableWindow(handle, false);
            HwndSource.FromHwnd(handle).AddHook((nint h, int message, nint w, nint l, ref bool handled) =>
            {
                if (message == 0x84) { handled = true; return -1; } // HTTRANSPARENT
                if (message == 0x21) { handled = true; return 3; } // MA_NOACTIVATE
                return 0;
            });
        };
        window.Loaded += (_, _) =>
        {
            // Bottom of the normal z-order; leave the user's foreground window alone.
            if (!SetWindowPos(new WindowInteropHelper(window).Handle, (nint)1, 0, 0, 0, 0, 0x0013))
                throw new Win32Exception();
            Check();
        };
    }

    internal static void Check()
    {
        GetWindowThreadProcessId(GetForegroundWindow(), out var process);
        if (process == Environment.ProcessId || GetCapture() != 0)
            throw new InvalidOperationException("界面基准不能取得前台焦点或捕获输入");
    }
}
