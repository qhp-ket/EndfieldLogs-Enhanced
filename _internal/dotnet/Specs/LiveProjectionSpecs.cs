using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;

internal static class LiveProjectionSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var report = (EvidenceObject)EvidenceJson.Parse("""
            {"battle":{"duration_ms":500,"total_damage":100,"roster":[{"character_key":"a"}],"private_evidence":"retained only by full view"},
             "participants":[{"character_key":"a","total_rd":75,"evidence":{"values":[9007199254740993,-0.0]}}],
             "loadout":[{"character_key":"support","slot":2}],
             "timeline_events":[{"rdps_contributions":[{"character_key":"a","value":33}]}]}
            """);
        var before = EvidenceJsonSignature.Sorted(report);
        var overlay = LiveReportProjection.Overlay(report);
        var summary = LiveReportProjection.Summary(report);
        var rows = ((EvidenceArray)overlay.Get("participants")).Items.Cast<EvidenceObject>().ToArray();
        check(rows[0].Get("rdps") is EvidenceReal { Value: 0 } && rows[0].Get("max_rd") is EvidenceReal { Value: 33 },
            "A 500ms window suppresses the unstable rate but retains actual total and maximum contribution");
        check(rows.Length == 2 && rows[1].Get("crit_rate") is EvidenceNull && rows[1].Get("total_damage") is EvidenceReal { Value: 0 },
            "Roster-only characters remain visible with zero damage and unknown critical rate");
        check(((EvidenceObject)summary.Get("battle")).Get("private_evidence") is EvidenceNull
            && summary.Get("timeline_events") is EvidenceNull && summary.Get("quality_summary") is EvidenceObject,
            "The compact view exposes selected battle fields and quality without full evidence or timeline payloads");
        ((Dictionary<string, EvidenceValue>)rows[0].Fields)["total_rd"] = new EvidenceReal(-1);
        check(before == EvidenceJsonSignature.Sorted(report)
            && ((EvidenceObject)((EvidenceArray)summary.Get("participants")).Items[0]).Get("total_rd") is EvidenceReal { Value: 75 },
            "A consumer can change its view without mutating canonical evidence or a separately published view");
        var direct = LiveReportProjection.Summary(report, new Dictionary<string, double> { ["a"] = 7 });
        check(((EvidenceObject)((EvidenceArray)direct.Get("participants")).Items[0]).Get("max_rd") is EvidenceReal { Value: 7 },
            "A compact calculation can provide per-hit maxima without constructing timeline events");
        var untouchedSummary = EvidenceJsonSignature.Sorted(summary);
        var nested = (EvidenceObject)((EvidenceObject)((EvidenceArray)direct.Get("participants")).Items[0]).Get("evidence");
        ((EvidenceValue[])((EvidenceArray)nested.Get("values")).Items)[0] = EvidenceNull.Value;
        var roster = (EvidenceObject)((EvidenceArray)((EvidenceObject)direct.Get("battle")).Get("roster")).Items[0];
        ((Dictionary<string, EvidenceValue>)roster.Fields)["character_key"] = new EvidenceText("changed");
        check(before == EvidenceJsonSignature.Sorted(report) && untouchedSummary == EvidenceJsonSignature.Sorted(summary),
            "Nested participant and roster evidence remain detached between compact views and the full source report");
    }
}
