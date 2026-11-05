using Vortice.Direct2D1;
using Vortice.DirectWrite;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>The overlay manager owns the dispatcher-thread factories; targets and their resources remain per-window.</summary>
internal sealed class OverlayGraphicsDevice : IDisposable
{
    internal ID2D1Factory Shapes { get; } = D2D1.D2D1CreateFactory<ID2D1Factory>(Vortice.Direct2D1.FactoryType.SingleThreaded);
    internal IDWriteFactory Text { get; }
    internal OverlayGraphicsDevice()
    {
        try { Text = DWrite.DWriteCreateFactory<IDWriteFactory>(); }
        catch { Shapes.Dispose(); throw; }
    }
    public void Dispose() { Text.Dispose(); Shapes.Dispose(); }
}
