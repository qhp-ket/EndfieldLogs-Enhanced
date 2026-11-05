using System.Runtime.InteropServices;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Vision;
using Windows.Graphics;
using Windows.Graphics.Capture;
using Windows.Graphics.DirectX;
using Windows.Graphics.DirectX.Direct3D11;
using WinRT;

namespace EndfieldLogs.Desktop.Vision;

/// <summary>Free-threaded WGC adapter. Callbacks retain one latest GPU frame; the vision worker maps a leased staging surface.</summary>
public sealed unsafe class WgcCaptureBackend : IVisionCaptureBackend
{
    private readonly object gate = new();
    private readonly D3DReadback readback;
    private readonly IDirect3DDevice device;
    private GameWindows? discovery;
    private string? executable;
    private GraphicsCaptureItem? item;
    private GraphicsCaptureSession? session;
    private Direct3D11CaptureFramePool? pool;
    private Direct3D11CaptureFrame? latest;
    private SizeInt32 size;
    private long window, nextId, latestId;
    private uint windowThread, windowProcess;
    private double received;
    private bool disposed, leased, targetClosed;
    private Exception? failure;
    private long resized, undersized;
    internal object Diagnostics { get { lock (gate) return new { receivedFrames = nextId, resized, undersized, size.Width, size.Height, targetClosed, window }; } }

