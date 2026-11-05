using System.Numerics;
using System.Security.Cryptography;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;

internal static class SessionSpecs
{
    private static byte[] Frame(byte[] head, byte[] body) => [(byte)head.Length,(byte)body.Length,(byte)(body.Length >> 8),..head,..body];

    public static void Run(Action<bool,string> check)
    {
        check(JsonContract.Serialize(BigInteger.Pow(2,80)) == "1208925819614629174706176", "Unbounded protocol integer remains a JSON number");
        check(JsonContract.Serialize(new Dictionary<BigInteger,double> { [9]=0.5 }) == "{\"9\":0.5}", "Attribute integer keys preserve external JSON shape");
        using var generated = RSA.Create(2048);
        var plain = Enumerable.Range(0,32).Select(i => (byte)i).ToArray();
        var encrypted = generated.Encrypt(plain,RSAEncryptionPadding.Pkcs1);
        check(CaptureKey.DecryptSessionKey(generated,encrypted).SequenceEqual(plain), "Session key uses exact PKCS#1 v1.5 plaintext");
        try { CaptureKey.DecryptSessionKey(generated,generated.Encrypt(new byte[31],RSAEncryptionPadding.Pkcs1)); throw new InvalidOperationException("Wrong key length accepted"); }
        catch (InvalidOperationException error) when (error.Message.EndsWith("decrypted_len=31",StringComparison.Ordinal))
        { check(true,"Wrong decrypted length is rejected"); }
        try { CaptureKey.DecryptSessionKey(generated,new byte[1]); throw new InvalidOperationException("Wrong ciphertext width accepted"); }
        catch (ArgumentException) { check(true,"Wrong ciphertext width is rejected"); }
        try { CaptureKey.DecryptSessionKey(generated,new byte[256]); throw new InvalidOperationException("Invalid padding accepted"); }
        catch (InvalidOperationException error) when (error.Message.EndsWith("decrypted_len=0",StringComparison.Ordinal))
        { check(true,"Invalid PKCS#1 padding produces a failed-decryption diagnostic"); }
        foreach (var encoded in new[] { generated.ExportPkcs8PrivateKey(), generated.ExportRSAPrivateKey() })
        {
            using var loaded = CaptureKey.Load(null,Convert.ToBase64String(encoded));
            check(CaptureKey.DecryptSessionKey(loaded,encrypted).SequenceEqual(plain),"External key resource supports both existing encodings");
        }

        // Only ephemeral generated data is written, and the directory is always removed.
        var directory = Directory.CreateTempSubdirectory("endfield-synthetic-key-");
        try
        {
            var path = Path.Combine(directory.FullName,"synthetic.txt");
            File.WriteAllText(path,generated.ExportRSAPrivateKeyPem());
            using (var loaded = CaptureKey.Load(path)) check(CaptureKey.DecryptSessionKey(loaded,encrypted).SequenceEqual(plain),"PEM file loads directly");
            File.WriteAllText(path,"=== CLIENT_NET_RSA_PRIVATE_KEY ===\ninvalid\n=== END ===");
            using (var loaded = CaptureKey.Load(path,Convert.ToBase64String(generated.ExportPkcs8PrivateKey())))
                check(CaptureKey.DecryptSessionKey(loaded,encrypted).SequenceEqual(plain),"Invalid legacy block uses the supplied fallback");
        }
        finally { directory.Delete(true); }

        MessageRegistry registry = new("[{\"msg_id\":1,\"class_name\":\"CS_PING\"}]","[]");
        var flow = new FlowKey(new("192.0.2.1",30001),new("203.0.113.10",30000));
        foreach (var kind in new[] { "ignored", "protobuf", "compressed" })
        {
            List<Dictionary<string,object?>> diagnostics = [];
            RuntimeMetrics metrics = new();
            var transport = new SessionTransport(flow,"synthetic",registry,body => body,_ => plain,(_,_) => { },_ => { },metrics,diagnostics.Add);
            transport.Process(new(0,flow.Client,flow.Server,0,Frame([],[]),"synthetic"));
            var nonce = new byte[12];
            transport.Process(new(0,flow.Server,flow.Client,0,Frame([],[0x1a,1,0,0x22,12,..nonce]),"synthetic"));
            var head = kind == "ignored" ? new byte[] { 8,99 } : kind == "compressed" ? new byte[] { 8,1,48,1 } : new byte[] { 8,1 };
            var body = kind == "protobuf" ? new byte[] { 128 } : "bad"u8.ToArray();
            var cipher = new Xxe1(plain,nonce,1);
            var payload = cipher.Process([..head,..body]);
            transport.Process(new(100,flow.Client,flow.Server,3,Frame(payload[..head.Length],payload[head.Length..]),"synthetic"));
            check(transport.IsLive,"Diagnostic failure preserves session lifecycle");
            check(diagnostics[^1]["type"]?.ToString() == (kind == "ignored" ? "debug_ignored_frame" : kind == "protobuf" ? "debug_protobuf_error" : "debug_decompression_error"),
                "Diagnostic helper resolves its own message ID: "+kind);
            check((BigInteger)diagnostics[^1]["msg_id"]! == (kind == "ignored" ? 99 : 1),"Diagnostic event includes the correct message ID");
            check(metrics.ProtobufDecodeErrors == (kind == "protobuf" ? 1 : 0)
                  && metrics.DecompressionErrors == (kind == "compressed" ? 1 : 0),"Diagnostic errors retain their metric and reliability boundary");
        }
    }
}
