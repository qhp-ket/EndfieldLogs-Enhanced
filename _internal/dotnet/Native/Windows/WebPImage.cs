using System.Runtime.InteropServices;

namespace EndfieldLogs.Native.Windows;

public sealed record WebPImage(int Width, int Height, byte[] PremultipliedBgra)
{
    static WebPImage()
    {
        // Native decoders have their own directory in portable packages. Development
        // builds keep the SDK's normal layout and use its default search behavior.
        NativeLibrary.SetDllImportResolver(typeof(WebPImage).Assembly, (name, assembly, _) =>
        {
            if (name != "libwebpdemux") return 0;
            var path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "native", "webp", "libwebpdemux.dll"));
            return File.Exists(path) ? NativeLibrary.Load(path, assembly,
                DllImportSearchPath.UseDllDirectoryForDependencies | DllImportSearchPath.SafeDirectories) : 0;
        });
    }

    /// <summary>Decode one fully composed frame; skin backgrounds are static, including animated files.</summary>
    public static unsafe WebPImage Decode(ReadOnlySpan<byte> bytes)
    {
        const int abiVersion = 0x0107; // libwebp 1.6 demux.h, WEBP_DEMUX_ABI_VERSION.
        Options options = default;
        if (WebPAnimDecoderOptionsInitInternal(ref options, abiVersion) == 0)
            throw new NotSupportedException("WebP 解码库版本不兼容");
        options.ColorMode = 8; // MODE_bgrA: premultiplied BGRA, matching WPF Pbgra32.
        fixed (byte* source = bytes)
        {
            Data data = new() { Bytes = source, Size = (nuint)bytes.Length };
            var decoder = WebPAnimDecoderNewInternal(ref data, ref options, abiVersion);
            if (decoder == 0) throw new InvalidDataException("WebP 图片无效或无法解码");
            try
            {
                if (WebPAnimDecoderGetInfo(decoder, out var info) == 0 || info.Width == 0 || info.Height == 0
                    || info.Width > int.MaxValue || info.Height > int.MaxValue)
                    throw new InvalidDataException("WebP 图片尺寸无效");
                var length = checked((int)((long)info.Width * info.Height * 4));
                if (WebPAnimDecoderGetNext(decoder, out var pixels, out _) == 0 || pixels == 0)
                    throw new InvalidDataException("WebP 图片首帧无法解码");
                return new((int)info.Width, (int)info.Height, new ReadOnlySpan<byte>((void*)pixels, length).ToArray());
            }
            finally { WebPAnimDecoderDelete(decoder); }
        }
    }

    [StructLayout(LayoutKind.Sequential)] private unsafe struct Data { internal byte* Bytes; internal nuint Size; }
    [StructLayout(LayoutKind.Sequential)] private unsafe struct Options { internal int ColorMode, UseThreads; internal fixed uint Padding[7]; }
    [StructLayout(LayoutKind.Sequential)] private unsafe struct Info { internal uint Width, Height, LoopCount, Background, Frames; internal fixed uint Padding[4]; }
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.SafeDirectories)]
    [DllImport("libwebpdemux", CallingConvention = CallingConvention.Cdecl)] private static extern int WebPAnimDecoderOptionsInitInternal(ref Options options, int version);
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.SafeDirectories)]
    [DllImport("libwebpdemux", CallingConvention = CallingConvention.Cdecl)] private static extern nint WebPAnimDecoderNewInternal(ref Data data, ref Options options, int version);
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.SafeDirectories)]
    [DllImport("libwebpdemux", CallingConvention = CallingConvention.Cdecl)] private static extern int WebPAnimDecoderGetInfo(nint decoder, out Info info);
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.SafeDirectories)]
    [DllImport("libwebpdemux", CallingConvention = CallingConvention.Cdecl)] private static extern int WebPAnimDecoderGetNext(nint decoder, out nint pixels, out int timestamp);
    [DefaultDllImportSearchPaths(DllImportSearchPath.AssemblyDirectory | DllImportSearchPath.SafeDirectories)]
    [DllImport("libwebpdemux", CallingConvention = CallingConvention.Cdecl)] private static extern void WebPAnimDecoderDelete(nint decoder);
}
