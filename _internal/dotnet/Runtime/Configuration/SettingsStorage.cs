using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Configuration;

/// <summary>UTF-8, valid-old-file backup and same-directory durable replacement.</summary>
public sealed class SettingsStorage(Action<string, Exception?>? diagnostic = null)
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static EvidenceObject Parse(byte[] content) => EvidenceJson.Parse(Utf8.GetString(content)) as EvidenceObject
        ?? throw new FormatException("配置根节点应为对象");
    public EvidenceObject Read(string path)
    {
        foreach (var candidate in new[] { path, path + ".bak" })
        {
            if (!File.Exists(candidate)) continue;
            EvidenceObject payload;
            try { payload = Parse(File.ReadAllBytes(candidate)); }
            catch (Exception error) when (error is FormatException or DecoderFallbackException)
            {
                diagnostic?.Invoke("配置损坏：" + candidate, error);
                if (candidate == path)
                {
                    var preserved = path + ".corrupt-" + Guid.NewGuid().ToString("N")[..10];
                    try { File.Move(path, preserved); diagnostic?.Invoke("损坏配置保留于：" + preserved, null); }
                    catch (Exception moveError) when (moveError is IOException or UnauthorizedAccessException)
                    { diagnostic?.Invoke("无法保留损坏配置原文件：" + path, moveError); }
                }
                continue;
            }
            if (candidate != path) diagnostic?.Invoke("已从备份恢复配置：" + candidate, null);
            return payload;
        }
        return SettingsData.Empty();
    }

    public void Write(string path, EvidenceObject payload)
    {
        // Validate before touching either existing file.
        var content = Utf8.GetBytes(TraceData.Json(payload, finite: true));
        path = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        if (File.Exists(path))
        {
            var previous = File.ReadAllBytes(path); var valid = true;
            try { Parse(previous); }
            catch (Exception error) when (error is FormatException or DecoderFallbackException) { valid = false; }
            if (valid) AtomicWrite(path + ".bak", previous);
        }
        AtomicWrite(path, content);
    }

    private static void AtomicWrite(string path, byte[] content)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (FileStream stream = new(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(content); stream.Flush(flushToDisk: true); }
            for (var attempt = 0; ; attempt++)
            {
                try { File.Move(temporary, path, overwrite: true); break; }
                catch (Exception error) when (attempt < 5 && (error is UnauthorizedAccessException || error is IOException && (error.HResult & 0xffff) is 5 or 32 or 33))
                { Thread.Sleep(10 << attempt); }
            }
        }
        finally { File.Delete(temporary); }
    }
}
