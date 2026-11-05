using System.Text;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Integrity;
using EndfieldLogs.Runtime.Storage;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Runtime.History;

/// <summary>Read-only raw source and atomic snapshot export, compatible with the existing official uploader.</summary>
public static partial class TraceExportService
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    [GeneratedRegex(@"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] HP_V2\s+#\d+\b", RegexOptions.Multiline)]
    private static partial Regex DamageLine();
    public static RawLogIntegrityResult LoadIntegrity(string path)
    {
        using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using MemoryStream content = new(); stream.CopyTo(content);
        var text = Utf8.GetString(content.ToArray());
        var embedded = RawLogProofs.Inspect(text);
        if (embedded.ProofSource == "embedded") return embedded;
        foreach (var candidate in new[] { path + ".integrity.json", Path.ChangeExtension(path, ".integrity.json") })
        {
            if (!File.Exists(candidate)) continue;
            var proof = EvidenceJson.Parse(Utf8.GetString(File.ReadAllBytes(candidate))) as EvidenceObject ?? throw new InvalidDataException("完整性证明应为对象");
            return RawLogProofs.Inspect(text, proof, candidate);
        }
        return embedded;
    }

    public static EvidenceObject Export(string source, string destination, string? exportedAt = null)
    {
        source = Path.GetFullPath(source); destination = Path.GetFullPath(destination);
        if (string.Equals(PhysicalPaths.Resolve(source), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("请另存导出文件，不能覆盖原始 trace");
        TraceVolumeChain? chain = null;
        SessionVolumeChain? session = null;
        RawLogIntegrityResult integrity;
        if (Path.GetExtension(source).Equals(".ndjson", StringComparison.OrdinalIgnoreCase))
        {
            session = SessionVolumes.Resolve(source);
            if (!session.IsComplete) throw new InvalidDataException(string.Join('；', session.Issues));
            if (session.Volumes[0].Header is { } header)
            {
                if (session.Volumes.Any(volume => string.Equals(PhysicalPaths.Resolve(volume.FilePath), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)))
                    throw new InvalidOperationException("请另存导出文件，不能覆盖原始 session 分卷");
                chain = TraceVolumes.Find(Path.GetDirectoryName(source)!, header.TraceRecordingId)
                    ?? throw new FileNotFoundException("找不到此 session 配套的 JSONL trace，请恢复原录制文件后重试");
                if (session.Volumes.Any(volume => !chain.Volumes.Any(trace => trace.Header.Volume == volume.Header!.TraceVolume
                    && trace.Header.TimeZoneOffsetMinutes == volume.Header.TimeZoneOffsetMinutes)))
                    throw new InvalidDataException("session 配套的 trace 分卷缺失或时区不一致");
            }
        }
        else if (Path.GetExtension(source).Equals(".jsonl", StringComparison.OrdinalIgnoreCase)) chain = TraceVolumes.Resolve(source);
        if (chain is not null)
        {
            if (chain.Volumes.Any(volume => string.Equals(PhysicalPaths.Resolve(volume.FilePath), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)))
                throw new InvalidOperationException("请另存导出文件，不能覆盖原始 trace 分卷");
            using StringWriter body = new(System.Globalization.CultureInfo.InvariantCulture);
            TraceLegacyExporter.Write(chain, body);
            integrity = RawLogProofs.Inspect(body.ToString());
        }
        else integrity = LoadIntegrity(source);
        if (integrity.Issues.Count > 0 && !integrity.Issues.SequenceEqual(["missing integrity proof"]))
            throw new InvalidDataException("原日志完整性校验失败：" + string.Join('；', integrity.Issues));
        if (!DamageLine().IsMatch(integrity.RawContent)) throw new InvalidDataException("请选择含伤害记录的 trace_*.log；session_*.ndjson 不是 uploader 日志");
        EvidenceObject meta = new(new Dictionary<string, EvidenceValue>
        {
            ["exporter"] = new EvidenceText("endfield-pcap-gui"), ["source_file_name"] = new EvidenceText(Path.GetFileName(source)), ["scope"] = new EvidenceText("full_trace_snapshot"),
        });
        if (chain is not null)
        {
            var fields = meta.Fields.ToDictionary();
            fields["source_recording_id"] = new EvidenceText(chain.Volumes[0].Header.RecordingId);
            fields["source_volumes"] = new EvidenceArray(chain.Volumes.Select(volume => (EvidenceValue)new EvidenceText(Path.GetFileName(volume.FilePath))).ToArray());
            meta = new(fields);
        }
        if (session?.Volumes[0].Header is { } sessionHeader)
        {
            var fields = meta.Fields.ToDictionary();
            fields["source_session_recording_id"] = new EvidenceText(sessionHeader.RecordingId);
            fields["source_session_volumes"] = new EvidenceArray(session.Volumes.Select(volume => (EvidenceValue)new EvidenceText(Path.GetFileName(volume.FilePath))).ToArray());
            meta = new(fields);
        }
        return WriteExport(source, destination, integrity.RawContent, meta, exportedAt);
    }

    public static EvidenceObject ExportBattle(HistoryRecord record, string destination, SkillResourceCatalog? identities = null)
    {
        var source = Path.GetFullPath(record.FilePath); destination = Path.GetFullPath(destination);
        if (string.Equals(PhysicalPaths.Resolve(source), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)
            || record.StructuredSource?.Volumes.Any(volume => string.Equals(PhysicalPaths.Resolve(volume.FilePath), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)) == true
            || record.SessionSource?.Volumes.Any(volume => string.Equals(PhysicalPaths.Resolve(volume.FilePath), PhysicalPaths.Resolve(destination), StringComparison.OrdinalIgnoreCase)) == true)
            throw new InvalidOperationException("请另存导出文件，不能覆盖原始日志分卷");
        string text;
        if (record.IsTrace && record.StructuredSource is null)
        {
            if (!HistoryCatalog.SourcesUnchanged(record)) throw new InvalidDataException("原始 trace 已变化，请刷新记录后重新导出");
            var integrity = LoadIntegrity(source);
            if (integrity.Issues.Count > 0 && !integrity.Issues.SequenceEqual(["missing integrity proof"]))
                throw new InvalidDataException("原日志完整性校验失败：" + string.Join('；', integrity.Issues));
            text = string.Concat(PythonTextLines.SplitKeepEnds(integrity.RawContent).Skip(record.SourceStartLine).Take(record.SourceEndLine - record.SourceStartLine));
            if (!HistoryCatalog.SourcesUnchanged(record)) throw new InvalidDataException("原始 trace 已变化，请刷新记录后重新导出");
        }
        else
        {
            // A growing final battle may have gained hits or its official end.
            // Refresh its bounds, then validate the original prefix before using them.
            var fresh = record.StructuredSource is null
                ? new HistoryCatalog().Read(source, false).SingleOrDefault(row => row.RecordIndex == record.RecordIndex && row.StartedAtMs == record.StartedAtMs)
                    ?? throw new InvalidDataException("所选战斗的来源范围已变化，请刷新记录")
                : record;
            var selected = HistorySelection.Read(record, identities);
            if (fresh.SourcePrefixSha256 != record.SourcePrefixSha256) selected = HistorySelection.Read(fresh, identities);
            record = fresh;
            text = string.Concat(selected.Events.SelectMany(item => TraceLegacyExporter.Lines(item, selected.Offset)));
        }
        if (!DamageLine().IsMatch(text)) throw new InvalidDataException("所选战斗没有可导出的伤害证据");
        EvidenceObject meta = new(new Dictionary<string, EvidenceValue>
        {
            ["exporter"] = new EvidenceText("endfield-pcap-gui"), ["source_file_name"] = new EvidenceText(Path.GetFileName(source)),
            ["scope"] = new EvidenceText("selected_battle"), ["battle_index"] = new EvidenceInteger(record.RecordIndex),
            ["source_start_line"] = new EvidenceInteger(record.SourceStartLine), ["source_end_line"] = new EvidenceInteger(record.SourceEndLine),
        });
        return WriteExport(source, destination, text, meta, sourceDate: DateTimeOffset.FromUnixTimeMilliseconds(record.StartedAtMs).UtcDateTime);
    }

    private static EvidenceObject WriteExport(string source, string destination, string rawContent, EvidenceObject meta,
        string? exportedAt = null, DateTime? sourceDate = null)
    {
        var proof = RawLogProofs.Build(Utf8.GetBytes(rawContent), Path.GetFileName(destination), exportedAt, meta);
        var separator = rawContent.Length > 0 && !rawContent.EndsWith('\n');
        var text = rawContent + (separator ? "\n" : "") + RawLogProofs.Begin + (separator ? "1" : "0") + "\n"
            + PythonSortedJson.Serialize(proof) + "\n" + RawLogProofs.End + "\n";
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        var temporary = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (FileStream output = new(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { output.Write(Utf8.GetBytes(text)); output.Flush(flushToDisk: true); }
            File.SetLastWriteTimeUtc(temporary, sourceDate ?? File.GetLastWriteTimeUtc(source));
            File.Move(temporary, destination, overwrite: true);
        }
        finally { File.Delete(temporary); }
        return proof;
    }
}
