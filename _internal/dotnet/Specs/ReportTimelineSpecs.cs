using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportTimelineSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static ReportHitInput Hit(string json) => new(Obj(json), new Dictionary<BigInteger, EvidenceValue>(),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    public static void Run(Action<bool, string> check)
    {
        ReportHitInput[] hits = [
            Hit("""{"ts_ms":0,"character_key":"a","skill_key":"normal","target_enemy_key":"enemy","hit_value":10}"""),
            Hit("""{"ts_ms":1200,"character_key":"a","skill_key":"normal","target_enemy_key":"enemy","hit_value":20}"""),
            Hit("""{"ts_ms":2401,"character_key":"a","skill_key":"normal","target_enemy_key":"enemy","hit_value":30}"""),
        ];
        var grouped = ReportTimeline.AssignGroups(hits);
        check(EvidenceJson.PythonEquals(grouped[0].Evidence.Get("timeline_group_key"), grouped[1].Evidence.Get("timeline_group_key"))
            && !EvidenceJson.PythonEquals(grouped[1].Evidence.Get("timeline_group_key"), grouped[2].Evidence.Get("timeline_group_key")),
            "The skill group admits a 1200ms gap and starts a new group at 1201ms");
        check(hits[0].Evidence.Get("timeline_group_key") is EvidenceNull
            && grouped[2].Evidence.Get("ts_ms") is EvidenceInteger { Value: var time } && time == 2401,
            "Presentation grouping preserves original timestamps and captured hit objects");
        var privateHits = hits.Select(hit => hit with { Evidence = (EvidenceObject)EvidenceJson.Clone(hit.Evidence) }).ToArray();
        var privateGroups = ReportTimeline.AssignGroupsOwned(privateHits);
        check(privateGroups.Select(hit => EvidenceJsonSignature.Sorted(hit.Evidence)).SequenceEqual(
                grouped.Select(hit => EvidenceJsonSignature.Sorted(hit.Evidence)))
            && hits.All(hit => hit.Evidence.Get("timeline_group_key") is EvidenceNull),
            "Private grouping has identical gap boundaries and evidence without changing the independent captured input");
        SkillIdentityCatalog ids = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
        ReportTimeline timeline = new(ids, key => key, key => key, _ => null, new Dictionary<string, EvidenceObject>());
        var stats = timeline.SkillStats(grouped, ["a"]);
        check(stats.Single().Get("cast_count") is EvidenceInteger { Value: var count } && count == 2
            && stats[0].Get("total_damage") is EvidenceInteger { Value: var damage } && damage == 60
            && stats[0].Get("max_damage") is EvidenceInteger { Value: var maximum } && maximum == 30
            && stats[0].Get("avg_damage") is EvidenceReal { Value: 30 },
            "Skill statistics aggregate complete groups: 10+20 and 30 give two casts averaging 30");
        var input = new ReportCalculationInput(new(new([], new Dictionary<string, EvidenceObject>()), [], new Dictionary<string, HashSet<string>>()), [], [], []);
        var lifecycle = new ReportLifecycleResult(input, new ReportTimingInput { GameElapsedMs = 500 }, new(1000, 2000, "game_timer", "game_timer", true), null, null, false);
        var window = Obj("""{"uid":"b","event_key":"buff","event_name":"Buff","start_ts_ms":500,"end_ts_ms":2500,"source_character_key":"a","source_character_name":"A","target_character_key":"a","target_character_name":"A","effects":[],"snapshot_update":true,"end_is_observation_boundary":true}""");
        var record = Obj("""{"uid":"b","event_key":"buff","ts_ms":500,"raw_duration_ms":5000}""");
        var sources = new ReportSourceInput([], [], [], [], new Dictionary<string, long>(), []);
        var display = timeline.Build([], sources, lifecycle, [], [], [window], [record]);
        var privateDisplay = timeline.BuildOwned([], sources, lifecycle, [], [],
            [(EvidenceObject)EvidenceJson.Clone(window)], [(EvidenceObject)EvidenceJson.Clone(record)]);
        check(privateDisplay.Events.Select(EvidenceJsonSignature.Sorted).SequenceEqual(display.Events.Select(EvidenceJsonSignature.Sorted))
            && privateDisplay.Windows!.Select(EvidenceJsonSignature.Sorted).SequenceEqual(display.Windows!.Select(EvidenceJsonSignature.Sorted)),
            "Private timeline projection retains the same visible bounds, lifetime evidence and evaluated windows as the public entry");
        var buff = display.Events.Single();
        check(buff.Get("ts_ms_from_start") is EvidenceInteger { Value: var start } && start == 0
            && buff.Get("duration_ms") is EvidenceInteger { Value: var duration } && duration == 500,
            "Visible BUFF bounds are clipped to the battle and use its server-duration scale");
        check(buff.Get("actual_start_ms_from_start") is EvidenceInteger { Value: var actualStart } && actualStart == -250
            && buff.Get("actual_end_ms_from_start") is EvidenceInteger { Value: var actualEnd } && actualEnd == 750
            && buff.Get("actual_duration_ms") is EvidenceInteger { Value: var actualDuration } && actualDuration == 1000,
            "Recorded BUFF bounds remain available outside the clipped visible region");
        check(buff.Get("buff_lifetime") is EvidenceObject lifetime && lifetime.Get("expiry_ms_from_start") is EvidenceInteger { Value: var expiry }
            && expiry == 2250 && lifetime.Get("source") is EvidenceText { Value: "duration" },
            "The nominal BUFF expiry stays distinct from its snapshot observation boundary");
        check(window.Get("ts_ms_from_start") is EvidenceNull && record.Get("buff_lifetime") is EvidenceNull,
            "Timeline projection leaves allocation windows and raw lifetime evidence intact");
        var unknown = timeline.Build([], sources, lifecycle, [], [], [window], []);
        check(unknown.Events[0].Get("buff_lifetime") is EvidenceObject missing && missing.Get("expiry_ms_from_start") is EvidenceNull
            && missing.Get("source") is EvidenceText { Value: "unknown" },
            "An unknown BUFF expiry remains unknown rather than becoming the visible window end");
        var snapshotFields = new Dictionary<string, EvidenceValue>(window.Fields) { ["start_ts_ms"] = new EvidenceInteger(1000) };
        var snapshot = new EvidenceObject(snapshotFields);
        var snapshotDisplay = timeline.Build([], sources, lifecycle, [], [], [snapshot], []);
        check(snapshotDisplay.Windows?.Single().Get("rdps_snapshot_order_unresolved") is EvidenceBoolean { Value: true }
            && snapshotDisplay.Events.Single().Get("effects") is EvidenceArray { Items.Count: 0 }
            && snapshot.Get("rdps_snapshot_order_unresolved") is EvidenceNull,
            "A display query without a hit line retains unresolved snapshot order in owned report windows without changing allocation input");
    }
}
