using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct2D1;
using Vortice.DirectWrite;

namespace EndfieldLogs.Desktop.Overlays;

/// <summary>Borrow the cached glyph arrays for one synchronous D2D call instead of copying them into native allocations per draw.</summary>
internal static unsafe class OverlayGlyphDrawing
{
    // Windows SDK dwrite.h: DWRITE_GLYPH_RUN. The font and arrays are owned by the caller.
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRun
    {
        internal nint FontFace;
        internal float FontEmSize;
        internal uint GlyphCount;
        internal ushort* Indices;
        internal float* Advances;
        internal GlyphOffset* Offsets;
        internal int IsSideways;
        internal uint BidiLevel;
    }

    internal static void Draw(ID2D1RenderTarget target, Vector2 origin, GlyphRun run, ID2D1Brush brush)
    {
        ArgumentNullException.ThrowIfNull(run.FontFace);
        ArgumentNullException.ThrowIfNull(run.Indices);
        if ((run.Advances is not null && run.Advances.Length != run.Indices.Length)
            || (run.Offsets is not null && run.Offsets.Length != run.Indices.Length))
            throw new ArgumentException("Glyph arrays must have matching lengths", nameof(run));
        fixed (ushort* indices = run.Indices)
        fixed (float* advances = run.Advances)
        fixed (GlyphOffset* offsets = run.Offsets)
        {
            NativeRun native = new()
            {
                FontFace = run.FontFace.NativePointer, FontEmSize = run.FontEmSize,
                GlyphCount = (uint)run.Indices.Length, Indices = indices, Advances = advances, Offsets = offsets,
                IsSideways = run.IsSideways ? 1 : 0, BidiLevel = (uint)run.BidiLevel
            };
            // ID2D1RenderTarget::DrawGlyphRun, slot 29 in the stable Windows COM interface.
            // Direct2D consumes the arrays during this call; no pointer escapes the fixed scopes.
            var draw = (delegate* unmanaged[Stdcall]<nint, Vector2, NativeRun*, nint, int, void>)(*(nint**)target.NativePointer)[29];
            draw(target.NativePointer, origin, &native, brush.NativePointer, 0); // DWRITE_MEASURING_MODE_NATURAL
        }
        GC.KeepAlive(run.FontFace);
        GC.KeepAlive(brush);
        GC.KeepAlive(target);
    }
}
