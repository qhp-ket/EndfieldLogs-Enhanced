using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

public sealed partial class HistoryAnalyzer
{
    private readonly object structuredGate = new();
    private (int Offset, BattleReportAnalysis Analysis)? structuredAnalysis;

    private BattleReportAnalysis StructuredAnalysis(int offset)
    {
        lock (structuredGate)
        {
            if (structuredAnalysis is { } previous && previous.Offset == offset) return previous.Analysis;
            var zone = TimeZoneInfo.CreateCustomTimeZone("trace-recording", TimeSpan.FromMinutes(offset), "trace-recording", "trace-recording");
            var analysis = BattleReportAnalysis.Load(files, zone);
            structuredAnalysis = (offset, analysis); return analysis;
        }
    }

    private EvidenceObject AnalyzeSession(HistoryRecord record, CancellationToken token) => AnalyzeSelected(record, token);
    private EvidenceObject AnalyzeStructured(HistoryRecord record, CancellationToken token) => AnalyzeSelected(record, token);
    private EvidenceObject AnalyzeSelected(HistoryRecord record, CancellationToken token)
    {
        var selected = HistorySelection.Read(record, resources.Value.Identities, timeZone, token);
        BattleIngestionStream stream = new(resources.Value.Ingestion); var evidence = 0;
        foreach (var item in selected.Events)
        {
            token.ThrowIfCancellationRequested();
            var stamp = DateTimeOffset.FromUnixTimeMilliseconds(item.CapturedAtMs).ToOffset(TimeSpan.FromMinutes(selected.Offset)).TimeOfDay.Ticks / TimeSpan.TicksPerMillisecond;
            if (stream.TimestampClockOrigin is { } origin) stamp = origin + ((stamp - origin) % 86_400_000 + 86_400_000) % 86_400_000;
            stream.Accept(++evidence, item with { CapturedAtMs = stamp });
        }
        var full = StructuredAnalysis(selected.Offset).BuildHistorySnapshot(stream, selected.ReferenceDate, "", Path.GetFileName(record.FilePath), cancellationToken: token);
        if (full?.Get("battle") is not EvidenceObject battle || !TraceData.Truth(battle.Get("total_damage")))
            throw new InvalidDataException("所选记录没有可供分析的伤害事件");
        return full;
    }
}
