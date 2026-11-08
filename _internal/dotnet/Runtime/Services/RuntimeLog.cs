using System.Text;

namespace EndfieldLogs.Runtime.Services;

/// <summary>Bounded, immediately flushed application diagnostics, independent of battle recording.</summary>
public sealed class RuntimeLog : IDisposable
{
    private readonly object gate = new();
    private readonly long limit;
    private StreamWriter? writer;
    private bool disposed;
    public string Path { get; }
    public string? Error { get; private set; }

    public RuntimeLog(string path, long maxBytes = 5 * 1024 * 1024)
    { Path = System.IO.Path.GetFullPath(path); limit = maxBytes; }

    public string Write(string message, Exception? exception = null)
    {
        var line = $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss.fff zzz} {(exception is null ? "INFO" : "ERROR")} {message}";
        if (exception is not null) line += Environment.NewLine + exception;
        lock (gate)
        {
            if (disposed) return line;
            try
            {
                Directory.CreateDirectory(System.IO.Path.GetDirectoryName(Path)!);
                if (writer is null || writer.BaseStream.Length >= limit)
                {
                    writer?.Dispose(); writer = null;
                    if (File.Exists(Path) && new FileInfo(Path).Length >= limit)
                    {
                        if (File.Exists(Path + ".1")) File.Move(Path + ".1", Path + ".2", overwrite: true);
                        File.Move(Path, Path + ".1", overwrite: true);
                    }
                    writer = new(new FileStream(Path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite), new UTF8Encoding(false)) { AutoFlush = true };
                }
                writer.WriteLine(line); Error = null;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            { writer?.Dispose(); writer = null; Error = error.Message; }
        }
        return line;
    }
    public void Dispose() { lock (gate) { if (disposed) return; disposed = true; writer?.Dispose(); writer = null; } }
}
