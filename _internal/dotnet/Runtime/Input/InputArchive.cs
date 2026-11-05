using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

/// <summary>Input sidecar index and interpreted intentions; raw motion is read only for the selected battle.</summary>
public sealed class InputArchive
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly List<(BigInteger WallNs, long Offset)> index = [];
    private readonly List<string> warnings = [];
    private readonly Dictionary<string, EvidenceValue> devices = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> counts = new(StringComparer.Ordinal);
    private readonly IReadOnlyList<InputIntention> actions;
    private EvidenceObject header = new(new Dictionary<string, EvidenceValue>());
    private EvidenceObject? digest;
    public string Path { get; }
    public bool WallOrdered { get; private set; } = true;
    public IReadOnlyList<string> Warnings => warnings.ToArray();
    public IReadOnlyDictionary<string, int> InputCounts => new Dictionary<string, int>(counts);
    public IReadOnlyList<InputIntention> Actions => actions.Select(row => row with { Keys = row.Keys.ToArray() }).ToArray();
    public EvidenceObject Header => (EvidenceObject)EvidenceJson.Clone(header);
    public EvidenceObject Devices => (EvidenceObject)EvidenceJson.Clone(new EvidenceObject(devices));
    public EvidenceObject? Digest => digest is null ? null : (EvidenceObject)EvidenceJson.Clone(digest);
    private static BigInteger Integer(EvidenceValue value) => TraceData.Int(value) ?? throw new InvalidDataException("输入日志数值无效");
    public InputArchive(string path, EvidenceValue? settings = null, CancellationToken cancellationToken = default)
    {
        Path = System.IO.Path.GetFullPath(path); InputInterpreter interpreter = new(settings);
        var ended = false; BigInteger? previousSequence = null, lastSecond = null; BigInteger previousStamp = 0;
        using FileStream stream = new(Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        foreach (var (offset, raw) in Lines(stream, cancellationToken))
        {
            EvidenceObject e;
            try { e = Parse(raw) ?? throw new FormatException("JSON record is not an object"); }
            catch (Exception error) when (error is FormatException or DecoderFallbackException)
            {
                warnings.Add($"偏移 {offset}：记录不完整 / 损坏");
                interpreter.Interrupt(interpreter.Last ?? TraceData.Make(("wall_ns", 0)), "malformed_record"); continue;
            }
            var type = TraceData.S(e.Get("type"));
            if (header.Fields.Count == 0)
            {
                if (type != "session" || !EvidenceJson.PythonEquals(e.Get("schema_version"), new EvidenceInteger(1))) throw new InvalidDataException("不支持的输入日志版本");
                header = e;
            }
            var sequence = e.Get("seq");
            if (sequence is not EvidenceNull)
            {
                var number = Integer(sequence);
                if (previousSequence is { } previous)
                {
                    if (number <= previous) throw new InvalidDataException("输入日志序号未递增");
                    if (number > previous + 1)
                    { if (warnings.Count < 100) warnings.Add($"序号 {previous + 1}–{number - 1} 缺失"); interpreter.Interrupt(e, "sequence_gap"); }
                }
                previousSequence = number + (type == "gap" ? BigInteger.Max(1, Integer(e.Fields.GetValueOrDefault("count") ?? new EvidenceInteger(1))) - 1 : 0);
            }
            var stamp = Integer(e.Fields.GetValueOrDefault("wall_ns") ?? e.Fields.GetValueOrDefault("start_wall_ns") ?? new EvidenceInteger(0));
            if (!stamp.IsZero) { if (stamp < previousStamp) WallOrdered = false; previousStamp = stamp; }
            var second = BigInteger.DivRem(stamp, 1_000_000_000, out var remainder); if (remainder.Sign < 0) second--;
            if (!stamp.IsZero && second != lastSecond) { index.Add((stamp, offset)); lastSecond = second; }
            if (type == "gap") warnings.Add("记录缺失 " + TraceData.S(e.Fields.GetValueOrDefault("missing_events") ?? e.Fields.GetValueOrDefault("count") ?? new EvidenceInteger(0)) + " 条");
            if (type == "diagnostic" && e.Get("reason") is EvidenceText { Value: "input_state_sampling_fallback" })
                warnings.Add("输入使用状态采样（" + TraceData.S(e.Fields.GetValueOrDefault("sample_interval_ms") ?? new EvidenceInteger(8)) + "ms），不含完整原始设备事件");
            if (type == "device") devices[TraceData.S(e.Get("device"))] = e;
            if (type == "input") Increment(counts, TraceData.S(e.Fields.GetValueOrDefault("kind") ?? new EvidenceText("other")));
            if (type == "trace_digest") digest = e;
            if (type == "end") ended = true;
            interpreter.Feed(e);
        }
        actions = interpreter.Close();
        if (!ended) warnings.Add("录制尚未结束或未正常结束，末尾按住区间按中断处理");
        if (warnings.Count > 100) { warnings.RemoveRange(100, warnings.Count - 100); warnings.Add("更多诊断已省略"); }
    }
    internal static void Increment(Dictionary<string, int> values, string key) => values[key] = values.GetValueOrDefault(key) + 1;
    internal static EvidenceObject? Parse(byte[] raw)
    {
        var offset = raw.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) ? 3 : 0;
        return EvidenceJson.Parse(Utf8.GetString(raw.AsSpan(offset))) as EvidenceObject;
    }
    // LF byte records retain physical offsets, including a partial final record.
    internal static IEnumerable<(long Offset, byte[] Raw)> Lines(FileStream stream, CancellationToken token)
    {
        using MemoryStream line = new(); var offset = stream.Position; var position = offset; byte[] buffer = new byte[64 * 1024]; int count;
        while ((count = stream.Read(buffer)) > 0)
        {
            token.ThrowIfCancellationRequested(); var start = 0;
            for (var at = 0; at < count; at++)
            {
                if (buffer[at] != (byte)'\n') continue;
                line.Write(buffer.AsSpan(start, at - start + 1)); yield return (offset, line.ToArray());
                line.SetLength(0); offset = position + at + 1; start = at + 1;
            }
            line.Write(buffer.AsSpan(start, count - start)); position += count;
        }
        if (line.Length > 0) yield return (offset, line.ToArray());
    }
    public string VerifyTrace(string trace, CancellationToken cancellationToken = default)
    {
        if (digest is null) return "未附 trace 摘要（录制可能仍在运行）";
        var size = checked((long)Integer(digest.Get("bytes")));
        using FileStream source = new(trace, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        if (source.Length < size) throw new InvalidDataException("trace 长度与输入日志关联摘要不匹配");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256); byte[] buffer = new byte[1024 * 1024]; var remaining = size;
        while (remaining > 0)
        {
            cancellationToken.ThrowIfCancellationRequested(); var count = source.Read(buffer, 0, (int)Math.Min(remaining, buffer.Length));
            if (count == 0) throw new InvalidDataException("trace 在校验期间发生变化");
            hash.AppendData(buffer, 0, count); remaining -= count;
        }
        if (Convert.ToHexStringLower(hash.GetHashAndReset()) != TraceData.S(digest.Get("sha256"))) throw new InvalidDataException("trace 与输入日志关联摘要不匹配；请手动核对来源");
        return "已校验 trace 关联";
    }
    public IReadOnlyList<EvidenceObject> RawRange(BigInteger startNs, BigInteger endNs, InputInterpretationSettings settings,
        Dictionary<string, int>? selectedCounts = null, CancellationToken cancellationToken = default)
    {
        using FileStream stream = new(Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        var offsets = index.OrderBy(row => row.WallNs).ThenBy(row => row.Offset).ToArray();
        var at = Array.FindLastIndex(offsets, row => row.WallNs <= startNs); at = Math.Max(0, at);
        if (WallOrdered && offsets.Length > 0) stream.Position = offsets[at].Offset;
        List<EvidenceObject> result = [];
        foreach (var (_, raw) in Lines(stream, cancellationToken))
        {
            EvidenceObject? e; try { e = Parse(raw); } catch (Exception error) when (error is FormatException or DecoderFallbackException) { continue; }
            if (e is null) continue;
            var stamp = Integer(e.Fields.GetValueOrDefault("wall_ns") ?? new EvidenceInteger(0));
            if (stamp > endNs) { if (WallOrdered) break; continue; }
            if (stamp < startNs || e.Get("type") is not EvidenceText { Value: "input" }) continue;
            var kind = e.Get("kind") is EvidenceText text ? text.Value : "other";
            if (selectedCounts is not null) Increment(selectedCounts, kind.Length == 0 ? "other" : kind);
            if (kind == "motion" ? !settings.ShowMotion : kind is "axis" or "hat" or "sensor" or "touch" or "other" ? !settings.ShowAxes : !settings.ShowOther) continue;
            result.Add(e);
        }
        return result;
    }
}
