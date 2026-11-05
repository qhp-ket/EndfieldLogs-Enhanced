using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Capture on the ingestion owner; the report worker then owns its evidence and loadout view.</summary>
public sealed record ReportEffectInput(IReadOnlyList<EvidenceObject> Records,IReadOnlyList<EvidenceObject> Hits,
    BigInteger LastHitMs,IReadOnlyDictionary<string,double> StaticArtsStrength,
    IReadOnlyDictionary<string,HashSet<string>> ActiveSuits,IReadOnlyDictionary<string,string> ActiveWeapons)
{
    public static ReportEffectInput Capture(BattleIngestionStream stream,BigInteger lastHitMs,
        IReadOnlyDictionary<string,double>? staticArtsStrength=null)=>new(
            stream.Buffs.Records.Select(BuffReportEvidence.Project).ToArray(),stream.Hits.Hits.Select(HitReportEvidence.Project).ToArray(),
            lastHitMs,new Dictionary<string,double>(staticArtsStrength ?? new Dictionary<string,double>(),StringComparer.Ordinal),
            stream.Party.ActiveSuits.ToDictionary(pair=>pair.Key,pair=>new HashSet<string>(pair.Value,StringComparer.Ordinal),StringComparer.Ordinal),
            new Dictionary<string,string>(stream.Party.ActiveWeapons,StringComparer.Ordinal));
}
