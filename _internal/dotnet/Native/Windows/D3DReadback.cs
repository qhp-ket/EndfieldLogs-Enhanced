using System.Buffers;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace EndfieldLogs.Native.Windows;

/// <summary>Small D3D11 readback owner. One staging texture, one mapped lease, no managed full-frame copy.</summary>
[SupportedOSPlatform("windows")]
public sealed unsafe class D3DReadback : IDisposable
{
    private nint device, context, staging;
    private TextureDescription size;
    private MappedMemory? mapped;
    public D3DReadback()
    {
        var result = D3D11CreateDevice(0, 1, 0, 0x20, 0, 0, 7, out device, out _, out context);
        if (result < 0)
        {
            Release(ref context); Release(ref device);
            result = D3D11CreateDevice(0, 5, 0, 0x20, 0, 0, 7, out device, out _, out context);
        }
        if (result < 0) { Dispose(); Marshal.ThrowExceptionForHR(result); }
        var iid = new Guid("9b7e4e00-342c-4106-a19f-4f2704f689f0");
        try
        {
            Marshal.ThrowExceptionForHR(Marshal.QueryInterface(context, in iid, out var multithread));
            try { ((delegate* unmanaged[Stdcall]<nint, int, int>)Slot(multithread, 5))(multithread, 1); }
            finally { Marshal.Release(multithread); }
        }
        catch { Dispose(); throw; }
    }
    public nint CreateInspectableDevice()
    {
        var iid = new Guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c");
        Marshal.ThrowExceptionForHR(Marshal.QueryInterface(device, in iid, out var dxgi));
        try { Marshal.ThrowExceptionForHR(CreateDirect3D11DeviceFromDXGIDevice(dxgi, out var value)); return value; }
        finally { Marshal.Release(dxgi); }
    }
    public bool TryMap(nint texture, int width, int height, out ReadOnlyMemory<byte> pixels, out int stride)
    {
        pixels = default; stride = 0;
        ObjectDisposedException.ThrowIf(device == 0, this);
        if (mapped is not null) throw new InvalidOperationException("上一帧仍在读取");
        TextureDescription description;
        ((delegate* unmanaged[Stdcall]<nint, TextureDescription*, void>)Slot(texture, 10))(texture, &description);
        if (description.Format != 87 || description.SampleCount != 1 || width <= 0 || height <= 0)
            throw new InvalidDataException("WGC 纹理格式或尺寸无效");
        // Resize can report the new content rectangle before the pool supplies a larger surface.
        if (width > description.Width || height > description.Height) return false;
        if (staging == 0 || description.Width != size.Width || description.Height != size.Height)
        {
            Release(ref staging); size = description;
            size.Usage = 3; size.BindFlags = 0; size.CpuAccess = 0x20000; size.MiscFlags = 0;
            nint created; var stagingDescription = size;
            Marshal.ThrowExceptionForHR(((delegate* unmanaged[Stdcall]<nint, TextureDescription*, nint, nint*, int>)Slot(device, 5))(device, &stagingDescription, 0, &created));
            staging = created;
        }
        ((delegate* unmanaged[Stdcall]<nint, nint, nint, void>)Slot(context, 47))(context, staging, texture);
        MappedResource resource;
        Marshal.ThrowExceptionForHR(((delegate* unmanaged[Stdcall]<nint, nint, uint, uint, uint, MappedResource*, int>)Slot(context, 14))(context, staging, 0, 1, 0, &resource));
        try
        {
            stride = checked((int)resource.RowPitch);
            if (stride < checked(width * 4) || resource.Data == 0) throw new InvalidDataException("WGC 纹理行宽无效");
            mapped = new(resource.Data, checked((height - 1) * stride + width * 4));
            pixels = mapped.Memory; return true;
        }
        catch { ((delegate* unmanaged[Stdcall]<nint, nint, uint, void>)Slot(context, 15))(context, staging, 0); throw; }
    }
    public void Unmap()
    {
        if (mapped is null) return;
        ((IDisposable)mapped).Dispose(); mapped = null;
        ((delegate* unmanaged[Stdcall]<nint, nint, uint, void>)Slot(context, 15))(context, staging, 0);
    }
    public void Dispose() { Unmap(); Release(ref staging); Release(ref context); Release(ref device); }
    private static nint Slot(nint value, int index) => (*(nint**)value)[index];
    private static void Release(ref nint value) { if (value != 0) Marshal.Release(value); value = 0; }
    [StructLayout(LayoutKind.Sequential)] private struct TextureDescription
    {
        public uint Width, Height, MipLevels, ArraySize, Format, SampleCount, SampleQuality, Usage, BindFlags, CpuAccess, MiscFlags;
    }
    [StructLayout(LayoutKind.Sequential)] private struct MappedResource { public nint Data; public uint RowPitch, DepthPitch; }
    private sealed class MappedMemory(nint pointer, int length) : MemoryManager<byte>
    {
        private nint address = pointer;
        public override Span<byte> GetSpan() { ObjectDisposedException.ThrowIf(address == 0, this); return new((void*)address, length); }
        public override MemoryHandle Pin(int elementIndex = 0)
        {
            ObjectDisposedException.ThrowIf(address == 0, this);
            if ((uint)elementIndex > (uint)length) throw new ArgumentOutOfRangeException(nameof(elementIndex));
            return new((byte*)address + elementIndex);
        }
        public override void Unpin() { }
        protected override void Dispose(bool disposing) => address = 0;
    }
    [DllImport("d3d11.dll")] private static extern int D3D11CreateDevice(nint adapter, uint driver, nint software, uint flags,
        nint featureLevels, uint count, uint version, out nint device, out uint featureLevel, out nint context);
    [DllImport("d3d11.dll")] private static extern int CreateDirect3D11DeviceFromDXGIDevice(nint dxgi, out nint inspectable);
}
