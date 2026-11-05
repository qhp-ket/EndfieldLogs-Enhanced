using System.Buffers.Binary;
using System.IO.Compression;
using System.Numerics;

namespace EndfieldLogs.Capture.Framing;

public sealed class SessionBodyDecompressionException(string message, Exception inner) : IOException(message, inner);

public static class SessionBodyCodec
{
    public static byte[] Decode(SessionHead head, byte[] body)
    {
        if (head.IsCompressed != true || body.Length == 0) return body;
        Exception? failure = null;
        foreach (var decoder in new Func<byte[], byte[]>[] { Lz4Block.Decompress, Zlib, RawDeflate, Gzip })
        {
            try { return decoder(body); }
            catch (Exception error) when (error is IOException or InvalidDataException or OverflowException)
            { failure=error; }
        }
        throw new SessionBodyDecompressionException(
            $"compressed session body could not be decoded: msg_id={head.MessageId ?? BigInteger.Zero} body_len={body.Length}", failure!);
    }

    // A normal Stream EOF lets DeflateStream accept some unfinished inputs. The reference's
    // one-shot decoder requires the end marker, so exhausting input is an error until it finishes.
    private sealed class EndGuardStream(byte[] data, int start=0, int maximumRead=int.MaxValue) : Stream
    {
        private int position = start;
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => data.Length;
        public override long Position { get => position; set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => Read(buffer.AsSpan(offset, count));
        public override int Read(Span<byte> buffer)
        {
            if (buffer.Length == 0) return 0;
            if (position >= data.Length) throw new EndOfStreamException("incomplete compressed stream");
            var size = Math.Min(Math.Min(buffer.Length, maximumRead), data.Length-position);
            data.AsSpan(position, size).CopyTo(buffer);
            position += size;
            return size;
        }
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private static byte[] ReadAll(Stream decoder)
    {
        using MemoryStream output = new();
        // DeflateStream.CopyTo has a separate fast path that drains the input past the
        // end marker. Read exposes the inflater's own completed-stream boundary.
        Span<byte> buffer = stackalloc byte[8192];
        int count;
        while ((count = decoder.Read(buffer)) != 0) output.Write(buffer[..count]);
        return output.ToArray();
    }

    public static byte[] Zlib(byte[] data)
    {
        using EndGuardStream input = new(data);
        using ZLibStream decoder = new(input, CompressionMode.Decompress);
        return ReadAll(decoder);
    }

    public static byte[] RawDeflate(byte[] data)
    {
        using EndGuardStream input = new(data);
        using DeflateStream decoder = new(input, CompressionMode.Decompress);
        return ReadAll(decoder);
    }

    public static byte[] Gzip(byte[] data)
    {
        if (data.Length < 10 || data[0] != 31 || data[1] != 139 || data[2] != 8 || (data[3] & 224) != 0)
            throw new InvalidDataException("invalid gzip header");
        var flags = data[3];
        var index = 10;
        void Require(int count)
        {
            if (count > data.Length-index) throw new InvalidDataException("incomplete gzip header");
        }
        if ((flags & 4) != 0)
        {
            Require(2);
            var length = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(index, 2));
            index += 2;
            Require(length);
            index += length;
        }
        foreach (var flag in new[] { 8, 16 })
            if ((flags & flag) != 0)
                do { Require(1); } while (data[index++] != 0);
        if ((flags & 2) != 0)
        {
            Require(2);
            if ((Crc32(data.AsSpan(0, index)) & 65535) != BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(index, 2)))
                throw new InvalidDataException("invalid gzip header checksum");
            index += 2;
        }
        // Bytewise feeding keeps the first member's trailer outside the native inflater.
        // Python zlib.decompress accepts the first member and ignores trailing members/data.
        using EndGuardStream input = new(data, index, 1);
        byte[] output;
        using (DeflateStream decoder = new(input, CompressionMode.Decompress, leaveOpen:true)) output = ReadAll(decoder);
        var end = checked((int)input.Position);
        if (data.Length-end < 8) throw new InvalidDataException("incomplete gzip trailer");
        if (Crc32(output) != BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(end, 4))
            || unchecked((uint)output.Length) != BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(end+4, 4)))
            throw new InvalidDataException("invalid gzip trailer");
        return output;
    }

    private static readonly uint[] CrcTable = Enumerable.Range(0, 256).Select(value =>
    {
        var crc = (uint)value;
        for (var i = 0; i < 8; i++) crc = (crc & 1) == 0 ? crc >> 1 : (crc >> 1)^0xedb88320;
        return crc;
    }).ToArray();

    private static uint Crc32(ReadOnlySpan<byte> bytes)
    {
        var crc = uint.MaxValue;
        foreach (var value in bytes) crc = CrcTable[(crc^value) & 255]^(crc >> 8);
        return ~crc;
    }
}
