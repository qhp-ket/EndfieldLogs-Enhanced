using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class ReportBuffEventSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool, string> check)
    {
        var resistance = Obj("""{"zone":"res","element":"physical","rate":15}""");
        var conditional = Obj("""{"zone":"amp","rate":0.2,"condition":{"type":"target_hp_compare","threshold":100,"compare":"LT","is_ratio":false}}""");
        check(ReportBuffEvents.Summaries([resistance, conditional, resistance]).SequenceEqual([
            "减抗/physical 15 点", "增幅/all 20.00% (target HP < 100.0)" ]),
            "Descriptions distinguish resistance points from percentages, retain HP conditions and remove duplicate text");
        var keyword = Obj("""
            {"zone":"dmg_inc","base_rate":0.1,"keyword_session_id":"s","keyword_rate_snapshots":[
              {"ts_ms":1000,"line_no":2,"operation_seq":1,"session_id":"s","status":"observed","rate_after":0.2},
              {"ts_ms":1000,"line_no":3,"operation_seq":2,"session_id":"s","status":"unknown","rate_after":0.9},
              {"ts_ms":1100,"line_no":4,"operation_seq":1,"session_id":"s","status":"observed","rate_after":0.7},
              {"ts_ms":1200,"line_no":5,"operation_seq":3,"session_id":"other","status":"observed","rate_after":0.8}]}
            """);
        var keywordSegments = ReportBuffEvents.Segments(1000, 2000, [], [keyword]);
        check(keywordSegments.Count == 3
            && keywordSegments[0].Get("start_ts_ms") is EvidenceInteger { Value: var start } && start == 1000
            && keywordSegments[0].Get("end_ts_ms") is EvidenceInteger { Value: var end } && end == 1000
            && keywordSegments[1].Get("end_line_no") is EvidenceInteger { Value: var line } && line == 3,
            "Equal-time updates preserve zero-length segments and the explicit next packet line");
        check(keywordSegments[^1].Get("rate") is EvidenceNull
            && keywordSegments[^1].Get("operation_seq") is EvidenceInteger { Value: var seq } && seq == 2,
            "Unconfirmed keyword state stays unknown; regressing operations and other sessions cannot restore it");
        var refresh = Obj("""
            {"zone":"res","element":"fire","parameter_keys":["a","b"],"parameter_snapshots":[
              {"ts_ms":1000,"operation_seq":1,"status":"attribute_parameters_observed","bb_values":{"a":-10,"b":-5}},
              {"ts_ms":1500,"operation_seq":2,"status":"attribute_parameters_observed","bb_values":{"a":-10}},
              {"ts_ms":2000,"operation_seq":3,"status":"attribute_parameters_observed","bb_values":{"a":0,"b":0}}]}
            """);
        var refreshSegments = ReportBuffEvents.Segments(1000, 2000, [], [refresh]);
        check(refreshSegments.Count == 3 && refreshSegments[0].Get("rate") is EvidenceReal { Value: 15 }
            && refreshSegments[1].Get("rate") is EvidenceNull && refreshSegments[2].Get("rate") is EvidenceReal { Value: 0 },
            "Resistance refresh sums observed negative points, distinguishes missing parameters and retains observed zero");
        check(ReportBuffEvents.Summaries([refresh]).Single() == "减抗/fire 按包内实际减抗点数更新",
            "Packet-updated resistance describes the observed point source without inventing a fixed percentage");
        var delayed = Obj("""{"zone":"amp","base_rate":0.1,"delayed_add_rate":0.2,"delay_sec":0.5}""");
        var delayedSegments = ReportBuffEvents.Segments(1000, 2000, [], [delayed]);
        check(delayedSegments.Count == 2 && delayedSegments[0].Get("end_ts_ms") is EvidenceInteger { Value: var transition } && transition == 1500
            && delayedSegments[1].Get("mode") is EvidenceText { Value: "dynamic_after_delay" },
            "A delayed change splits at its original time rather than interpolating between observed values");
        var root = Path.Combine(Path.GetTempPath(), "endfield-report-buffs-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var builder = ReportBuffEvents.Load(new ResourceFiles(root));
            var record = Obj("""
                {"ts_ms":1000,"line_no":3,"event_key":"unknown","raw_event_key":"unknown","uid":"u","raw_duration_ms":4000,
                 "snapshot_end_ts_ms":1800,"snapshot_end_line_no":8,"snapshot_update":true,"source_character_key":"source",
                 "target_enemy_key":"enemy","target_enemy_name":"Enemy","bb_keys":["z","a","z"],"bb_values":{},
                 "creation_observations":[{"line_no":3}],"dynamic_bb_events":[{"line_no":4}]}
                """);
            var before = EvidenceJsonSignature.Sorted(record);
            var result = builder.Build([record], [], 1200, 2000);
            var row = result.Events.Single();
            check(row.Get("status") is EvidenceText { Value: "filtered" } && row.Get("target_character_key") is EvidenceText { Value: "enemy" }
                && row.Get("end_source") is EvidenceText { Value: "snapshot_update" },
                "A filtered BUFF remains in the full report with its enemy identity and observed lifetime boundary");
            check(row.Get("end_ts_ms") is EvidenceInteger { Value: var observedEnd } && observedEnd == 1800
                && row.Get("start_ms_from_battle") is EvidenceInteger { Value: var offset } && offset == -200
                && row.Get("raw_duration_ms") is EvidenceInteger { Value: var nominal } && nominal == 4000,
                "Report offsets retain pre-battle observations, the snapshot end and the independent nominal duration");
            check(row.Get("bb_keys") is EvidenceArray keys && keys.Items.OfType<EvidenceText>().Select(value => value.Value).SequenceEqual(["a", "z"]),
                "Blackboard keys are unique and sorted for consistent evidence display");
            check(before == EvidenceJsonSignature.Sorted(record) && !ReferenceEquals(row.Get("creation_observations"), record.Get("creation_observations"))
                && !ReferenceEquals(row.Get("dynamic_bb_events"), record.Get("dynamic_bb_events")),
                "Detailed report evidence owns its nested observations and never changes captured ingestion records");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