    public WgcCaptureBackend()
    {
        if (!GraphicsCaptureSession.IsSupported()) throw new PlatformNotSupportedException("系统不支持 Windows Graphics Capture");
        readback = new();
        nint inspectable = 0;
        try { inspectable = readback.CreateInspectableDevice(); device = MarshalInterface<IDirect3DDevice>.FromAbi(inspectable); }
        catch { readback.Dispose(); throw; }
        finally { if (inspectable != 0) Marshal.Release(inspectable); }
    }
    public VisionTargets Discover(string game)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        if (game != executable) { discovery = new(game); executable = game; }
        var found = discovery!.Discover(); return new(found.Windows, found.Foreground);
    }
    public void SetTarget(long? target)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        CloseTarget();
        if (target is null) return;
        try
        {
            item = CreateItem((nint)target.Value); size = item.Size;
            if (size.Width <= 0 || size.Height <= 0) throw new InvalidOperationException("游戏窗口尺寸无效");
            var thread = GetWindowThreadProcessId((nint)target.Value, out var process);
            if (thread == 0) throw new InvalidOperationException("游戏窗口已关闭");
            pool = Direct3D11CaptureFramePool.CreateFreeThreaded(device, DirectXPixelFormat.B8G8R8A8UIntNormalized, 2, size);
            session = pool.CreateCaptureSession(item); session.IsCursorCaptureEnabled = false;
            // Match Qt's WGC backend: disable the colored capture border on each
            // new session, including replacements after a target resize.
            var sessionPointer = MarshalInterface<GraphicsCaptureSession>.FromManaged(session);
            try { CaptureSessionOptions.TryDisableBorder(sessionPointer); }
            finally { Marshal.Release(sessionPointer); }
            lock (gate) { window = target.Value; windowThread = thread; windowProcess = process; targetClosed = false; failure = null; }
            pool.FrameArrived += OnFrame;
            session.StartCapture();
        }
        catch { CloseTarget(); throw; }
    }
    private void OnFrame(Direct3D11CaptureFramePool sender, object args)
    {
        // Closing detaches the pool before disposal. Late callbacks never touch a replacement session.
        lock (gate)
        {
            if (disposed || targetClosed || !ReferenceEquals(sender, pool)) return;
            try
            {
                var frame = sender.TryGetNextFrame(); if (frame is null) return;
                latest?.Dispose(); latest = frame; latestId = ++nextId;
                received = frame.SystemRelativeTime.TotalSeconds;
            }
            catch (Exception error) { failure = error; }
        }
    }
    public VisionCaptureFrame? AcquireLatest()
    {
        VisionCaptureFrame? result; long? restart;
        lock (gate) result = AcquireFrame(out restart);
        // A new session requests the current composition even when resizing leaves a static window.
        // Pool/session closure runs outside the callback lock.
        if (restart is not null) SetTarget(restart);
        return result;
    }
    private VisionCaptureFrame? AcquireFrame(out long? restart)
    {
        restart = null;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            // Closed subscriptions retain a native window wait after each capture-item
            // replacement. Check the HWND at the existing read boundary instead;
            // no extra polling timer or per-target wait registration is needed.
            if (targetClosed || window == 0) return null;
            if (GetWindowThreadProcessId((nint)window, out var process) != windowThread || process != windowProcess)
            {
                targetClosed = true; latest?.Dispose(); latest = null; return null;
            }
            if (failure is not null) throw new InvalidOperationException("WGC 帧接收失败", failure);
            if (leased) throw new InvalidOperationException("上一帧仍在读取");
            var frame = latest; latest = null; if (frame is null) return null;
            try
            {
                var content = frame.ContentSize;
                if (content.Width <= 0 || content.Height <= 0) return null;
                if (content.Width != size.Width || content.Height != size.Height)
                {
                    // The resize frame's underlying texture can still have the old size. Recreate and await a fresh frame.
                    resized++; restart = window; return null;
                }
                // The projected surface owns native texture/device resources separately from the frame.
                // Closing the frame alone leaves that ownership alive until the RCW is collected.
                // Readback has its own staging texture, so the source can close before its mapped lease.
                using var capturedSurface = frame.Surface;
                var surface = MarshalInterface<IDirect3DSurface>.FromManaged(capturedSurface);
                nint access = 0, texture = 0;
                try
                {
                    var accessIid = new Guid("a9b3d012-3df2-4ee3-b8d1-8695f457d3c1");
                    Marshal.ThrowExceptionForHR(Marshal.QueryInterface(surface, in accessIid, out access));
                    var textureIid = new Guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c");
                    Marshal.ThrowExceptionForHR(((delegate* unmanaged[Stdcall]<nint, Guid*, nint*, int>)(*(nint**)access)[3])(access, &textureIid, &texture));
                    if (!readback.TryMap(texture, content.Width, content.Height, out var memory, out var stride)) { undersized++; return null; }
                    var pixels = new VisionPixels(memory, content.Width, content.Height, stride);
                    var client = GameWindows.ClientInFrame((nint)window, content.Width, content.Height);
                    leased = true;
                    return new(pixels, new(client.X, client.Y, client.Width, client.Height), latestId, received, window, ReleaseFrame);
                }
                finally { if (texture != 0) Marshal.Release(texture); if (access != 0) Marshal.Release(access); Marshal.Release(surface); }
            }
            finally { frame?.Dispose(); }
        }
    }
    private void ReleaseFrame()
    {
        lock (gate)
        {
            if (!leased) return; readback.Unmap(); leased = false;
            if (disposed) CloseDevice();
        }
    }
    private void CloseTarget()
    {
        GraphicsCaptureSession? oldSession; Direct3D11CaptureFramePool? oldPool;
        lock (gate)
        {
            oldSession = session; oldPool = pool; item = null; session = null; pool = null;
            latest?.Dispose(); latest = null; window = 0; windowThread = windowProcess = 0; targetClosed = true; failure = null;
        }
        if (oldPool is not null) oldPool.FrameArrived -= OnFrame;
        try { oldSession?.Dispose(); }
        finally
        {
            oldPool?.Dispose();
        }
    }
    public void Dispose()
    {
        lock (gate) { if (disposed) return; disposed = true; }
        try { CloseTarget(); }
        finally { lock (gate) if (!leased) CloseDevice(); }
    }
    private void CloseDevice()
    {
        try { device.Dispose(); }
        finally
        {
            readback.Dispose();
        }
    }
    private static GraphicsCaptureItem CreateItem(nint window)
    {
        // IGraphicsCaptureItemInterop is an IUnknown factory interface, separate from the WinRT item projection.
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
