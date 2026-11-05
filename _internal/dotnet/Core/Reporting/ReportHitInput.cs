using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>An owned hit projection and its integer-key attribute evidence, captured on the ingestion owner.</summary>
public sealed record ReportHitInput(EvidenceObject Evidence,
    IReadOnlyDictionary<BigInteger,EvidenceValue> Baseline,
    IReadOnlyDictionary<BigInteger,EvidenceValue> BasicAttributes,
    IReadOnlyDictionary<BigInteger,EvidenceValue> Attributes)
{
    // The public JSON projection renders integer keys as text. It is an alias, not a second baseline.
    // Compatibility imports may instead supply genuine text keys alongside numeric ones.
    public bool BaselineProjectionIsNumeric { get; init; }

    public static ReportHitInput Capture(DamageHit hit)
    {
        static IReadOnlyDictionary<BigInteger,EvidenceValue> Copy(IReadOnlyDictionary<BigInteger,double>? values)=>
            values?.ToDictionary(pair=>pair.Key,pair=>(EvidenceValue)new EvidenceReal(pair.Value)) ?? [];
        return new(HitReportEvidence.Project(hit),Copy(hit.Packet.Baseline),Copy(hit.AttackerStats.Snapshot?.BasicAttributes),
            Copy(hit.AttackerStats.Snapshot?.Attributes)) { BaselineProjectionIsNumeric = true };
    }
}
