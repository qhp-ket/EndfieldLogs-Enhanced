using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;

/// <summary>Materialize only fixture-supplied resources under an invocation-owned directory.</summary>
internal sealed class ResourceFixture : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "endfield-resource-spec-" + Guid.NewGuid().ToString("N"));
    public ResourceFiles Files { get; }

    public ResourceFixture(JsonNode fixture)
    {
        Files = new(Path.Combine(root, "_internal"));
        Directory.CreateDirectory(Files.InternalRoot);
        try
        {
            foreach (var (name, contents) in fixture["files"]?.AsObject() ?? [])
            {
                var path = SafePath(name);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllText(path, contents!.GetValue<string>());
            }
            foreach (var value in fixture["directories"]?.AsArray() ?? []) Directory.CreateDirectory(SafePath(value!.GetValue<string>()));
            foreach (var (name, bytes) in fixture["binary_files"]?.AsObject() ?? [])
            {
                var path = SafePath(name);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllBytes(path, Convert.FromBase64String(bytes!.GetValue<string>()));
            }
        }
        catch { Dispose(); throw; }
    }

    private string SafePath(string relative)
    {
        var path = Path.GetFullPath(Path.Combine(root, relative));
        if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Fixture resource path is outside its temporary directory");
        return path;
    }

    public void Dispose() => Directory.Delete(root, recursive: true);
}
