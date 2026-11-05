using System.Buffers.Binary;
using System.Security.Cryptography;

namespace EndfieldLogs.Core.Integrity;

public sealed record RawLogHashResult(long ByteSize, int LineCount, string Sha256, string ChainSha256);

public static class RawLogHashes
{
    public static RawLogHashResult Compute(ReadOnlySpan<byte> data)
    {
        byte[] accumulator = "endfield-raw-log-chain-v1"u8.ToArray();
        var offset = 0;
        var count = 0;
        Span<byte> index = stackalloc byte[4];
        using var hasher = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        while (offset < data.Length)
        {
            var end = offset;
            while (end < data.Length && data[end] != 10 && data[end] != 13) end++;
            if (end < data.Length)
            {
                var terminator = data[end++];
                if (terminator == 13 && end < data.Length && data[end] == 10) end++;
            }
            BinaryPrimitives.WriteUInt32BigEndian(index, checked((uint)count));
            hasher.AppendData(accumulator);
            hasher.AppendData(index);
            hasher.AppendData(data[offset..end]);
            accumulator = hasher.GetHashAndReset();
            count++;
            offset = end;
        }
        return new(data.Length, count, Convert.ToHexStringLower(SHA256.HashData(data)),
            Convert.ToHexStringLower(SHA256.HashData(accumulator)));
    }
}
