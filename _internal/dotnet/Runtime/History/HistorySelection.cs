using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

public sealed record SelectedHistoryEvents(IReadOnlyList<TraceEvent> Events, int Offset);

/// <summary>One indexed battle and its original prefix context. Never carries earlier damage.</summary>
public static class HistorySelection
{
    public static SelectedHistoryEvents Read(HistoryRecord record, SkillResourceCatalog? identities = null,
        TimeZoneInfo? timeZone = null, CancellationToken token = default)
    {
        if (record.SourceStartLine < 0 || record.SourceEndLine <= record.SourceStartLine)
            throw new InvalidDataException("所选战斗没有有效的来源范围，请刷新记录");
        using LiveBattleSession prefix = new(() => throw new InvalidOperationException("Selection never calculates"),
            eventCalculatorFactory: () => throw new InvalidOperationException("Selection never calculates"));
        List<TraceEvent> selected = []; var ordinal = 0;
        void Accept(TraceEvent item) { if (ordinal < record.SourceStartLine) prefix.FeedEvent(item); else selected.Add(item); }
        if (record.StructuredSource is not null)
        {
            var chain = TraceVolumes.Resolve(record.FilePath, token);
            if (!TraceVolumes.SameSources(record.StructuredSource, chain)) throw new InvalidDataException("trace 分卷已变化，请刷新记录后重新加载");
            foreach (var item in TraceVolumes.ReadEvents(chain, token))
            {
                if (ordinal == record.SourceStartLine) selected.AddRange(prefix.HistoryEventContext());
                if (ordinal < record.SourceEndLine) Accept(item);
                ordinal++;
            }
            if (ordinal < record.SourceEndLine || !HistoryCatalog.SourcesUnchanged(record)) throw new InvalidDataException("trace 事件范围已变化，请刷新记录");
            return new(selected, chain.Volumes[0].Header.TimeZoneOffsetMinutes);
        }
        var session = SessionVolumes.Resolve(record.FilePath, token);
        if (record.SessionSource is { } original && !SessionVolumes.RetainsSources(original, session))
            throw new InvalidDataException("原始 session 分卷已变化或不完整，请刷新记录后重新加载");
        if (record.SourcePrefixSha256.Length == 0 && !HistoryCatalog.SourcesUnchanged(record))
            throw new InvalidDataException("session 分卷已变化，请刷新记录");
        var offset = session.Volumes[0].Header?.TimeZoneOffsetMinutes
            ?? (int)(timeZone ?? TimeZoneInfo.Local).GetUtcOffset(DateTimeOffset.FromUnixTimeMilliseconds(record.StartedAtMs)).TotalMinutes;
        var zone = TimeZoneInfo.CreateCustomTimeZone("session-selection", TimeSpan.FromMinutes(offset), "session-selection", "session-selection");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Selection emitted legacy text"), identities, zone, eventSink: Accept);
        foreach (var raw in SessionVolumes.ReadLines(session, token, allowAppend: record.SourcePrefixSha256.Length > 0).Take(record.SourceEndLine))
        {
            token.ThrowIfCancellationRequested();
            if (ordinal == record.SourceStartLine) selected.AddRange(prefix.HistoryEventContext());
            hash.AppendData(Encoding.UTF8.GetBytes(raw.TrimEnd('\r') + "\n"));
            EvidenceValue value;
            try { value = EvidenceJson.Parse(raw); } catch (FormatException) { ordinal++; continue; }
            if (value is not EvidenceObject row) throw new InvalidDataException("日志事件应为对象");
            bridge.Handle(row); ordinal++;
        }
        bridge.EndCaptureSession();
        if (ordinal != record.SourceEndLine || record.SourcePrefixSha256.Length > 0
            && Convert.ToHexStringLower(hash.GetCurrentHash()) != record.SourcePrefixSha256)
            throw new InvalidDataException("所选战斗的原始 session 内容已变化，请刷新记录后重新加载");
        return new(selected, offset);
    }
}
