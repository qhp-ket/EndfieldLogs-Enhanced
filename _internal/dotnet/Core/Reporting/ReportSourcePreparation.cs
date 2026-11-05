using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record PreparedReportSources(ReportCalculationInput Calculation, ReportSourceInput Sources);

/// <summary>Bind report-local observations by explicit identity and lifetime, preserving evidence order.</summary>
public static class ReportSourcePreparation
{
    private static EvidenceObject Copy(EvidenceObject row) => (EvidenceObject)BuffEvidence.Clone(row);
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject row) => (Dictionary<string, EvidenceValue>)row.Fields;
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Integer(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static (BigInteger Time, BigInteger Line) Stamp(EvidenceObject row, string time = "ts_ms", string line = "line_no") =>
        (Integer(row.Get(time)), Integer(row.Get(line)));
    private static bool Within(EvidenceObject row, (BigInteger, BigInteger) stamp, bool closedCast)
    {
        if (stamp.CompareTo(Stamp(row)) < 0) return false;
        if (row.Get("end_ts_ms") is not EvidenceNull)
        {
            if (stamp.CompareTo(Stamp(row, "end_ts_ms", "end_line_no")) >= 0) return false;
        }
        else if (closedCast) return false;
        return closedCast || row.Get("snapshot_end_ts_ms") is EvidenceNull
            || stamp.CompareTo(Stamp(row, "snapshot_end_ts_ms", "snapshot_end_line_no")) < 0;
    }

    public static PreparedReportSources Prepare(ReportCalculationInput input, ReportSourceInput sources)
        => PrepareCore(input, sources, ownsInput: false);

    // Consume a freshly captured, private snapshot. Never pass caller-owned or reused input here.
    internal static PreparedReportSources PrepareOwned(ReportCalculationInput input, ReportSourceInput sources, bool preserveHits = false,
        LiveSourcePreparationCache? summaryCache = null)
        => PrepareCore(input, sources, ownsInput: true, preserveHits, summaryCache);

    private static PreparedReportSources PrepareCore(ReportCalculationInput input, ReportSourceInput sources, bool ownsInput, bool preserveHits = false,
        LiveSourcePreparationCache? summaryCache = null)
    {
        if (ownsInput && preserveHits && summaryCache is not null && sources.DynamicEvents.Count == 0
            && sources.RefreshEvents.Count == 0 && sources.PoiseEvents.Count == 0)
        {
            // No binding can change an earlier record. Preserve its protected identity
            // instead of rebuilding every root and comparing its fields in the effect cache.
            var preparedRecords = input.Records.Select(row => summaryCache.Prepare(row,
                sources.ModifierLastSeen.TryGetValue(Text(row.Get("uid")), out var stamp) ? stamp : null)).ToArray();
            foreach (var cast in sources.Casts) Fields(cast)["dynamic_bb_events"] = new EvidenceArray([]);
            foreach (var hit in input.Baseline.Hits)
                if (!FrozenEvidence.IsFrozenRoot(hit.Evidence)) Fields(hit.Evidence)["dynamic_bb_observations"] = new EvidenceArray([]);
            return new(input with { Records = preparedRecords }, sources);
        }
        var records = ownsInput ? input.Records.Select(FrozenEvidence.OwnedMutableRoot).ToArray() : input.Records.Select(Copy).ToArray();
        var hits = ownsInput ? input.Baseline.Hits : input.Baseline.Hits.Select(hit => hit with { Evidence = Copy(hit.Evidence) }).ToArray();
        var casts = ownsInput ? sources.Casts : sources.Casts.Select(Copy).ToArray();
        var events = ownsInput ? sources.DynamicEvents : sources.DynamicEvents.Select(Copy).ToArray();
        var refreshes = ownsInput ? sources.RefreshEvents : sources.RefreshEvents.Select(Copy).ToArray();
        foreach (var row in refreshes)
            if (row.Get("snapshot") is EvidenceObject snapshot) Fields(row)["snapshot_status"] = snapshot.Get("status");

        var byInstance = records.Where(row => CatalogValues.Truth(row.Get("uid")))
            .GroupBy(row => Text(row.Get("uid"))).ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.Ordinal);
        var buffEvents = records.ToDictionary(row => row, _ => new List<EvidenceValue>(), (IEqualityComparer<EvidenceObject>)ReferenceEqualityComparer.Instance);
        var castEvents = casts.ToDictionary(row => row, _ => new List<EvidenceValue>(), (IEqualityComparer<EvidenceObject>)ReferenceEqualityComparer.Instance);
        var byCast = casts.GroupBy(row => (Text(row.Get("owner_id")), Text(row.Get("skill_inst_id")), Text(row.Get("skill"))))
            .ToDictionary(group => group.Key, group => group.ToArray());
        foreach (var row in events)
        {
            var stamp = Stamp(row);
            var candidates = (byInstance.GetValueOrDefault(Text(row.Get("instance_id"))) ?? []).Where(record =>
                CatalogValues.Truth(row.Get("owner_id")) && CatalogValues.Truth(record.Get("target_actor_id"))
                && Text(row.Get("owner_id")) == Text(record.Get("target_actor_id"))
                && EvidenceJson.PythonEquals(row.Get("skill_key"), record.Get("event_key")) && Within(record, stamp, false)).ToArray();
            if (candidates.Length == 1) buffEvents[candidates[0]].Add(row);
            else if (candidates.Length > 1) Fields(row)["binding_error"] = new EvidenceText("ambiguous_buff_instance");
        }
        foreach (var row in events)
        {
            var candidates = (byCast.GetValueOrDefault((Text(row.Get("owner_id")), Text(row.Get("instance_id")), Text(row.Get("skill_key")))) ?? [])
                .Where(cast => CatalogValues.Truth(row.Get("owner_id")) && CatalogValues.Truth(cast.Get("owner_id"))
                    && EvidenceJson.PythonEquals(row.Get("instance_id"), cast.Get("skill_inst_id"))
                    && EvidenceJson.PythonEquals(row.Get("skill_key"), cast.Get("skill")) && Within(cast, Stamp(row), true)).ToArray();
            if (candidates.Length == 1) castEvents[candidates[0]].Add(row);
            else if (candidates.Length > 1) Fields(row)["binding_error"] = new EvidenceText("ambiguous_skill_instance");
        }
        foreach (var row in records)
        {
            Fields(row)["dynamic_bb_events"] = new EvidenceArray(buffEvents[row]);
            if (sources.ModifierLastSeen.TryGetValue(Text(row.Get("uid")), out var time))
                Fields(row)["packet_modifier_last_seen_ts_ms"] = new EvidenceInteger(time);
        }
        foreach (var row in casts) Fields(row)["dynamic_bb_events"] = new EvidenceArray(castEvents[row]);
        var poiseByTime = sources.PoiseEvents.GroupBy(row => Integer(row.Get("ts_ms")))
            .ToDictionary(group => group.Key, group => group.ToArray());
        foreach (var hit in hits)
        {
            // Summary preparation attaches the empty observation field once with its immutable baseline.
            if (preserveHits && FrozenEvidence.IsFrozenRoot(hit.Evidence)) continue;
            var row = hit.Evidence;
            Fields(row)["dynamic_bb_observations"] = new EvidenceArray([]);
            foreach (var poise in poiseByTime.GetValueOrDefault(Integer(row.Get("ts_ms"))) ?? [])
            {
                var source = Text(poise.Get("source"));
                if (source != Text(row.Get("skill_key")) && source != Text(row.Get("skill_family_key"))
                    && !(poise.Get("source_int") is not EvidenceNull && EvidenceJson.PythonEquals(poise.Get("source_int"), row.Get("template_int_id")))
                    && !(poise.Get("orig_source_int") is not EvidenceNull && EvidenceJson.PythonEquals(poise.Get("orig_source_int"), row.Get("original_template_int_id")))) continue;
                Fields(row)["poise_damage"] = BuffEvidence.Object(
                    ("type", BuffEvidence.Clone(CatalogValues.Or(poise.Get("type"), new EvidenceText("PoiseDamage")))),
                    ("value", BuffEvidence.Clone(poise.Get("value"))), ("current_value", BuffEvidence.Clone(poise.Get("current_value"))),
                    ("source", new EvidenceText(source)), ("source_int", BuffEvidence.Clone(poise.Get("source_int"))),
                    ("orig_source", BuffEvidence.Clone(poise.Get("orig_source"))), ("orig_source_int", BuffEvidence.Clone(poise.Get("orig_source_int"))));
            }
        }
        return new(input with { Baseline = input.Baseline with { Hits = hits }, Records = records },
            sources with { Casts = casts, DynamicEvents = events, RefreshEvents = refreshes,
                PoiseEvents = ownsInput ? sources.PoiseEvents : sources.PoiseEvents.Select(Copy).ToArray(),
                AtbEvents = ownsInput ? sources.AtbEvents : sources.AtbEvents.Select(Copy).ToArray(),
                ModifierLastSeen = ownsInput ? sources.ModifierLastSeen : new Dictionary<string, long>(sources.ModifierLastSeen, StringComparer.Ordinal) });
    }
}
