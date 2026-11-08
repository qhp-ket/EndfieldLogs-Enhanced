using System.Runtime.InteropServices;
using Windows.Graphics;
using Windows.Graphics.Capture;
using WinRT;

namespace EndfieldLogs.Desktop.Vision;

/// <summary>One capture target shared across worker restarts; never retains a device, session or frame pool.</summary>
public sealed unsafe class WgcCaptureItemCache : IDisposable
{
    private readonly object gate = new();
    private GraphicsCaptureItem? item;
    private long window;
    private uint thread, process;
    private SizeInt32 size;
    private bool disposed;
    private int created;
    internal int CreatedCount { get { lock (gate) return created; } }
    internal bool HasItem { get { lock (gate) return item is not null; } }

    internal GraphicsCaptureItem Get(long target, out SizeInt32 dimensions)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var targetThread = GetWindowThreadProcessId((nint)target, out var targetProcess);
            if (targetThread == 0) { Clear(); throw new InvalidOperationException("游戏窗口已关闭"); }
            if (item is null || window != target || thread != targetThread || process != targetProcess)
            {
                Clear();
                item = CreateItem((nint)target); created++;
                window = target; thread = targetThread; process = targetProcess; size = item.Size;
            }
            dimensions = size;
            return item;
        }
    }

    internal void ObserveSize(GraphicsCaptureItem target, SizeInt32 dimensions)
    {
        lock (gate) if (ReferenceEquals(item, target)) size = dimensions;
    }

    internal void Invalidate(GraphicsCaptureItem? target)
    {
        lock (gate) if (ReferenceEquals(item, target)) Clear();
    }

    internal void KeepOnly(IReadOnlyList<long> windows)
    {
        lock (gate) if (item is not null && !windows.Contains(window)) Clear();
    }

    internal void Clear()
    {
        lock (gate) { item = null; window = 0; thread = process = 0; size = default; }
    }

    public void Dispose()
    {
        lock (gate) { if (disposed) return; disposed = true; Clear(); }
    }

    private static GraphicsCaptureItem CreateItem(nint window)
    {
        // The interop factory owns no device. Its item can be used by later capture sessions.
        var name = "Windows.Graphics.Capture.GraphicsCaptureItem";
        Marshal.ThrowExceptionForHR(WindowsCreateString(name, name.Length, out var className));
        nint factory = 0, item = 0;
        try
        {
            var iid = new Guid("3628e81b-3cac-4c60-b7f4-23ce0e0c3356");
            Marshal.ThrowExceptionForHR(RoGetActivationFactory(className, in iid, out factory));
            var itemIid = new Guid("79c3f95b-31f7-4ec2-a464-632ef5d30760");
            Marshal.ThrowExceptionForHR(((delegate* unmanaged[Stdcall]<nint, nint, Guid*, nint*, int>)(*(nint**)factory)[3])(factory, window, &itemIid, &item));
            return MarshalInterface<GraphicsCaptureItem>.FromAbi(item);
        }
        finally { if (item != 0) Marshal.Release(item); if (factory != 0) Marshal.Release(factory); WindowsDeleteString(className); }
    }

    [DllImport("combase.dll", CharSet = CharSet.Unicode, ExactSpelling = true)] private static extern int WindowsCreateString(string value, int length, out nint result);
    [DllImport("combase.dll", ExactSpelling = true)] private static extern int WindowsDeleteString(nint value);
    [DllImport("combase.dll", ExactSpelling = true)] private static extern int RoGetActivationFactory(nint className, in Guid iid, out nint factory);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint window, out uint process);
}
