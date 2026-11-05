using System.Buffers.Binary;
using System.Numerics;

namespace EndfieldLogs.Capture.Cryptography;

/// <summary>XXE1's stream state, including its existing counter carry behavior.</summary>
public sealed class Xxe1
{
    private readonly uint[] state = new uint[16];
    private readonly byte[] keyStream = new byte[64];
    private int keyStreamOffset = 64;

    public Xxe1(ReadOnlySpan<byte> key, ReadOnlySpan<byte> nonce, uint counter = 0)
    {
        if (key.Length != 32) throw new ArgumentException("XXE1 key length must be 32", nameof(key));
        if (nonce.Length != 12) throw new ArgumentException("XXE1 nonce length must be 12", nameof(nonce));
        state[0] = 0x61707865; state[1] = 0x3320646e;
        state[2] = 0x79622d32; state[3] = 0x6b206574;
        for (var i = 0; i < 8; i++) state[4+i] = BinaryPrimitives.ReadUInt32LittleEndian(key.Slice(i*4, 4));
        state[12] = counter;
        for (var i = 0; i < 3; i++) state[13+i] = BinaryPrimitives.ReadUInt32LittleEndian(nonce.Slice(i*4, 4));
    }

    private static void QuarterRound(Span<uint> s, int a, int b, int c, int d)
    {
        unchecked
        {
            s[a] += s[b]; s[d] = BitOperations.RotateLeft(s[d] ^ s[a], 16);
            s[c] += s[d]; s[b] = BitOperations.RotateLeft(s[b] ^ s[c], 12);
            s[a] += s[b]; s[d] = BitOperations.RotateLeft(s[d] ^ s[a], 8);
            s[c] += s[d]; s[b] = BitOperations.RotateLeft(s[b] ^ s[c], 7);
        }
    }

    private void Refill()
    {
        Span<uint> working = stackalloc uint[16];
        state.CopyTo(working);
        for (var i = 0; i < 10; i++)
        {
            QuarterRound(working, 0, 4, 8, 12); QuarterRound(working, 1, 5, 9, 13);
            QuarterRound(working, 2, 6, 10, 14); QuarterRound(working, 3, 7, 11, 15);
            QuarterRound(working, 0, 5, 10, 15); QuarterRound(working, 1, 6, 11, 12);
            QuarterRound(working, 2, 7, 8, 13); QuarterRound(working, 3, 4, 9, 14);
        }
        for (var i = 0; i < 16; i++)
            BinaryPrimitives.WriteUInt32LittleEndian(keyStream.AsSpan(i*4, 4), unchecked(working[i]+state[i]));
        state[12] = unchecked(state[12]+1);
        if (state[12] == 0) state[13] = unchecked(state[13]+1);
        keyStreamOffset = 0;
    }

    public byte[] Process(ReadOnlySpan<byte> input)
    {
        var output = new byte[input.Length];
        var offset = 0;
        while (offset < input.Length)
        {
            if (keyStreamOffset == 64) Refill();
            var count = Math.Min(input.Length-offset, 64-keyStreamOffset);
            for (var i = 0; i < count; i++) output[offset+i] = (byte)(input[offset+i]^keyStream[keyStreamOffset+i]);
            offset += count;
            keyStreamOffset += count;
        }
        return output;
    }
}
