using System.Buffers.Binary;
using System.Collections;
using System.Collections.ObjectModel;
using System.Diagnostics.CodeAnalysis;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Versioned, derived static-resource cache. Original gzip JSON remains authoritative.
/// Both the source bytes and cache payload must match before any values are materialized.</summary>
internal static class CompiledResource
{
    private sealed class Shape(string[] names)
    {
        internal readonly ReadOnlyCollection<string> Names = Array.AsReadOnly(names);
        internal readonly Dictionary<string, int> Indices = names.Select((name, index) => (name, index))
            .ToDictionary(row => row.name, row => row.index, StringComparer.Ordinal);
    }
    private sealed class Fields(Shape shape, EvidenceValue[] values) : FrozenEvidence.FrozenFields
    {
        public int Count => values.Length;
        public EvidenceValue this[string key] => values[shape.Indices[key]];
        public IEnumerable<string> Keys => shape.Names;
        public IEnumerable<EvidenceValue> Values { get { foreach (var value in values) yield return value; } }
        public bool ContainsKey(string key) => shape.Indices.ContainsKey(key);
        public bool TryGetValue(string key, out EvidenceValue value)
        {
            if (shape.Indices.TryGetValue(key, out var index)) { value = values[index]; return true; }
            value = null!; return false;
        }
        public IEnumerator<KeyValuePair<string, EvidenceValue>> GetEnumerator()
        {
            for (var index = 0; index < values.Length; index++) yield return new(shape.Names[index], values[index]);
        }
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
    private static readonly EvidenceInteger[] Integers = Enumerable.Range(-1, 257).Select(value => new EvidenceInteger(value)).ToArray();
    private static readonly EvidenceReal Zero = new(0), NegativeZero = new(-0.0), One = new(1);
    private static readonly EvidenceBoolean True = new(true), False = new(false);

    internal static bool TryRead(string path, ReadOnlySpan<byte> source, [NotNullWhen(true)] out EvidenceValue? value)
    {
        value = null;
        try
        {
            if (!File.Exists(path)) return false;
            value = Read(File.ReadAllBytes(path), source);
            return true;
        }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException or OverflowException)
        {
            // A missing, stale, truncated or damaged derivative never suppresses the original loader.
            return false;
        }
    }

    internal static EvidenceValue Read(byte[] bytes, ReadOnlySpan<byte> source)
    {
        if (bytes.Length < 72 || !bytes.AsSpan(0, 8).SequenceEqual("EGLRC002"u8)
            || !SHA256.HashData(source).AsSpan().SequenceEqual(bytes.AsSpan(8, 32))
            || !SHA256.HashData(bytes.AsSpan(72)).AsSpan().SequenceEqual(bytes.AsSpan(40, 32)))
            throw new InvalidDataException("Compiled resource signature mismatch");
        return new Reader(bytes).Read();
    }

    private sealed class Reader(byte[] bytes)
    {
        private int position = 72;
        private EvidenceText[] text = [];
        private Shape[] shapes = [];
        private ReadOnlySpan<byte> Take(int count)
        {
            if (count < 0 || count > bytes.Length - position) throw new InvalidDataException("Compiled resource is truncated");
            var result = bytes.AsSpan(position, count); position += count; return result;
        }
        private int Count(int minimumBytes = 1)
        {
            var count = BinaryPrimitives.ReadInt32LittleEndian(Take(4));
            if (count < 0 || count > (bytes.Length - position) / minimumBytes) throw new InvalidDataException("Compiled resource count is invalid");
            return count;
        }
        private int Id(int length)
        {
            var id = BinaryPrimitives.ReadInt32LittleEndian(Take(4));
            if ((uint)id >= (uint)length) throw new InvalidDataException("Compiled resource index is invalid");
            return id;
        }
        internal EvidenceValue Read()
        {
            text = new EvidenceText[Count(4)];
            for (var index = 0; index < text.Length; index++)
            {
                var units = Take(checked(Count(2) * 2));
                // Raw UTF-16 units retain supplementary characters and lone surrogates.
                string name;
                if (BitConverter.IsLittleEndian) name = new string(MemoryMarshal.Cast<byte, char>(units));
                else
                {
                    var characters = new char[units.Length / 2];
                    for (var unit = 0; unit < characters.Length; unit++)
                        characters[unit] = (char)BinaryPrimitives.ReadUInt16LittleEndian(units[(unit * 2)..]);
                    name = new(characters);
                }
                text[index] = new(name);
            }
            shapes = new Shape[Count(4)];
            for (var index = 0; index < shapes.Length; index++)
            {
                var names = new string[Count(4)];
                HashSet<string> seen = new(StringComparer.Ordinal);
                for (var key = 0; key < names.Length; key++)
                {
                    names[key] = text[Id(text.Length)].Value;
                    if (!seen.Add(names[key])) throw new InvalidDataException("Compiled resource repeats a field");
                }
                shapes[index] = new(names);
            }
            var result = Value(0);
            if (position != bytes.Length) throw new InvalidDataException("Compiled resource contains trailing data");
            return result;
        }
        private EvidenceValue Integer()
        {
            ulong zigzag = 0;
            for (var shift = 0; shift <= 63; shift += 7)
            {
                var part = Take(1)[0];
                if (shift == 63 && part > 1) throw new InvalidDataException("Compiled resource integer overflow");
                zigzag |= (ulong)(part & 127) << shift;
                if (part < 128)
                {
                    var number = unchecked((long)(zigzag >> 1) ^ -((long)zigzag & 1));
                    return number is >= -1 and <= 255 ? Integers[(int)number + 1] : new EvidenceInteger(number);
                }
            }
            throw new InvalidDataException("Compiled resource integer overflow");
        }
        private EvidenceValue Value(int depth)
        {
            if (depth > 1000) throw new InvalidDataException("Compiled resource nesting limit exceeded");
            switch (Take(1)[0])
            {
                case 0: return EvidenceNull.Value;
                case 1: return False;
                case 2: return True;
                case 3: return Integer();
                case 4: return new EvidenceInteger(new BigInteger(Take(Count())));
                case 5:
                    var bits = BinaryPrimitives.ReadInt64LittleEndian(Take(8));
                    if (bits == 0x7ff8000000000000) return EvidenceJson.ResourceNaN;
                    var real = BitConverter.Int64BitsToDouble(bits);
                    return real == 0 ? BitConverter.DoubleToInt64Bits(real) < 0 ? NegativeZero : Zero : real == 1 ? One : new EvidenceReal(real);
                case 6: return text[Id(text.Length)];
                case 7:
                    var count = Count();
                    List<EvidenceValue> items = new(count);
                    for (var index = 0; index < count; index++) items.Add(Value(depth + 1));
                    return FrozenEvidence.OwnParsedArray(items);
                case 8:
                    var shape = shapes[Id(shapes.Length)];
                    var values = new EvidenceValue[shape.Names.Count];
                    for (var index = 0; index < values.Length; index++) values[index] = Value(depth + 1);
                    return new EvidenceObject(new Fields(shape, values));
                default: throw new InvalidDataException("Compiled resource tag is invalid");
            }
        }
    }
}
