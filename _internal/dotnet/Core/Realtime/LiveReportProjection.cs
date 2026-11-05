using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Realtime;

/// <summary>Owned overlay and compact live views of canonical results. No attribution rules.</summary>
public static class LiveReportProjection
{
    private static readonly string[] BattleFields = [
        "dungeon_key", "dungeon_name", "boss_key", "boss_name", "battle_start_at", "battle_end_at", "duration_ms",
        "total_damage", "total_dps", "roster", "time_source", "timer_start_seen", "timer_end_seen", "timer_window_valid",
        "official_timer_start_seen", "official_timer_end_seen", "timer_integrity_ok", "timer_integrity_reasons",
        "clear_flag", "official_pass_confirmed", "completion_source", "parser_version", "rules_version",
    ];
    private static EvidenceValue Or(EvidenceValue value, EvidenceValue fallback) => CatalogValues.Or(value, fallback);
    private static string Key(EvidenceObject row) => PythonDisplay.String(Or(row.Get("character_key"), new EvidenceText("")));
    private static IEnumerable<EvidenceObject> Rows(EvidenceObject source, string key) => source.Get(key) is EvidenceArray rows
        ? rows.Items.Cast<EvidenceObject>() : [];
    private static double Number(EvidenceValue value) => EffectIdentity.Float(Or(value, new EvidenceReal(0)));

    public static IReadOnlyDictionary<string, double> MaximaFromHits(IEnumerable<ReportHitInput> hits)
    {
        Dictionary<string, double> maxima = new(StringComparer.Ordinal);
        foreach (var hit in hits)
            if (hit.Evidence.Get("rdps_contributions") is EvidenceObject contributions)
                foreach (var (key, value) in contributions.Fields)
                    maxima[key] = Math.Max(maxima.GetValueOrDefault(key), PythonDecimalRounding.Round(Number(value), 4));
        return maxima;
    }

    private static IReadOnlyDictionary<string, double> TimelineMaxima(EvidenceObject report)
    {
        Dictionary<string, double> maxima = new(StringComparer.Ordinal);
        foreach (var item in Rows(report, "timeline_events"))
            foreach (var row in Rows(item, "rdps_contributions"))
            {
                var key = Key(row);
                if (key.Length > 0) maxima[key] = Math.Max(maxima.GetValueOrDefault(key), Number(row.Get("value")));
            }
        return maxima;
    }

    public static EvidenceObject Overlay(EvidenceObject report, IReadOnlyDictionary<string, double>? maxima = null)
        => (EvidenceObject)BuffEvidence.Clone(OverlayOwned(report, maxima));

    // The report and its projection belong to the same private calculation until
    // the caller makes the final detached output. Do not expose this view directly.
    internal static EvidenceObject OverlayOwned(EvidenceObject report, IReadOnlyDictionary<string, double>? maxima = null)
    {
        maxima ??= TimelineMaxima(report);
        var battle = (EvidenceObject)report.Get("battle");
        var seconds = Math.Max(Number(battle.Get("duration_ms")) / 1000.0, 0);
        Dictionary<string, double> totals = new(StringComparer.Ordinal);
        foreach (var row in Rows(report, "participants"))
        {
            var key = Key(row);
            if (key.Length > 0) totals[key] = row.Get("total_rd") is not EvidenceNull ? Number(row.Get("total_rd")) : Number(row.Get("rdps")) * seconds;
        }
        List<EvidenceValue> participants = [];
        HashSet<string> seen = new(StringComparer.Ordinal);
        foreach (var row in Rows(report, "participants"))
        {
            var key = Key(row);
            if (key.Length == 0) continue;
            seen.Add(key);
            var total = totals.GetValueOrDefault(key);
            var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal)
            {
                ["rdps"] = new EvidenceReal(seconds > .5 ? total / seconds : 0),
                ["total_rd"] = new EvidenceReal(total), ["max_rd"] = new EvidenceReal(maxima.GetValueOrDefault(key)),
            };
            participants.Add(new EvidenceObject(fields));
        }
        foreach (var row in Rows(report, "loadout").OrderBy(row => EffectIdentity.Integer(Or(row.Get("slot"), new EvidenceInteger(0))))
            .ThenBy(Key, PythonDisplay.CodePointComparer))
        {
            var key = Key(row);
            if (key.Length == 0 || !seen.Add(key)) continue;
            participants.Add(BuffEvidence.Object(("character_key", new EvidenceText(key)),
                ("character_name", new EvidenceText(PythonDisplay.String(Or(row.Get("character_name"), new EvidenceText(key))))),
                ("total_damage", new EvidenceReal(0)), ("dps", new EvidenceReal(0)), ("rdps", new EvidenceReal(0)),
                ("total_rd", new EvidenceReal(0)), ("max_rd", new EvidenceReal(0)), ("max_hit", new EvidenceInteger(0)),
                ("hit_count", new EvidenceInteger(0)), ("crit_hits", new EvidenceInteger(0)), ("crit_rate", EvidenceNull.Value)));
        }
        Dictionary<string, EvidenceValue> output = new(StringComparer.Ordinal)
        {
            ["battle"] = battle, ["participants"] = new EvidenceArray(participants), ["debug"] = EvidenceNull.Value,
            ["rdps_damage_basis"] = Or(report.Get("rdps_damage_basis"), battle.Get("rdps_damage_basis")),
        };
        foreach (var key in new[] { "loadout", "buff_events", "timeline_events", "role_skill_stats", "casts", "atb_events" })
            output[key] = Or(report.Get(key), new EvidenceArray([]));
        foreach (var key in new[] { "rdps_preflight", "unresolved_hits", "unresolved_buff_actions", "snapshot_quality" })
            if (report.Fields.TryGetValue(key, out var value)) output[key] = value;
        return new EvidenceObject(output);
    }

    public static EvidenceObject Summary(EvidenceObject report, IReadOnlyDictionary<string, double>? maxima = null)
    {
        var projected = OverlayOwned(report, maxima);
        var battle = (EvidenceObject)report.Get("battle");
        var quality = SnapshotQuality.Build(report, includeEvidence: false);
        var basis = report.Get("rdps_damage_basis") as EvidenceObject ?? BuffEvidence.Object();
        var preflight = report.Get("rdps_preflight") as EvidenceObject ?? BuffEvidence.Object();
        Dictionary<string, EvidenceValue> counts = new(StringComparer.Ordinal) { ["blockers"] = preflight.Get("blocker_count") };
        foreach (var key in new[] { "hit_count", "unresolved_damage_actor_count", "missing_packet_hit_count", "hit_conservation_mismatch_count" })
            counts[key] = basis.Get(key);
        var fields = new Dictionary<string, EvidenceValue>(quality.Fields, StringComparer.Ordinal) { ["counts"] = new EvidenceObject(counts) };
        return (EvidenceObject)BuffEvidence.Clone(BuffEvidence.Object(("battle", new EvidenceObject(BattleFields.Where(battle.Fields.ContainsKey)
            .ToDictionary(key => key, battle.Get, StringComparer.Ordinal))), ("participants", projected.Get("participants")),
            ("quality_summary", new EvidenceObject(fields))));
    }
}
