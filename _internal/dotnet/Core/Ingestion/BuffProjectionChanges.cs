namespace EndfieldLogs.Core.Ingestion;

/// <summary>Enabled only by the live owner. Shared observations invalidate every snapshot in their instance.</summary>
internal sealed class BuffProjectionChanges
{
    private readonly Dictionary<(string Uid, int StartLine), HashSet<BuffRecord>> families = [];
    internal HashSet<BuffRecord> Dirty { get; } = new(ReferenceEqualityComparer.Instance);
    internal long StructureRevision { get; private set; }

    internal void Add(BuffRecord record)
    {
        var key = (record.Uid, record.InstanceStartLineNumber);
        if (!families.TryGetValue(key, out var family)) families[key] = family = new(ReferenceEqualityComparer.Instance);
        family.Add(record);
        Dirty.Add(record);
    }

    internal void Changed(BuffRecord record)
    {
        if (families.TryGetValue((record.Uid, record.InstanceStartLineNumber), out var family)) Dirty.UnionWith(family);
    }

    internal void Removed(BuffRecord record)
    {
        var key = (record.Uid, record.InstanceStartLineNumber);
        if (families.TryGetValue(key, out var family))
        {
            family.Remove(record);
            if (family.Count == 0) families.Remove(key);
        }
        Dirty.Remove(record);
        StructureRevision++;
    }
}
