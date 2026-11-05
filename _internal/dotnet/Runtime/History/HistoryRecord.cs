using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

public sealed record HistoryFileSignature(long ModifiedNanoseconds, long ByteSize)
{
    public static HistoryFileSignature Read(string path)
    {
        FileInfo file = new(path); file.Refresh();
        if (!file.Exists) throw new FileNotFoundException("日志文件不存在", path);
        return new(checked((file.LastWriteTimeUtc.Ticks - DateTime.UnixEpoch.Ticks) * 100), file.Length);
    }
}
public sealed record HistoryPlayer(BigInteger BattleInstanceId, string DisplayName, string? TemplateId, int SquadIndex,
    double TotalDamage = 0, double MaxDamage = 0, int CritCount = 0, int HitCount = 0)
{
    public double CritRate => HitCount <= 0 ? 0 : (double)CritCount / HitCount * 100;
}
public sealed record HistoryRecord(string FilePath, int RecordIndex, long StartedAtMs, string Label,
    IReadOnlyList<HistoryPlayer> Players, double TotalDamage, long DurationMs, int SourceStartLine, int SourceEndLine,
    bool AnalysisLoaded, bool IsTrace, HistoryFileSignature SourceSignature, long SourceByteStart = 0,
    long SourceByteEnd = 0, string LastHitHint = "", string ReferenceDate = "", TraceVolumeChain? StructuredSource = null,
    SessionVolumeChain? SessionSource = null, string SourcePrefixSha256 = "")
{
    public string Key => PythonSortedJson.Serialize(new EvidenceArray([new EvidenceText(Path.GetFullPath(FilePath).Replace('/', '\\').ToLowerInvariant()),
        new EvidenceInteger(RecordIndex), new EvidenceInteger(StartedAtMs)]));
    public double Dps => DurationMs <= 0 ? 0 : TotalDamage / (DurationMs / 1000.0);
}
