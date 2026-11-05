using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Owned equipment history captured on the ingestion thread for report workers.</summary>
public sealed record ReportLoadoutInput(IReadOnlyList<EvidenceObject> Groups,IReadOnlyDictionary<string,EvidenceObject> Fallback)
{
    public static ReportLoadoutInput Capture(BattleIngestionStream stream)=>new(stream.Loadouts.Groups.Select(group=>new EvidenceObject(
        new Dictionary<string,EvidenceValue>(StringComparer.Ordinal)
        {
            ["ts_ms"]=new EvidenceInteger(group.TimestampMs),["line_no"]=new EvidenceInteger(group.LineNumber),
            ["reason"]=new EvidenceText(group.Reason),["index"]=new EvidenceInteger(group.Index),
            ["rows"]=new EvidenceObject(group.Rows.ToDictionary(pair=>pair.Key,pair=>BuffEvidence.Clone(pair.Value),StringComparer.Ordinal)),
        })).ToArray(),stream.Party.Loadouts.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)BuffEvidence.Clone(pair.Value),StringComparer.Ordinal));
}
