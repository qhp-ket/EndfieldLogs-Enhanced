using System.Buffers.Binary;
using System.IO.Compression;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Python gzip.decompress semantics: all members, full trailers, and zero padding.</summary>
public static class GzipMembers
{
    public static byte[] Decompress(byte[] data)
    {
        using MemoryStream result = new();
        DecompressTo(data, result);
        return result.ToArray();
    }

    internal static string DecodeJson(byte[] data)
    {
        using MemoryStream result = new();
        DecompressTo(data, result);
        return JsonByteEncoding.Decode(result.GetBuffer().AsSpan(0, checked((int)result.Length)));
    }

    internal static EvidenceValue ParseJson(byte[] data)
    {
        // Resource archives normally contain one member. ISIZE is only a bounded
        // allocation hint: concatenation, padding and every trailer are still validated below.
        var hint = data.Length >= 18 ? BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(data.Length - 4)) : 0;
        using MemoryStream result = new(hint <= 64 * 1024 * 1024 ? (int)hint : 0);
        DecompressTo(data, result);
        return JsonByteEncoding.ParseReadOnly(result.GetBuffer().AsMemory(0, checked((int)result.Length)));
    }

    private static void DecompressTo(byte[] data, MemoryStream result)
    {
        byte[] buffer = new byte[8192];
        var position = 0;
        while (position < data.Length)
        {
            Require(10);
            if (data[position] != 31 || data[position + 1] != 139 || data[position + 2] != 8)
                throw new InvalidDataException("Invalid gzip header");
            var flags = data[position + 3];
            position += 10;
            if ((flags & 4) != 0)
            {
                Require(2);
                var size = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(position, 2));
                position += 2;
                Require(size);
                position += size;
            }
            foreach (var flag in new[] { 8, 16 })
                if ((flags & flag) != 0)
                    while (position < data.Length && data[position++] != 0) { }
            if ((flags & 2) != 0)
            {
                // The reference discards FHCRC instead of validating it.
                Require(2);
                position += 2;
            }
            var memberStart = position;
            var chunked = data.Length - position > buffer.Length;
            using var input = new MemberStream(data, position, chunked ? int.MaxValue : position);
            var crc = uint.MaxValue;
            uint memberSize = 0;
            using (var deflate = new DeflateStream(input, CompressionMode.Decompress, leaveOpen: true))
            {
                int size;
                while ((size = deflate.Read(buffer)) != 0)
                {
                    var bytes = buffer.AsSpan(0, size);
                    crc = UpdateCrc32(crc, bytes);
                    memberSize = unchecked(memberSize + (uint)size);
                    result.Write(bytes);
                }
            }
            position = checked((int)input.Position);
            if (chunked)
            {
                // DeflateStream may buffer bytes beyond this member. Replay with bulk
                // reads up to the last input block, then one byte at a time to recover
                // its exact end. Only the first pass writes output and updates the CRC.
                using var boundary = new MemberStream(data, memberStart, input.LastReadStart);
                using (var deflate = new DeflateStream(boundary, CompressionMode.Decompress, leaveOpen: true))
                    while (deflate.Read(buffer) != 0) { }
                position = checked((int)boundary.Position);
            }
            Require(8);
            if (~crc != BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(position, 4))
                || memberSize != BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(position + 4, 4)))
                throw new InvalidDataException("Invalid gzip trailer");
            position += 8;
            while (position < data.Length && data[position] == 0) position++;
        }
        void Require(int count)
        {
            if (count > data.Length - position) throw new EndOfStreamException("Incomplete gzip member");
        }
    }

    private static readonly uint[] CrcTable = Enumerable.Range(0, 256).Select(value =>
    {
        var crc = (uint)value;
        for (var bit = 0; bit < 8; bit++) crc = (crc & 1) == 0 ? crc >> 1 : (crc >> 1) ^ 0xedb88320;
        return crc;
    }).ToArray();

    private static uint UpdateCrc32(uint crc, ReadOnlySpan<byte> bytes)
    {
        foreach (var value in bytes) crc = CrcTable[(crc ^ value) & 255] ^ (crc >> 8);
        return crc;
    }

    private sealed class MemberStream(byte[] data, int start, int singleByteFrom) : Stream
    {
        private int position = start;
        internal int LastReadStart { get; private set; } = start;
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => data.Length;
        public override long Position { get => position; set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => Read(buffer.AsSpan(offset, count));
        public override int Read(Span<byte> buffer)
        {
            if (buffer.Length == 0) return 0;
            if (position >= data.Length) throw new EndOfStreamException("Incomplete deflate stream");
            LastReadStart = position;
            var count = position >= singleByteFrom ? 1 : Math.Min(buffer.Length, singleByteFrom - position);
            count = Math.Min(count, data.Length - position);
            data.AsSpan(position, count).CopyTo(buffer);
            position += count;
            return count;
        }
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
