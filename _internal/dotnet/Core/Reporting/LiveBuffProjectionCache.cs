using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>One live stream's immutable BUFF projections; snapshots own their reference array.</summary>
internal sealed class LiveBuffProjectionCache
{
    private BuffInstanceState? owner;
    private readonly Dictionary<BuffRecord, int> indices = new(ReferenceEqualityComparer.Instance);
    private readonly List<EvidenceObject> projections = [];
    private readonly FrozenEvidence.Context snapshots = new();
    private long structureRevision;
    internal long ProjectedRecords { get; private set; }
    internal long ReusedRecords { get; private set; }
    internal long StructureResets { get; private set; }

    internal EvidenceObject[] Capture(BuffInstanceState state)
    {
        if (owner is not null && !ReferenceEquals(owner, state)) throw new InvalidOperationException("Live BUFF cache belongs to another stream");
        owner = state;
        var changes = state.TrackProjectionChanges();
        if (structureRevision != changes.StructureRevision)
        {
            indices.Clear();
            projections.Clear();
            snapshots.Clear();
            structureRevision = changes.StructureRevision;
            StructureResets++;
        }
        var projected = 0;
        for (var index = projections.Count; index < state.Records.Count; index++)
        {
            var record = state.Records[index];
            indices.Add(record, index);
            projections.Add(Project(record));
            changes.Dirty.Remove(record);
            projected++;
        }
        foreach (var record in changes.Dirty)
            if (indices.TryGetValue(record, out var index))
            {
                projections[index] = Project(record);
                projected++;
            }
        changes.Dirty.Clear();
        ProjectedRecords += projected;
        ReusedRecords += projections.Count - projected;
        return projections.ToArray();
    }

    private EvidenceObject Project(BuffRecord record) => (EvidenceObject)snapshots.Capture(BuffReportEvidence.Project(record));
}
