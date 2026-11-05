namespace EndfieldLogs.Runtime.Storage;

internal static class PhysicalPaths
{
    internal static string Resolve(string path)
    {
        path = Path.GetFullPath(path);
        var root = Path.GetPathRoot(path)!; var current = root;
        foreach (var part in path[root.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            FileSystemInfo item = Directory.Exists(current) ? new DirectoryInfo(current) : new FileInfo(current);
            if (item.Exists && item.LinkTarget is not null)
                current = item.ResolveLinkTarget(returnFinalTarget: true)?.FullName ?? throw new IOException("无法解析文件路径");
        }
        return current;
    }
}
