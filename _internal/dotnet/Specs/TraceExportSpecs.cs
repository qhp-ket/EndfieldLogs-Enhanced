using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Integrity;
using EndfieldLogs.Runtime.History;

internal static class TraceExportSpecs
{
    private const string Hit = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-export-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            var source = Path.Combine(root, "trace_20261028.log"); var destination = Path.Combine(root, "导出.log");
            File.WriteAllText(source, Hit, new UTF8Encoding(false));
            var timestamp = new DateTime(2026, 10, 28, 12, 34, 56, DateTimeKind.Utc); File.SetLastWriteTimeUtc(source, timestamp);
            var original = File.ReadAllBytes(source); var sourceHash = SHA256.HashData(original);
            var proof = TraceExportService.Export(source, destination, "2026-10-29T12:34:56+08:00");
            var loaded = TraceExportService.LoadIntegrity(destination);
            check(loaded.Verified && loaded.RawContent == Hit && loaded.ProofSource == "embedded", "Export embeds a valid proof without changing raw no-newline content");
            check(SHA256.HashData(File.ReadAllBytes(source)).SequenceEqual(sourceHash), "Export never changes original trace bytes");
            check(File.GetLastWriteTimeUtc(destination) == timestamp, "Uploader reference date retains the source modification timestamp");
            check(proof.Get("file_name") is EvidenceText { Value: "导出.log" } && ((EvidenceObject)proof.Get("meta")).Get("source_file_name") is EvidenceText { Value: "trace_20261028.log" }, "Export records original name separately from destination name");
            var sameRejected = false;
            try { TraceExportService.Export(source, source); } catch (InvalidOperationException) { sameRejected = true; }
            check(sameRejected && File.ReadAllBytes(source).SequenceEqual(original), "Cannot export onto the original source");
            var content = File.ReadAllText(destination); File.WriteAllText(destination, content.Replace("hit=100", "hit=101", StringComparison.Ordinal));
            var failed = false; var refused = Path.Combine(root, "refused.log");
            try { TraceExportService.Export(destination, refused); } catch (InvalidDataException) { failed = true; }
            check(failed && !File.Exists(refused), "Failed existing proof cannot be re-sealed as a trusted local snapshot");
            File.WriteAllText(source + ".integrity.json", PythonSortedJson.Serialize(RawLogProofs.Build(original, Path.GetFileName(source))));
            check(TraceExportService.LoadIntegrity(source).Verified, "Existing sidecar proof is accepted");
            File.WriteAllText(source + ".status.json", "{\"state\":\"running\"}");
            TraceExportService.Export(source, destination);
            check(File.ReadAllText(source + ".status.json") == "{\"state\":\"running\"}" && TraceExportService.LoadIntegrity(destination).Verified, "Snapshot export preserves live status and reuses valid source proof");
            File.Delete(source + ".integrity.json");
            using (var writer = new FileStream(source, FileMode.Append, FileAccess.Write, FileShare.Read))
            {
                writer.Write(Encoding.UTF8.GetBytes("\n" + Hit.Replace("hit=100", "hit=20", StringComparison.Ordinal) + "\n")); writer.Flush(true);
                TraceExportService.Export(source, destination);
                check(TraceExportService.LoadIntegrity(destination).Verified, "Active trace writer allows a separate stable snapshot export");
            }
            File.WriteAllText(source, "{\"type\":\"damage\"}\n"); failed = false;
            try { TraceExportService.Export(source, refused); } catch (InvalidDataException) { failed = true; }
            check(failed && !File.Exists(refused), "NDJSON event records are not exported as uploader traces");
            check(Directory.GetFiles(root, "*.tmp").Length == 0, "Export leaves no temporary files");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
