using System.Globalization;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

/// <summary>On-demand bounded replay through the production ingestion and canonical report pipeline.</summary>
public sealed partial class HistoryAnalyzer(ResourceFiles files, TimeZoneInfo? timeZone = null)
{
    private sealed record Resources(BattleIngestionResources Ingestion, Lazy<BattleReportAnalysis> Analysis, SkillResourceCatalog Identities);
    private readonly Lazy<Resources> resources = new(() => new(BattleIngestionResources.Load(files), new(() => BattleReportAnalysis.Load(files, timeZone)), new(files)));
    private static readonly UTF8Encoding Utf8 = new(false, true);
    public Task<EvidenceObject> AnalyzeAsync(HistoryRecord record, CancellationToken cancellationToken = default) =>
        Task.Run(() => Analyze(record, cancellationToken), cancellationToken);
    public EvidenceObject Analyze(HistoryRecord record, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (record.StructuredSource is not null) return AnalyzeStructured(record, cancellationToken);
        if (!record.IsTrace) return AnalyzeSession(record, cancellationToken);
        var shared = resources.Value; var text = ReadTrace(record, cancellationToken);
        BattleIngestionStream stream = new(shared.Ingestion); var lineNumber = 0;
        foreach (var line in PythonTextLines.Split(text)) { cancellationToken.ThrowIfCancellationRequested(); stream.Accept(++lineNumber, line); }
        var date = DateOnly.ParseExact(record.ReferenceDate, "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var full = shared.Analysis.Value.BuildHistorySnapshot(stream, date, text, Path.GetFileName(record.FilePath),
            lastHitHintMs: TraceFields.HintTimestampMs(record.LastHitHint), cancellationToken: cancellationToken);
        if (full is null || full.Get("battle") is not EvidenceObject battle || !TraceData.Truth(battle.Get("total_damage")))
            throw new InvalidDataException("所选记录没有可供 canonical parser 分析的伤害行");
        return full;
    }
    private static string ReadTrace(HistoryRecord record, CancellationToken token)
    {
        if (HistoryFileSignature.Read(record.FilePath) != record.SourceSignature) throw new InvalidDataException("原始 trace 日志已变化，请刷新记录后重新加载");
        using FileStream file = new(record.FilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        if (record.SourceByteStart < 0 || record.SourceByteEnd < record.SourceByteStart || record.SourceByteEnd > file.Length) throw new InvalidDataException("历史记录来源范围无效，请刷新记录");
        file.Position = record.SourceByteStart;
        var remaining = record.SourceByteEnd - record.SourceByteStart;
        byte[] bytes = new byte[64 * 1024]; char[] characters = new char[Utf8.GetMaxCharCount(bytes.Length)];
        var decoder = Utf8.GetDecoder(); StringBuilder text = new();
        while (remaining > 0)
        {
            token.ThrowIfCancellationRequested();
            var count = (int)Math.Min(remaining, bytes.Length); file.ReadExactly(bytes.AsSpan(0, count)); remaining -= count;
            var decoded = decoder.GetChars(bytes, 0, count, characters, 0, flush: remaining == 0);
            text.Append(characters, 0, decoded);
        }
        token.ThrowIfCancellationRequested();
        if (HistoryFileSignature.Read(record.FilePath) != record.SourceSignature) throw new InvalidDataException("原始 trace 日志已变化，请刷新记录后重新加载");
        return PythonDisplay.Strip(text.ToString());
    }
    public static HistoryRecord ApplySummary(HistoryRecord record, EvidenceObject snapshot)
    {
        var battle = TraceData.Obj(snapshot.Get("battle"));
        var players = TraceData.Rows(snapshot.Get("participants")).Select((row, index) => new HistoryPlayer(index,
            TraceData.Text(row.Get("character_name"), TraceData.S(row.Get("character_key"))), TraceData.S(row.Get("character_key")), index,
            TraceData.Float(row.Get("total_damage")) ?? 0, TraceData.Float(row.Get("max_hit")) ?? 0, (int)(TraceData.Int(row.Get("crit_hits")) ?? 0), (int)(TraceData.Int(row.Get("hit_count")) ?? 0))).ToArray();
        return record with { TotalDamage = TraceData.Float(battle.Get("total_damage")) ?? 0, DurationMs = (long)(TraceData.Int(battle.Get("duration_ms")) ?? 0), Players = players, AnalysisLoaded = true };
    }
}
