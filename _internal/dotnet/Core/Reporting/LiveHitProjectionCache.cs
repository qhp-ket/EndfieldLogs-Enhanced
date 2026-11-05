using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>One serialized live engine's projections; late packet observations invalidate only their hit.</summary>
internal sealed class LiveHitProjectionCache
{
    private sealed record Entry(long PacketRevision, ReportHitInput Input)
    {
        internal ReportHitInput? SummaryInput;
    }
    private static readonly EvidenceObject SummaryFields = (EvidenceObject)FrozenEvidence.Capture(
        new EvidenceObject(new Dictionary<string, EvidenceValue> { ["dynamic_bb_observations"] = new EvidenceArray([]) }));
    private readonly Dictionary<DamageHit, Entry> entries = new(ReferenceEqualityComparer.Instance);
    private readonly FrozenEvidence.Context snapshots = new();
    internal long ProjectedHits { get; private set; }
    internal long ReusedHits { get; private set; }

    internal ReportHitInput Capture(DamageHit hit)
    {
        var input = Get(hit).Input;
        return input with { Evidence = FrozenEvidence.MutableRoot(input.Evidence) };
    }

    internal ReportHitInput CaptureImmutable(DamageHit hit)
    {
        var entry = Get(hit);
        return entry.SummaryInput ??= entry.Input with { Evidence = FrozenEvidence.MergeRoot(entry.Input.Evidence, SummaryFields) };
    }

    private Entry Get(DamageHit hit)
    {
        if (!entries.TryGetValue(hit, out var entry) || entry.PacketRevision != hit.Packet.Revision)
        {
            var input = ReportHitInput.Capture(hit);
            entry = new(hit.Packet.Revision, input with
            {
                Evidence = (EvidenceObject)snapshots.Capture(input.Evidence),
                Baseline = FrozenEvidence.CaptureNumbers(input.Baseline),
                BasicAttributes = FrozenEvidence.CaptureNumbers(input.BasicAttributes), Attributes = FrozenEvidence.CaptureNumbers(input.Attributes),
            });
            entries[hit] = entry;
            ProjectedHits++;
        }
        else ReusedHits++;
        return entry;
    }
}
