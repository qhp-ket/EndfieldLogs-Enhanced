using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

public static class HistoryFiles
{
    public static string RenamedPath(string source, string label)
    {
        label = PythonDisplay.Strip(label);
        if (label.Length == 0 || label.Any(token => token < 32 || "<>:\"/\\|?*".Contains(token)) || label.EndsWith('.') || label.EndsWith(' '))
            throw new ArgumentException("名称不能为空，不能包含 Windows 文件名禁用字符或以点结尾");
        var stem = Path.GetFileNameWithoutExtension(source); var delimiter = stem.IndexOf(" -- ", StringComparison.Ordinal);
        if (delimiter >= 0) stem = stem[..delimiter];
        var name = stem + " -- " + label + Path.GetExtension(source);
        if (name.EnumerateRunes().Count() > 240) throw new ArgumentException("名称过长，请缩短后重试");
        return Path.Combine(Path.GetDirectoryName(Path.GetFullPath(source))!, name);
    }
    public static string Rename(string source, string label, Func<string, bool>? isWriting = null)
    {
        source = Path.GetFullPath(source);
        if (isWriting?.Invoke(source) == true) throw new InvalidOperationException("该文件正在写入，请先停止相关服务再重命名");
        var destination = RenamedPath(source, label);
        if (string.Equals(source, destination, StringComparison.OrdinalIgnoreCase)) return destination;
        List<(string Source, string Destination)> pairs = [(source, destination)];
        var oldInput = Path.ChangeExtension(source, ".input.jsonl"); var newInput = Path.ChangeExtension(destination, ".input.jsonl");
        var oldPrefix = Path.GetFileNameWithoutExtension(Path.GetFileNameWithoutExtension(oldInput));
        var newPrefix = Path.GetFileNameWithoutExtension(Path.GetFileNameWithoutExtension(newInput));
        List<(string Source, string Destination)> companions = [(oldInput, newInput)];
        foreach (var part in Directory.EnumerateFiles(Path.GetDirectoryName(source)!, oldPrefix + ".part-*.input.jsonl").Order(StringComparer.Ordinal))
            companions.Add((part, Path.Combine(Path.GetDirectoryName(destination)!, newPrefix + Path.GetFileName(part)[oldPrefix.Length..])));
        companions.Add((source + ".integrity.json", destination + ".integrity.json"));
        companions.Add((Path.ChangeExtension(source, ".integrity.json"), Path.ChangeExtension(destination, ".integrity.json")));
        companions.Add((source + ".status.json", destination + ".status.json"));
        foreach (var pair in companions)
        {
            if (Path.Exists(pair.Destination)) throw new IOException("文件已存在：" + Path.GetFileName(pair.Destination));
            if (Path.Exists(pair.Source)) pairs.Add(pair);
        }
        foreach (var pair in pairs)
        {
            if (!File.Exists(pair.Source)) throw new FileNotFoundException("源文件不存在", pair.Source);
            if (Path.Exists(pair.Destination)) throw new IOException("文件已存在：" + Path.GetFileName(pair.Destination));
            if (isWriting?.Invoke(pair.Source) == true) throw new InvalidOperationException("相关输入文件正在写入，请先停止服务");
        }
        List<(string Source, string Destination)> completed = [];
        try { foreach (var pair in pairs) { File.Move(pair.Source, pair.Destination); completed.Add(pair); } }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            List<Exception> failures = [];
            foreach (var pair in completed.AsEnumerable().Reverse())
                try { File.Move(pair.Destination, pair.Source); } catch (Exception rollback) when (rollback is IOException or UnauthorizedAccessException) { failures.Add(rollback); }
            if (failures.Count > 0) throw new IOException("重命名失败，部分文件恢复失败", new AggregateException(new[] { error }.Concat(failures)));
            throw;
        }
        return destination;
    }
    public static string RelocateKey(string key, string oldPath, string newPath)
    {
        try
        {
            if (EvidenceJson.Parse(key) is EvidenceArray { Items.Count: > 0 } values && values.Items[0] is EvidenceText path
                && string.Equals(path.Value.Replace('/', '\\'), oldPath.Replace('/', '\\'), StringComparison.OrdinalIgnoreCase))
                return PythonSortedJson.Serialize(new EvidenceArray(new EvidenceValue[] { new EvidenceText(newPath.Replace('/', '\\').ToLowerInvariant()) }.Concat(values.Items.Skip(1)).ToArray()));
        }
        catch (FormatException) { }
        return key;
    }
    public static HistoryRecord Relocate(HistoryRecord record, string oldPath, string newPath)
    {
        var moved = string.Equals(record.FilePath, oldPath, StringComparison.OrdinalIgnoreCase)
            ? record with { FilePath = newPath, Label = record.Label.Replace(Path.GetFileName(oldPath), Path.GetFileName(newPath), StringComparison.Ordinal) } : record;
        if (moved.SessionSource is { } session) moved = moved with { SessionSource = session with
        {
            Volumes = session.Volumes.Select(volume => string.Equals(volume.FilePath, oldPath, StringComparison.OrdinalIgnoreCase)
                ? volume with { FilePath = newPath } : volume).ToArray(),
        } };
        return moved.StructuredSource is not { } chain ? moved : moved with { StructuredSource = chain with
        {
            Volumes = chain.Volumes.Select(volume => string.Equals(volume.FilePath, oldPath, StringComparison.OrdinalIgnoreCase)
                ? volume with { FilePath = newPath } : volume).ToArray(),
        } };
    }
    public static ApplicationSettings Relocate(ApplicationSettings settings, string oldPath, string newPath)
    {
        Dictionary<string, EvidenceValue> bindings = new(StringComparer.Ordinal);
        foreach (var (key, value) in settings.InputLogBindings.Fields)
        {
            var moved = RelocateKey(key, oldPath, newPath);
            bindings[moved] = moved == key ? EvidenceJson.Clone(value) : RelocateBinding(value, oldPath, newPath);
        }
        return settings with
        {
            ImportedTraceFiles = settings.ImportedTraceFiles.Select(path => string.Equals(path, oldPath, StringComparison.OrdinalIgnoreCase) ? newPath : path).ToArray(),
            HiddenHistoryRecords = settings.HiddenHistoryRecords.Select(key => RelocateKey(key, oldPath, newPath)).ToArray(), InputLogBindings = new(bindings),
        };
    }
    private static EvidenceObject RelocateBinding(EvidenceValue value, string oldPath, string newPath)
    {
        var binding = InputBindings.Read(value, oldPath);
        var oldDirectory = Path.GetDirectoryName(oldPath)!; var newDirectory = Path.GetDirectoryName(newPath)!;
        string? RelocateSource(string? source)
        {
            if (source is null) return null;
            var oldInput = Path.ChangeExtension(oldPath, ".input.jsonl"); var newInput = Path.ChangeExtension(newPath, ".input.jsonl");
            var prefix = Path.GetFileNameWithoutExtension(oldPath); var newPrefix = Path.GetFileNameWithoutExtension(newPath);
            if (string.Equals(source, oldInput, StringComparison.OrdinalIgnoreCase)) source = newInput;
            else if (string.Equals(Path.GetDirectoryName(source), oldDirectory, StringComparison.OrdinalIgnoreCase) && Path.GetFileName(source).StartsWith(prefix + ".part-", StringComparison.Ordinal))
                source = Path.Combine(newDirectory, newPrefix + Path.GetFileName(source)[prefix.Length..]);
            return source;
        }
        return InputBindings.Write(newPath, binding with { SourcePath = RelocateSource(binding.SourcePath),
            SourcePaths = binding.SourcePaths?.Select(source => RelocateSource(source)!).ToArray() });
    }
}
