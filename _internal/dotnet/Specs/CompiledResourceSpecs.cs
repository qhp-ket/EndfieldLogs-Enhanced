using System.IO.Compression;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

internal static class CompiledResourceSpecs
{
    internal static void Run(Action<bool, string> check, string root)
    {
        const string json = """{"name":"\ud800\u0000\ud83d\ude00","samples":[null,false,true,-9223372036854775808,9223372036854775807,1267650600228229401496703205376,0.0,-0.0,1.0,NaN,Infinity,-Infinity],"empty":{}}""";
        byte[] Gzip(string text)
        {
            using MemoryStream stream = new();
            using (GZipStream zip = new(stream, CompressionMode.Compress, leaveOpen: true)) zip.Write(Encoding.UTF8.GetBytes(text));
            return stream.ToArray();
        }
        var source = Gzip(json);
        using MemoryStream payload = new();
        using (BinaryWriter writer = new(payload, Encoding.UTF8, leaveOpen: true))
        {
            // Independent fixture encoding: ordered names, one root shape and an empty shape.
            var strings = new[] { "name", "samples", "empty", "\ud800\0\ud83d\ude00" };
            writer.Write(strings.Length);
            foreach (var text in strings) { writer.Write(text.Length); foreach (var unit in text) writer.Write((ushort)unit); }
            writer.Write(2); writer.Write(3); writer.Write(0); writer.Write(1); writer.Write(2); writer.Write(0);
            writer.Write((byte)8); writer.Write(0); writer.Write((byte)6); writer.Write(3);
            writer.Write((byte)7); writer.Write(12);
            writer.Write((byte)0); writer.Write((byte)1); writer.Write((byte)2);
            foreach (var value in new[] { long.MinValue, long.MaxValue })
            { writer.Write((byte)3); writer.Write7BitEncodedInt64(unchecked((value << 1) ^ (value >> 63))); }
            var large = (BigInteger.One << 100).ToByteArray(); writer.Write((byte)4); writer.Write(large.Length); writer.Write(large);
            foreach (var value in new[] { 0.0, -0.0, 1.0, BitConverter.UInt64BitsToDouble(0x7ff8000000000000), double.PositiveInfinity, double.NegativeInfinity })
            { writer.Write((byte)5); writer.Write(value); }
            writer.Write((byte)8); writer.Write(1);
        }
        byte[] Wrap(byte[] body) => [.. "EGLRC002"u8, .. SHA256.HashData(source), .. SHA256.HashData(body), .. body];
        var encoded = Wrap(payload.ToArray());
        var expected = EvidenceJson.ParseReadOnly(json);
        var actual = CompiledResource.Read(encoded, source);
        bool Exact(EvidenceValue left, EvidenceValue right) => (left, right) switch
        {
            (EvidenceNull, EvidenceNull) => true,
            (EvidenceBoolean a, EvidenceBoolean b) => a.Value == b.Value,
            (EvidenceInteger a, EvidenceInteger b) => a.Value == b.Value,
            (EvidenceReal a, EvidenceReal b) => BitConverter.DoubleToInt64Bits(a.Value) == BitConverter.DoubleToInt64Bits(b.Value),
            (EvidenceText a, EvidenceText b) => a.Value == b.Value,
            (EvidenceArray a, EvidenceArray b) => a.Items.Count == b.Items.Count && a.Items.Zip(b.Items).All(pair => Exact(pair.First, pair.Second)),
            (EvidenceObject a, EvidenceObject b) => a.Fields.Keys.SequenceEqual(b.Fields.Keys, StringComparer.Ordinal)
                && a.Fields.Values.Zip(b.Fields.Values).All(pair => Exact(pair.First, pair.Second)),
            _ => false,
        };
        check(Exact(expected, actual), "Compiled resources retain field order, UTF-16 units, exact integers, float bits and unknown values");
        var frozen = (EvidenceObject)actual;
        check(EvidenceJson.PythonEquals(new EvidenceArray([((EvidenceArray)frozen.Get("samples")).Items[9]]), EvidenceJson.ParseReadOnly("[NaN]")),
            "Compiled named NaN retains the original JSON literal identity in container comparisons");
        check(FrozenEvidence.IsFrozenRoot(frozen) && ReferenceEquals(FrozenEvidence.Capture(frozen), frozen),
            "Compiled resources use the existing recursively immutable ownership boundary");
        var copy = (EvidenceObject)EvidenceJson.Clone(frozen); ((Dictionary<string, EvidenceValue>)copy.Fields)["name"] = EvidenceNull.Value;
        var rejected = false;
        try { ((IList<EvidenceValue>)((EvidenceArray)frozen.Get("samples")).Items)[0] = EvidenceNull.Value; }
        catch (NotSupportedException) { rejected = true; }
        check(rejected && Exact(expected, frozen), "Editable copies and array mutation cannot change compiled resource evidence");
        var path = Path.Combine(root, "compiled.json.gz"); var cache = path + ".egr";
        File.WriteAllBytes(path, source); File.WriteAllBytes(cache, encoded);
        check(Exact(expected, new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!), "Resource loading accepts the valid derivative");
        var wrongVersion = encoded.ToArray(); wrongVersion[7] = (byte)'3'; File.WriteAllBytes(cache, wrongVersion);
        check(Exact(expected, new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!), "Unknown derivative versions fall back to original JSON");
        var damaged = encoded.ToArray(); damaged[^1] ^= 1; File.WriteAllBytes(cache, damaged);
        check(Exact(expected, new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!), "Damaged derivative payloads fall back to original JSON");
        var invalidIndex = payload.ToArray(); invalidIndex[^1] = 0x7f; File.WriteAllBytes(cache, Wrap(invalidIndex));
        check(Exact(expected, new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!), "Structurally invalid derivatives retain original JSON fallback");
        File.WriteAllBytes(cache, encoded[..30]);
        check(Exact(expected, new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!), "Truncated derivative headers retain original JSON fallback");
        File.WriteAllBytes(cache, encoded); File.WriteAllBytes(path, Gzip("{\"changed\":true}"));
        check(((EvidenceObject)new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!).Get("changed") is EvidenceBoolean { Value: true },
            "Changed source bytes invalidate a previously valid derivative");
        File.Delete(cache);
        check(((EvidenceObject)new ResourceFiles(root).ReadGzipRelative("compiled.json.gz")!).Get("changed") is EvidenceBoolean { Value: true },
            "Missing derivatives need no user action and load original JSON");
    }
}
