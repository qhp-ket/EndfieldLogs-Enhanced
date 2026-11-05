using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Integrity;

public sealed record RawLogVerification(bool Verified, IReadOnlyList<string> Issues, RawLogHashResult Computed);
public sealed record RawLogIntegrityResult(bool Verified, IReadOnlyList<string> Issues, string? ProofPath,
    string? ProofSource, EvidenceObject? Proof, string RawContent, RawLogHashResult Computed);

/// <summary>Uploader-compatible local export integrity; the public seal scheme is not server attestation.</summary>
public static partial class RawLogProofs
{
    public const string Version = "raw-log-proof-v1";
    public const string Source = "endfield-dps-overlay";
    public const string Algorithm = "hmac-sha256(local)";
    public const string Begin = "## ENDFIELD_RAW_LOG_INTEGRITY_BEGIN sep=";
    public const string End = "## ENDFIELD_RAW_LOG_INTEGRITY_END";
    private const string LoadoutBegin = "## ENDFIELD_LOADOUT_SUMMARY_BEGIN sep=";
    private const string LoadoutEnd = "## ENDFIELD_LOADOUT_SUMMARY_END";
    private static readonly UTF8Encoding Utf8 = new(false, true);
    // Public, stable compatibility seed used by existing local exports. This is not the capture RSA key.
    private static readonly byte[] SealKey = SHA256.HashData("endfield|meter|raw-log-proof|2026-04|sidecar"u8);
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));
    private static EvidenceValue Text(string? value) => value is null ? EvidenceNull.Value : new EvidenceText(value);
    private static string Seal(EvidenceObject value) => Convert.ToHexStringLower(HMACSHA256.HashData(SealKey, Utf8.GetBytes(PythonSortedJson.Serialize(value, compact: true))));
    private static EvidenceObject HashFields(RawLogHashResult hashes) => Object(("byte_size", new EvidenceInteger(hashes.ByteSize)),
        ("line_count", new EvidenceInteger(hashes.LineCount)), ("sha256", new EvidenceText(hashes.Sha256)), ("chain_sha256", new EvidenceText(hashes.ChainSha256)));
    public static EvidenceObject Build(ReadOnlySpan<byte> data, string? fileName = null, string? exportedAt = null, EvidenceObject? meta = null)
    {
        var fields = HashFields(RawLogHashes.Compute(data)).Fields.ToDictionary();
        fields["version"] = new EvidenceText(Version); fields["source"] = new EvidenceText(Source); fields["file_name"] = Text(fileName);
        fields["exported_at"] = new EvidenceText(exportedAt ?? DateTimeOffset.Now.ToString("yyyy-MM-dd'T'HH:mm:sszzz", System.Globalization.CultureInfo.InvariantCulture));
        fields["meta"] = meta is null ? Object() : EvidenceJson.Clone(meta);
        var seal = Seal(new(fields));
        fields["seal_algorithm"] = new EvidenceText(Algorithm); fields["local_seal"] = new EvidenceText(seal);
        return new(fields);
    }

    public static RawLogVerification Verify(ReadOnlySpan<byte> data, EvidenceObject proof)
    {
        var computed = RawLogHashes.Compute(data); List<string> issues = [];
        void Equal(string key, EvidenceValue expected)
        { if (!EvidenceJson.PythonEquals(proof.Get(key), expected)) issues.Add("proof." + key + " mismatch"); }
        Equal("version", new EvidenceText(Version)); Equal("source", new EvidenceText(Source));
        foreach (var (key, value) in HashFields(computed).Fields) Equal(key, value);
        var fields = new[] { "version", "source", "file_name", "exported_at", "byte_size", "line_count", "sha256", "chain_sha256", "meta" }
            .ToDictionary(key => key, key => proof.Get(key), StringComparer.Ordinal);
        if (fields["meta"] is EvidenceNull or EvidenceBoolean { Value: false } || fields["meta"] is EvidenceText { Value.Length: 0 }
            || fields["meta"] is EvidenceInteger { Value.IsZero: true } || fields["meta"] is EvidenceReal { Value: 0 }
            || fields["meta"] is EvidenceArray { Items.Count: 0 }) fields["meta"] = Object();
        var seal = Seal(new(fields));
        Equal("seal_algorithm", new EvidenceText(Algorithm));
        var supplied = proof.Get("local_seal") is EvidenceText text ? text.Value : PythonDisplay.String(proof.Get("local_seal"));
        if (!CryptographicOperations.FixedTimeEquals(Utf8.GetBytes(supplied), Utf8.GetBytes(seal))) issues.Add("proof.local_seal mismatch");
        return new(issues.Count == 0, issues, computed);
    }

    /// <summary>Parse embedded proof and loadout suffixes; optional sidecar is used only without embedded proof.</summary>
    public static RawLogIntegrityResult Inspect(string fullText, EvidenceObject? sidecar = null, string? sidecarPath = null)
    {
        var split = Split(fullText, Begin, End, proof: true);
        var loadout = Split(split.Raw, LoadoutBegin, LoadoutEnd, proof: false);
        var bytes = Utf8.GetBytes(loadout.Raw);
        var issues = new[] { split.Issue, loadout.Issue }.OfType<string>().ToArray();
        if (issues.Length > 0) return new(false, issues, "<embedded>", "embedded", null, loadout.Raw, RawLogHashes.Compute(bytes));
        var proof = split.Proof ?? sidecar;
        if (proof is null) return new(false, ["missing integrity proof"], null, null, null, loadout.Raw, RawLogHashes.Compute(bytes));
        var result = Verify(bytes, proof);
        return new(result.Verified, result.Issues, split.Proof is not null ? "<embedded>" : sidecarPath,
            split.Proof is not null ? "embedded" : "sidecar", (EvidenceObject)EvidenceJson.Clone(proof), loadout.Raw, result.Computed);
    }

    private static (string Raw, EvidenceObject? Proof, string? Issue) Split(string text, string begin, string end, bool proof)
    {
        var index = text.LastIndexOf(begin, StringComparison.Ordinal);
        if (index < 0) return (text, null, null);
        var label = proof ? "embedded proof" : "embedded loadout";
        var lineEnd = text.IndexOf('\n', index);
        if (lineEnd < 0) return (text, null, label + " begin marker incomplete");
        var marker = text[index..lineEnd];
        if (marker != begin + "0" && marker != begin + "1") return (text, null, label + " begin marker malformed");
        var endIndex = text.IndexOf("\n" + end, lineEnd + 1, StringComparison.Ordinal);
        if (endIndex < 0) return (text, null, label + " end marker missing");
        EvidenceObject? payload = null;
        if (proof)
        {
            EvidenceValue parsed;
            try { parsed = EvidenceJson.Parse(text[(lineEnd + 1)..endIndex]); }
            catch (FormatException) { return (text, null, "embedded proof json malformed"); }
            if (parsed is not EvidenceNull) payload = parsed as EvidenceObject ?? throw new InvalidDataException("完整性证明应为对象");
        }
        var raw = text[..index];
        if (marker.EndsWith('1') && raw.EndsWith('\n')) raw = raw[..^1];
        return (raw, payload, null);
    }
}
