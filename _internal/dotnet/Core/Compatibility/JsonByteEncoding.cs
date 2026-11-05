using System.Buffers.Binary;
using System.Text;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Python JSON byte inputs detect UTF-8/16/32 and preserve encoded surrogate code points.</summary>
public static class JsonByteEncoding
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    public static string Decode(ReadOnlySpan<byte> data)
    {
        var (skip, width, littleEndian) = Detect(data);
        return width == 1 ? DecodeUtf8(data[skip..]) : Wide(data[skip..], width, littleEndian);
    }

    internal static EvidenceValue ParseReadOnly(ReadOnlyMemory<byte> data)
    {
        var (skip, width, littleEndian) = Detect(data.Span);
        return width == 1 ? EvidenceJson.ParseReadOnlyUtf8(data[skip..], surrogatePass: true)
            : EvidenceJson.ParseReadOnly(Wide(data.Span[skip..], width, littleEndian));
    }

    private static (int Skip, int Width, bool LittleEndian) Detect(ReadOnlySpan<byte> data)
    {
        if (data.StartsWith(new byte[] { 0, 0, 0xfe, 0xff })) return (4, 4, false);
        if (data.StartsWith(new byte[] { 0xff, 0xfe, 0, 0 })) return (4, 4, true);
        if (data.StartsWith(new byte[] { 0xfe, 0xff })) return (2, 2, false);
        if (data.StartsWith(new byte[] { 0xff, 0xfe })) return (2, 2, true);
        if (data.StartsWith(new byte[] { 0xef, 0xbb, 0xbf })) return (3, 1, false);
        if (data.Length >= 4)
        {
            if (data[0] == 0) return (0, data[1] == 0 ? 4 : 2, false);
            if (data[1] == 0) return (0, data[2] != 0 || data[3] != 0 ? 2 : 4, true);
        }
        else if (data.Length == 2)
        {
            if (data[0] == 0) return (0, 2, false);
            if (data[1] == 0) return (0, 2, true);
        }
        return (0, 1, false);
    }

    public static EvidenceValue Parse(ReadOnlySpan<byte> data) => EvidenceJson.Parse(Decode(data));

    private static string Wide(ReadOnlySpan<byte> data, int width, bool littleEndian)
    {
        if (data.Length % width != 0) throw Invalid();
        StringBuilder text = new(data.Length / width);
        for (var offset = 0; offset < data.Length; offset += width)
        {
            if (width == 2)
            {
                var unit = littleEndian ? BinaryPrimitives.ReadUInt16LittleEndian(data[offset..]) : BinaryPrimitives.ReadUInt16BigEndian(data[offset..]);
                text.Append((char)unit);
                continue;
            }
            var code = littleEndian ? BinaryPrimitives.ReadUInt32LittleEndian(data[offset..]) : BinaryPrimitives.ReadUInt32BigEndian(data[offset..]);
            Append(text, code);
        }
        return text.ToString();
    }

    internal static string DecodeUtf8(ReadOnlySpan<byte> data)
    {
        // Ordinary UTF-8 needs only the final string. The fallback retains Python's
        // surrogatepass behavior, which the platform decoder deliberately rejects.
        try { return StrictUtf8.GetString(data); }
        catch (DecoderFallbackException) { return Utf8SurrogatePass(data); }
    }

    private static string Utf8SurrogatePass(ReadOnlySpan<byte> data)
    {
        StringBuilder text = new(data.Length);
        for (var offset = 0; offset < data.Length;)
        {
            var first = data[offset++];
            if (first < 0x80) { text.Append((char)first); continue; }
            var length = first is >= 0xc2 and <= 0xdf ? 2 : first is >= 0xe0 and <= 0xef ? 3 : first is >= 0xf0 and <= 0xf4 ? 4 : 0;
            if (length == 0 || offset + length - 1 > data.Length) throw Invalid();
            uint code = (uint)(first & (0x7f >> length));
            for (var index = 1; index < length; index++)
            {
                var next = data[offset++];
                if (next is < 0x80 or > 0xbf) throw Invalid();
                code = code << 6 | (uint)(next & 0x3f);
            }
            if (code < (length == 2 ? 0x80 : length == 3 ? 0x800 : 0x10000)) throw Invalid();
            Append(text, code);
        }
        return text.ToString();
    }

    private static void Append(StringBuilder text, uint code)
    {
        if (code > 0x10ffff) throw Invalid();
        if (code <= 0xffff) text.Append((char)code);
        else text.Append(char.ConvertFromUtf32((int)code));
    }
    private static DecoderFallbackException Invalid() => new("Invalid JSON byte encoding");
}
