using System.Reflection;
using System.Text.Json;
using Google.Protobuf;
using Google.Protobuf.Reflection;

namespace EndfieldLogs.Protocol;

public static class ProtocolCatalog
{
    public static IReadOnlyDictionary<string, FileDescriptor> Files { get; } = DiscoverFiles();
    public static IReadOnlyDictionary<string, MessageDescriptor> Messages { get; } = DiscoverMessages();
    public static IReadOnlySet<string> DeclaredMessages { get; } = ReadDeclaredMessages();

    private static IReadOnlySet<string> ReadDeclaredMessages()
    {
        using var stream = typeof(ProtocolCatalog).Assembly.GetManifestResourceStream("EndfieldLogs.Protocol.SchemaManifest.json")
            ?? throw new InvalidDataException("Protocol schema manifest is missing");
        using var document = JsonDocument.Parse(stream);
        return new[] { "active_messages", "declared_unavailable_messages" }
            .SelectMany(name => document.RootElement.GetProperty(name).EnumerateArray().Select(item => item.GetString()!))
            .ToHashSet(StringComparer.Ordinal);
    }

    private static Dictionary<string, FileDescriptor> DiscoverFiles()
    {
        Dictionary<string, FileDescriptor> files = new(StringComparer.Ordinal);
        foreach (var type in typeof(ProtocolCatalog).Assembly.GetTypes())
        {
            if (!type.IsAbstract || !type.IsSealed) continue;
            var descriptor = type.GetProperty("Descriptor", BindingFlags.Public|BindingFlags.Static);
            if (descriptor?.PropertyType != typeof(FileDescriptor)) continue;
            var file = (FileDescriptor)descriptor.GetValue(null)!;
            files.Add(file.Name, file);
        }
        return files;
    }

    private static Dictionary<string, MessageDescriptor> DiscoverMessages()
    {
        Dictionary<string, MessageDescriptor> messages = new(StringComparer.Ordinal);
        void Visit(MessageDescriptor descriptor)
        {
            if (descriptor.Parser is not null) messages.Add(descriptor.FullName, descriptor);
            foreach (var nested in descriptor.NestedTypes) Visit(nested);
        }
        foreach (var file in Files.Values)
            foreach (var message in file.MessageTypes) Visit(message);
        return messages;
    }

    public static IMessage Parse(string fullName, byte[] data) =>
        Messages.TryGetValue(fullName, out var descriptor)
            ? descriptor.Parser.ParseFrom(data)
            : throw new InvalidDataException("protobuf class unavailable: "+fullName);
}
