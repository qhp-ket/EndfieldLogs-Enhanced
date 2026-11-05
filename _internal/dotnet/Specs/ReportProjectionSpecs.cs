using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportProjectionSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool, string> check)
    {
        LiveParticipantCacheSpecs.Run(check);
        var root = Path.Combine(Path.GetTempPath(), "endfield-report-projection-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ResourceFiles files = new(root);
            BattleIngestionStream stream = new(BattleIngestionResources.Load(files));
            string[] lines = [
                "[00:00:00.900] SKILL_CAST_START skill=chr_0001_test_skill owner=chr_0001_test ownerId=17 inst=cast",
                "[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7",
                "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=60 crit=1",
                "[00:00:01.100] POISE_V1 type=PoiseDamage source=chr_0001_test_skill value=4 cur=12",
                "[00:00:01.110] ATB_UPDATE owner=chr_0001_test ownerId=17 atb=2 delta=1 recoverySpeed=3 tick=100 reason=AddValue",
                "[00:00:01.200] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=40",
                "[00:00:01.300] SKILL_CAST_END inst=cast",
                "[00:00:01.500] OFFICIAL_TIMER_END gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=400",
            ];
            stream.Accept(lines.Select((line, index) => (index + 1, line)));
            var input = BattleReportInput.Capture(stream);
            check(input.Calculation.Baseline.Hits.Count == 2 && input.Sources.PoiseEvents.Count == 1 && input.Sources.Casts.Count == 1,
                "One production snapshot owns hits, cast lifecycle and poise observations");
            check(input.Sources.Casts[0].Get("source_character_key") is EvidenceText { Value: "chr_0001_test" }
                && input.Sources.Casts[0].Get("end_line_no") is EvidenceInteger { Value: var endLine } && endLine == 7,
                "Cast projection preserves the external source identity and explicit end-line boundary");
            check(input.Sources.AtbEvents[0].Get("owner_actor_id") is EvidenceText { Value: "17" }
                && input.Sources.AtbEvents[0].Get("client_tick_ms") is EvidenceReal { Value: 100 },
                "Energy evidence uses the existing report contract's actor and client-clock field names");
            var analysis = BattleReportAnalysis.Load(files);
            var result = analysis.Analyze(input, string.Join('\n', lines), includeDebug: true);
            var withBuff = input with { Calculation = input.Calculation with { Records = [Obj("""
                {"ts_ms":1050,"line_no":2,"event_key":"unknown_buff","uid":"observed-buff","raw_duration_ms":100,
                 "source_character_key":"chr_0001_test","target_character_key":"chr_0001_test","bb_values":{}}
                """)] } };
            var described = analysis.Analyze(withBuff, string.Join('\n', lines), includeDebug: true);
            check(described.Calculation?.BuffEvents is { Count: 1 } buffs
                && buffs[0].Get("uid") is EvidenceText { Value: "observed-buff" }
                && buffs[0].Get("status") is EvidenceText { Value: "filtered" },
                "The production report entry retains a non-allocating observed BUFF in its detailed output");
            check(described.Participants.Participants.Single().Get("total_damage") is EvidenceInteger { Value: var unchangedDamage } && unchangedDamage == 100
                && withBuff.Calculation.Records[0].Get("status") is EvidenceNull,
                "BUFF descriptions do not change recorded damage or mutate the transferred source record");
            check(result.Calculation is { Hits.Count: 2, DebugHits.Count: 2 } && result.Participants.Participants.Count == 1,
                "Production factories connect source preparation, timing, allocation, debug and participant projection");
            var participant = result.Participants.Participants.Single();
            check(participant.Get("total_damage") is EvidenceInteger { Value: var damage } && damage == 100
                && participant.Get("total_rd") is EvidenceReal { Value: 100 } && participant.Get("dps") is EvidenceReal { Value: 250 },
                "Observed 100 damage over the server's 400ms yields 250 DPS and conserves rDMG");
            check(participant.Get("max_hit") is EvidenceInteger { Value: var maximum } && maximum == 100,
                "The two same-skill hits 100ms apart form one 100-damage visual group");
            check(result.Calculation!.Hits[0].Evidence.Get("poise_damage") is EvidenceObject poise
                && poise.Get("value") is EvidenceReal { Value: 4 } && poise.Get("current_value") is EvidenceReal { Value: 12 },
                "An exact-time, exact-skill poise observation reaches the calculated hit");
            check(result.Calculation.Hits[0].Evidence.Get("critical_context") is EvidenceObject critical
                && critical.Get("status") is EvidenceText { Value: "unavailable" }
                && result.Calculation.DebugHits[0].Get("critical_context") is EvidenceObject,
                "The connected report and debug output retain explicit unavailable critical evidence");
            check(result.Timeline is { Events.Count: 2, Casts.Count: 1, RoleSkillStats.Count: 1, AtbEvents.Count: 1 },
                "The production report entry emits damage events, cast export, grouped skill statistics and energy observations");
            var timeline = result.Timeline!;
            check(timeline.Events[0].Get("ts_ms_from_start") is EvidenceInteger { Value: var offset } && offset == 80
                && timeline.Events[0].Get("actual_start_ms_from_start") is EvidenceInteger { Value: var castOffset } && castOffset == -80,
                "Damage and pre-battle cast coordinates share the server-duration scale without clamping the cast");
            check(timeline.Events[0].Get("actual_duration_ms") is EvidenceInteger { Value: var castDuration } && castDuration == 400
                && timeline.Casts[0].Get("recovers_energy") is EvidenceBoolean { Value: true },
                "Observed cast duration remains unscaled and the nearest predecessor owns the recorded energy gain");
            check(timeline.RoleSkillStats[0].Get("cast_count") is EvidenceInteger { Value: var casts } && casts == 1
                && timeline.RoleSkillStats[0].Get("avg_damage") is EvidenceReal { Value: 100 },
                "Two hits in one skill timeline group produce one cast averaging the full 100 damage");
            check(result.Calculation.DebugHits[0].Get("timeline_group_key") is EvidenceText
                && input.Calculation.Baseline.Hits[0].Evidence.Get("timeline_group_key") is EvidenceNull,
                "Detailed evidence carries the final skill group without mutating source hit identity");
            check(input.Calculation.Baseline.Hits[0].Evidence.Get("poise_damage") is EvidenceNull,
                "Preparing report observations leaves the captured hit evidence untouched");
            stream.Accept([(9, "[00:00:01.700] HP_V2 #3 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=900")]);
            var replay = analysis.Analyze(input, string.Join('\n', lines));
            check(replay.Participants.Participants.Single().Get("total_damage") is EvidenceInteger { Value: var oldDamage } && oldDamage == 100
                && input.Participants.Totals["chr_0001_test"].Get("hit_count") is EvidenceInteger { Value: var count } && count == 2,
                "Later ingestion cannot alter the transferred report or its captured participant counters");
            ((Dictionary<string, EvidenceValue>)participant.Fields)["total_damage"] = new EvidenceInteger(-1);
            check(replay.Participants.Participants.Single().Get("total_damage") is EvidenceInteger { Value: var isolated } && isolated == 100,
                "Reports returned from repeated analysis are independent objects");
            using CancellationTokenSource cancel = new();
            cancel.Cancel();
            try { analysis.Analyze(input, string.Join('\n', lines), cancellationToken: cancel.Token); check(false, "Cancelled analysis ran"); }
            catch (OperationCanceledException) { check(true, "Cancellation stops analysis before source preparation"); }

            var ambiguous = input with
            {
                Calculation = input.Calculation with { Records = [Obj("""{"uid":"i","target_actor_id":"o","event_key":"s","ts_ms":0,"line_no":0}""")] },
                Sources = input.Sources with
                {
                    Casts = [Obj("""{"owner_id":"o","skill_inst_id":"i","skill":"s","ts_ms":0,"line_no":0,"end_ts_ms":200}"""),
                             Obj("""{"owner_id":"o","skill_inst_id":"i","skill":"s","ts_ms":0,"line_no":0,"end_ts_ms":200}""")],
                    DynamicEvents = [Obj("""{"owner_id":"o","instance_id":"i","skill_key":"s","ts_ms":100,"line_no":1}""")],
                },
            };
            var prepared = ReportSourcePreparation.Prepare(ambiguous.Calculation, ambiguous.Sources);
            check(prepared.Calculation.Records[0].Get("dynamic_bb_events") is EvidenceArray { Items.Count: 1 } events
                && ((EvidenceObject)events.Items[0]).Get("binding_error") is EvidenceText { Value: "ambiguous_skill_instance" },
                "The single BUFF binding sees ambiguity later discovered on the same cast observation");
            check(prepared.Calculation.Baseline.Hits.All(hit => hit.Evidence.Get("dynamic_bb_observations") is EvidenceArray { Items.Count: 0 }),
                "Dynamic cast or BUFF proximity never supplies missing per-hit blackboard evidence");
            check(ambiguous.Sources.DynamicEvents[0].Get("binding_error") is EvidenceNull,
                "Binding diagnostics stay in the report copy rather than changing captured evidence");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
