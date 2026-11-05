using System.Numerics;
using System.Text.Json;
using EndfieldLogs.Protocol;
using Google.Protobuf;

namespace EndfieldLogs.Capture.Framing;

public sealed class MessageDecodeFailure(string message, Exception? inner=null) : Exception(message, inner);
public sealed record DecodedMessage(string Direction, string ClassName, BigInteger MessageId,
    SessionHead Head, IMessage Message, byte[] RawBody);

public sealed class MessageRegistry
{
    private readonly Dictionary<string, Dictionary<BigInteger, string>> maps;
    private readonly Dictionary<string, HashSet<BigInteger>> interesting;

    public MessageRegistry(string dataDirectory) : this(
        File.ReadAllText(Path.Combine(dataDirectory, "message_ids_cs.json")),
        File.ReadAllText(Path.Combine(dataDirectory, "message_ids_sc.json"))) { }

    public MessageRegistry(string clientMapJson, string serverMapJson)
    {
        maps = new(StringComparer.Ordinal) { ["cs"]=ReadMap(clientMapJson), ["sc"]=ReadMap(serverMapJson) };
        maps["cs"][1952] = "CS_CONTINGENCY_CONTRACT_SET_TAGS";
        maps["sc"][2201] = "SC_CONTINGENCY_CONTRACT_SET_TAGS";
        maps["sc"][2202] = "SC_CONTINGENCY_CONTRACT_TAGS_SYNC";
        maps["sc"][2203] = "SC_CONTINGENCY_CONTRACT_BATTLE_RESULT";
        interesting = maps.ToDictionary(pair => pair.Key,
            pair => pair.Value.Where(row => ProtocolCatalog.DeclaredMessages.Contains(row.Value)).Select(row => row.Key).ToHashSet(),
            StringComparer.Ordinal);
    }

    private static Dictionary<BigInteger, string> ReadMap(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var entries = root.ValueKind == JsonValueKind.Object ? root.EnumerateObject().Select(row => row.Value) : root.EnumerateArray();
        Dictionary<BigInteger, string> result = [];
        foreach (var row in entries)
        {
            if (!row.TryGetProperty("msg_id", out var id) || id.ValueKind == JsonValueKind.Null
                || !row.TryGetProperty("class_name", out var name) || name.ValueKind == JsonValueKind.Null) continue;
            var className = name.GetString();
            if (string.IsNullOrEmpty(className)) continue;
            var number = BigInteger.Parse(id.ValueKind == JsonValueKind.String ? id.GetString()! : id.GetRawText(),
                System.Globalization.CultureInfo.InvariantCulture);
            result[number] = className;
        }
        return result;
    }

    public string? ResolveClassName(string direction, BigInteger id) => maps.GetValueOrDefault(direction)?.GetValueOrDefault(id);
    public bool ShouldDecode(string direction, BigInteger id) => interesting.GetValueOrDefault(direction)?.Contains(id) == true;

    public IReadOnlyList<DecodedMessage> Decode(string direction, SessionHead head, byte[] body)
    {
        var id = head.MessageId ?? BigInteger.Zero;
        if (!ShouldDecode(direction, id) || ResolveClassName(direction, id) is not string className) return [];
        if (!ProtocolCatalog.Messages.TryGetValue(className, out var descriptor))
            throw new MessageDecodeFailure($"protobuf class unavailable: direction={direction} msg_id={id} class={className}");
        IMessage message;
        try { message = descriptor.Parser.ParseFrom(body); }
        catch (InvalidProtocolBufferException error)
        {
            throw new MessageDecodeFailure(
                $"protobuf decode failed: direction={direction} msg_id={id} class={className} body_len={body.Length}", error);
        }
        List<DecodedMessage> decoded = [new(direction, className, id, head, message, body)];
        if (className.EndsWith("MERGE_MSG", StringComparison.Ordinal)
            && message.Descriptor.FindFieldByName("msg")?.Accessor.GetValue(message) is ByteString merged && merged.Length > 0)
            foreach (var frame in SessionFrameBuffer.Merged(merged.ToByteArray()))
            {
                var subHead = WireFields.ParseHead(frame.Frame.Head);
                var subBody = SessionBodyCodec.Decode(subHead, frame.Frame.Body);
                decoded.AddRange(Decode(direction, subHead, subBody));
            }
        return decoded;
    }
}
