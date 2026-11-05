using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

public sealed record TypedActionNode(EvidenceObject Definition, bool Enabled);
public sealed record BuffRootActionIndex(EvidenceValue Root,
    IReadOnlyDictionary<BigInteger, IReadOnlyList<TypedActionNode>> Actions,
    IReadOnlyList<TypedActionNode> Creations);

/// <summary>One ingestion stream owns this cache and every referenced immutable root.</summary>
public sealed class BuffActionIndices
{
    private readonly Dictionary<EvidenceValue, BuffRootActionIndex> cache = new(ReferenceEqualityComparer.Instance);

    public BuffRootActionIndex For(EvidenceValue root)
    {
        if (cache.TryGetValue(root, out var existing)) return existing;
        Dictionary<BigInteger, List<TypedActionNode>> actions = [];
        List<TypedActionNode> creations = [];
        Stack<(EvidenceValue Node, bool Enabled)> pending = new([(root, true)]);
        while (pending.TryPop(out var current))
        {
            if (current.Node is EvidenceObject obj)
            {
                var enabled = current.Enabled && (!obj.Fields.ContainsKey("serverActionIndex") || obj.Get("isEnable") is EvidenceBoolean { Value: true });
                if (obj.Get("serverActionIndex") is EvidenceInteger index)
                {
                    if (!actions.TryGetValue(index.Value, out var rows)) actions[index.Value] = rows = [];
                    rows.Add(new(obj, enabled));
                }
                if (obj.Get("$type") is EvidenceText { Value: "Beyond.Gameplay.Core.CreateBuffAction.Data" })
                    creations.Add(new(obj, enabled));
                foreach (var value in obj.Fields.Values) pending.Push((value, enabled));
            }
            else if (current.Node is EvidenceArray array)
                foreach (var value in array.Items) pending.Push((value, current.Enabled));
        }
        var result = new BuffRootActionIndex(root,
            actions.ToDictionary(pair => pair.Key, pair => (IReadOnlyList<TypedActionNode>)pair.Value), creations);
        cache[root] = result;
        return result;
    }
}
