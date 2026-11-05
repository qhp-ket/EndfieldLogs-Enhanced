using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Capture hit and equipment evidence together before dispatching baseline preparation.</summary>
public sealed record ReportBaselineInput(ReportLoadoutInput Loadouts,IReadOnlyList<ReportHitInput> Hits,
    IReadOnlyDictionary<string,HashSet<string>> ActiveSuits)
{
    public static ReportBaselineInput Capture(BattleIngestionStream stream)=>Capture(stream, ReportHitInput.Capture);

    internal static ReportBaselineInput Capture(BattleIngestionStream stream, Func<DamageHit, ReportHitInput> project)=>new(ReportLoadoutInput.Capture(stream),
        stream.Hits.Hits.Select(project).ToArray(),
        stream.Party.ActiveSuits.ToDictionary(pair=>pair.Key,pair=>new HashSet<string>(pair.Value,StringComparer.Ordinal),StringComparer.Ordinal));
}
