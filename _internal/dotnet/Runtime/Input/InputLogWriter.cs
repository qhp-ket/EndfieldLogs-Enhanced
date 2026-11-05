using System.Collections.Concurrent;
using System.Diagnostics;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public readonly record struct InputTimestamp(BigInteger WallNs, BigInteger MonoNs)
{
    public static InputTimestamp Now() => new((DateTime.UtcNow.Ticks - DateTime.UnixEpoch.Ticks) * (BigInteger)100,
        (BigInteger)Stopwatch.GetTimestamp() * 1_000_000_000 / Stopwatch.Frequency);
    public EvidenceObject ToEvidence() => TraceData.Make(("wall_ns", WallNs), ("mono_ns", MonoNs));
}

/// <summary>Schema-v1 sidecar writer. Producers never wait for disk; the single writer owns the stream.</summary>
public sealed class InputLogWriter : IDisposable
{
    private readonly BlockingCollection<EvidenceObject> queue;
    private readonly Thread worker;
    private readonly StreamWriter output;
    private readonly string? trace;
    private readonly Func<InputTimestamp> clock;
    private readonly object gate = new();
    private EvidenceObject? gap;
    private long sequence, count, lost;
    private bool closing;
    private Exception? error;
    public string Path { get; }
    public long Count => Interlocked.Read(ref count);
    public long Lost => Interlocked.Read(ref lost);
    public Exception? Error => Volatile.Read(ref error);
    public bool Completed => !worker.IsAlive;

    public InputLogWriter(string path, string? trace = null, int capacity = 32768, string? session = null,
        Func<InputTimestamp>? clock = null)
        : this(path, trace, capacity, session, clock, null) { }

    // Stream injection is internal, for actual backpressure and failing-storage contracts.
    internal InputLogWriter(string path, string? trace, int capacity, string? session, Func<InputTimestamp>? clock, Stream? stream)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(capacity, 1);
        Path = System.IO.Path.GetFullPath(path); this.trace = trace; this.clock = clock ?? InputTimestamp.Now;
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
        output = new(stream ?? new FileStream(Path, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 256 * 1024),
            new UTF8Encoding(false, true), 256 * 1024);
        queue = new(capacity);
        try
        {
            var stamp = this.clock();
            Write(TraceData.Make(("type", "session"), ("schema_version", 1), ("session_id", session ?? Guid.NewGuid().ToString("N")),
                ("trace_name", trace is null ? null : System.IO.Path.GetFileName(trace)), ("clock", "unix_ns + perf_counter_ns"),
                ("wall_ns", stamp.WallNs), ("mono_ns", stamp.MonoNs)));
            output.Flush();
        }
        catch { output.Dispose(); queue.Dispose(); throw; }
        worker = new(Run) { Name = "input-jsonl", IsBackground = true }; worker.Start();
    }
    public static string Companion(string trace) => System.IO.Path.ChangeExtension(trace, ".input.jsonl");
    public bool Put(string type, EvidenceObject? fields = null)
    {
        lock (gate)
        {
            if (closing) throw new ObjectDisposedException(nameof(InputLogWriter));
            if (Error is { } failure) throw new IOException("输入日志写入失败", failure);
            var stamp = clock();
            var values = TraceData.Make(("type", type), ("seq", ++sequence), ("wall_ns", stamp.WallNs), ("mono_ns", stamp.MonoNs)).Fields.ToDictionary();
            if (fields is not null) foreach (var (key, value) in fields.Fields) values[key] = EvidenceJson.Clone(value);
            var item = new EvidenceObject(values);
            if (gap is not null && queue.TryAdd(gap)) gap = null;
            if (gap is null && queue.TryAdd(item)) { Interlocked.Increment(ref count); return true; }
            Interlocked.Increment(ref lost);
            var missing = gap?.Fields.ToDictionary() ?? TraceData.Make(("type", "gap"), ("seq", sequence),
                ("start_wall_ns", item.Get("wall_ns")), ("start_mono_ns", item.Get("mono_ns")), ("count", 0)).Fields.ToDictionary();
            missing["count"] = new EvidenceInteger((TraceData.Int(missing["count"]) ?? 0) + 1);
            missing["end_wall_ns"] = item.Get("wall_ns"); missing["end_mono_ns"] = item.Get("mono_ns"); gap = new(missing);
            return false;
        }
    }
    private void Write(EvidenceObject item) { output.Write(TraceData.Json(item, finite: true)); output.Write('\n'); }
    private void Run()
    {
        try
        {
            var flushed = Stopwatch.GetTimestamp();
            while (!queue.IsCompleted)
            {
                if (queue.TryTake(out var item, 250)) Write(item);
                if (Stopwatch.GetElapsedTime(flushed).TotalMilliseconds >= 250)
                { output.Flush(); flushed = Stopwatch.GetTimestamp(); }
            }
            if (trace is not null && File.Exists(trace)) AppendTraceDigest(trace);
        }
        catch (Exception failure) { Volatile.Write(ref error, failure); }
        finally
        {
            try { output.Dispose(); } catch (Exception failure) { Interlocked.CompareExchange(ref error, failure, null); }
        }
    }
    private void AppendTraceDigest(string sourcePath)
    {
        using FileStream source = new(sourcePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        var size = source.Length; long read = 0;
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256); byte[] bytes = new byte[1024 * 1024];
        while (read < size)
        { var got = source.Read(bytes, 0, (int)Math.Min(bytes.Length, size - read)); if (got == 0) break; hash.AppendData(bytes, 0, got); read += got; }
        Write(TraceData.Make(("type", "trace_digest"), ("name", System.IO.Path.GetFileName(sourcePath)), ("bytes", read),
            ("sha256", Convert.ToHexStringLower(hash.GetHashAndReset())), ("scope", "prefix")));
    }
    public void Close(string reason = "stopped", TimeSpan? timeout = null)
    {
        var budget = timeout ?? TimeSpan.FromSeconds(5); var started = Stopwatch.GetTimestamp();
        lock (gate)
        {
            if (!closing)
            {
                closing = true;
                try
                {
                    if (gap is not null) Final(gap); gap = null;
                    var stamp = clock(); Final(TraceData.Make(("type", "end"), ("reason", reason), ("wall_ns", stamp.WallNs), ("mono_ns", stamp.MonoNs)));
                }
                finally { queue.CompleteAdding(); }
            }
        }
        var remaining = budget - Stopwatch.GetElapsedTime(started);
        if (worker.IsAlive && (remaining <= TimeSpan.Zero || !worker.Join(remaining))) throw new IOException("输入日志写入未能结束");
        if (Error is { } failure) throw new IOException("输入日志写入失败：" + failure.Message, failure);
        void Final(EvidenceObject item)
        {
            while (worker.IsAlive && Error is null)
            {
                var left = budget - Stopwatch.GetElapsedTime(started);
                if (left <= TimeSpan.Zero) throw new IOException("输入日志写入未能结束");
                if (queue.TryAdd(item, (int)Math.Min(100, Math.Ceiling(left.TotalMilliseconds)))) return;
            }
        }
    }
    public void Dispose() => Close();
}
