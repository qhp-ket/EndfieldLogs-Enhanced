using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace EndfieldLogs.Native.Windows;

/// <summary>Owns a premultiplied BGRA DIB. Desktop alpha changes composition while retaining the source surface for WGC.</summary>
[SupportedOSPlatform("windows")]
public sealed class LayeredSurface : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct Size { public int Width, Height; }
    [StructLayout(LayoutKind.Sequential, Pack = 1)] private struct Blend { public byte Operation, Flags, Alpha, Format; }
    [StructLayout(LayoutKind.Sequential)] private struct BitmapInfo
    {
        public uint Size; public int Width, Height; public ushort Planes, Bits;
        public uint Compression, ImageSize; public int X, Y; public uint Colors, Important;
    }
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateLayeredWindow(nint window, nint screen, ref Point destination, ref Size size, nint source, ref Point origin, uint colorKey, ref Blend blend, uint flags);
    [DllImport("gdi32.dll", SetLastError = true)] private static extern nint CreateCompatibleDC(nint source);
    [DllImport("gdi32.dll", SetLastError = true)] private static extern nint CreateDIBSection(nint source, ref BitmapInfo info, uint usage, out nint pixels, nint section, uint offset);
    [DllImport("gdi32.dll")] private static extern nint SelectObject(nint dc, nint value);
    [DllImport("gdi32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DeleteObject(nint value);
    [DllImport("gdi32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DeleteDC(nint dc);
    private nint context, bitmap, previous;
    private bool disposed;
    public nint Pixels { get; private set; }
    public int Width { get; private set; }
    public int Height { get; private set; }
    public int ByteSize => checked(Width * Height * 4);
    public void Resize(int width, int height)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        if (width == Width && height == Height) return;
        if (width is < 1 or > 32768 || height is < 1 or > 32768) throw new ArgumentOutOfRangeException(nameof(width));
        Clear();
        context = CreateCompatibleDC(0); if (context == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
        var info = new BitmapInfo { Size = (uint)Marshal.SizeOf<BitmapInfo>(), Width = width, Height = -height, Planes = 1, Bits = 32 };
        bitmap = CreateDIBSection(context, ref info, 0, out var pixels, 0, 0);
        if (bitmap == 0) { var error = Marshal.GetLastWin32Error(); Clear(); throw new Win32Exception(error); }
        Pixels = pixels; previous = SelectObject(context, bitmap); Width = width; Height = height;
    }
    public void Present(nint window, int x, int y, double opacity)
    {
        ObjectDisposedException.ThrowIf(disposed, this); if (context == 0) return;
        var destination = new Point { X = x, Y = y }; var origin = new Point(); var size = new Size { Width = Width, Height = Height };
        var blend = new Blend { Alpha = (byte)Math.Clamp((int)Math.Round(opacity * 255), 0, 255), Format = 1 };
        if (!UpdateLayeredWindow(window, 0, ref destination, ref size, context, ref origin, 0, ref blend, 2)) throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    private void Clear()
    {
        if (context != 0 && previous != 0) SelectObject(context, previous);
        if (bitmap != 0) DeleteObject(bitmap); if (context != 0) DeleteDC(context);
        bitmap = context = previous = Pixels = 0; Width = Height = 0;
    }
    public void Dispose() { if (disposed) return; Clear(); disposed = true; }
}
