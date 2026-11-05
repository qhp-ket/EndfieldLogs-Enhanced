using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

public sealed record SkillItemMetadata(string Specification, string CastType, string AttackRangeType,
    IReadOnlyDictionary<BigInteger, string> DynamicActionKeys, bool Available = true);

public sealed class SkillItemMetadataCatalog(ResourceFiles resources)
{
    private readonly Dictionary<string, (SkillItemMetadata Metadata, LinkedListNode<string> Node)> cache = new(StringComparer.Ordinal);
    private readonly LinkedList<string> recent = new();
    public SkillItemMetadata For(string key)
    {
        if (cache.TryGetValue(key, out var saved))
        {
            recent.Remove(saved.Node);
            recent.AddFirst(saved.Node);
            return saved.Metadata;
        }
        var payload = key.Length == 0 ? null : resources.ReadRelative("data/akedata/skill/items/"+key+".json") as EvidenceObject;
        Dictionary<BigInteger, string> keys = [];
        Stack<EvidenceValue> pending = new([payload ?? (EvidenceValue)EvidenceNull.Value]);
        while (pending.TryPop(out var node))
        {
            if (node is EvidenceObject obj)
            {
                var type = PacketBuffCatalog.Text(obj.Get("$type")).Replace('+', '.');
                var actionKey = PacketBuffCatalog.Text(obj.Get("key"));
                var action = obj.Get("serverActionIndex") switch
                {
                    EvidenceInteger integer => integer.Value,
                    EvidenceText text => TraceFields.OptionalInteger(text.Value),
                    EvidenceReal real => TraceFields.OptionalInteger(real.Value),
                    _ => null,
                };
                if ((type.Contains("ModifyDynamicBlackboard.Data", StringComparison.Ordinal) || type.Contains("SimpleCalcBBAction.Data", StringComparison.Ordinal))
                    && action is not null && actionKey.Length > 0) keys[action.Value] = actionKey;
                foreach (var value in obj.Fields.Values) pending.Push(value);
            }
            else if (node is EvidenceArray array) foreach (var value in array.Items) pending.Push(value);
        }
        var result = new SkillItemMetadata(payload is null ? "" : PacketBuffCatalog.Text(payload.Get("skillSpecification")),
            payload is null ? "" : PacketBuffCatalog.Text(payload.Get("castType")),
            payload is null ? "" : PacketBuffCatalog.Text(payload.Get("attackRangeType")), keys, payload is not null);
        cache[key] = (result, recent.AddFirst(key));
        if (cache.Count > 4096 && recent.Last is { } last) { cache.Remove(last.Value); recent.RemoveLast(); }
        return result;
    }
}
