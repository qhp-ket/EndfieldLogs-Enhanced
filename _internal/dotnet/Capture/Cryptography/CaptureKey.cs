using System.Security.Cryptography;
using System.Text;
using System.Numerics;

namespace EndfieldLogs.Capture.Cryptography;

public static class CaptureKey
{
    private static RSA ImportLines(IReadOnlyList<string> lines)
    {
        if (lines.Count == 0) throw new CryptographicException("private key not found");
        var bytes = Convert.FromBase64String(string.Concat(lines));
        var key = RSA.Create();
        try
        {
            try { key.ImportPkcs8PrivateKey(bytes, out _); }
            catch (CryptographicException) { key.ImportRSAPrivateKey(bytes, out _); }
            return key;
        }
        catch { key.Dispose(); throw; }
    }

    public static RSA Load(string? path, string? embeddedBase64=null)
    {
        var exists = path is not null && File.Exists(path);
        string[] lines;
        if (exists)
        {
            // Invalid UTF-8 is ignored by the existing external resource reader.
            var utf8 = Encoding.GetEncoding("UTF-8", new EncoderReplacementFallback(""), new DecoderReplacementFallback(""));
            lines = File.ReadAllLines(path!, utf8);
            var text = string.Join('\n', lines);
            if (text.Contains("BEGIN", StringComparison.Ordinal) && text.Contains("PRIVATE KEY", StringComparison.Ordinal))
            {
                var key = RSA.Create();
                try { key.ImportFromPem(text); return key; }
                catch { key.Dispose(); throw; }
            }
        }
        else if (!string.IsNullOrEmpty(embeddedBase64)) lines = ["=== CLIENT_NET_RSA_PRIVATE_KEY ===", embeddedBase64, "=== END ==="];
        else throw new FileNotFoundException("rsa_keys.txt not found and embedded_keys.py is unavailable; provide an external rsa_keys.txt");
        var capture = false;
        List<string> captured = [];
        foreach (var line in lines)
        {
            if (line.StartsWith("=== CLIENT_NET_RSA_PRIVATE_KEY", StringComparison.Ordinal)) { capture=true; continue; }
            if (capture && line.StartsWith("===", StringComparison.Ordinal)) break;
            if (capture && line.Trim().Length > 0) captured.Add(line.Trim());
        }
        try { return ImportLines(captured); }
        catch (Exception error) when (error is CryptographicException or FormatException)
        {
            if (!exists || string.IsNullOrEmpty(embeddedBase64)) throw;
            return ImportLines(embeddedBase64.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries));
        }
    }

    public static byte[] DecryptSessionKey(RSA privateKey, byte[] encrypted)
    {
        var width = privateKey.KeySize/8;
        if (encrypted.Length != width) throw new ArgumentException($"Ciphertext with incorrect length (not {width} bytes)", nameof(encrypted));
        var modulus = privateKey.ExportParameters(false).Modulus!;
        if (new BigInteger(encrypted,isUnsigned:true,isBigEndian:true) >= new BigInteger(modulus,isUnsigned:true,isBigEndian:true))
            throw new ArgumentException("Ciphertext too large",nameof(encrypted));
        byte[] plain;
        try { plain = privateKey.Decrypt(encrypted, RSAEncryptionPadding.Pkcs1); }
        catch (CryptographicException) { plain=[]; }
        if (plain.Length != 32) throw new InvalidOperationException($"failed to decrypt session key: decrypted_len={plain.Length}");
        return plain;
    }
}
