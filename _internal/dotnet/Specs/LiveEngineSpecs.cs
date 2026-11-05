using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveEngineSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-live-engine-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ResourceFiles files = new(root);
            var engine = LiveBattleEngine.Load(files, new(2026, 10, 29), TimeZoneInfo.Utc);
            const string first = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100\n";
            const string second = "[00:00:02.100] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=50\n";
            static EvidenceObject Battle(EvidenceObject report) => (EvidenceObject)report.Get("battle");
            static bool Damage(EvidenceObject report, int expected) => Battle(report).Get("total_damage") is EvidenceInteger value && value.Value == expected;
            var one = engine.Snapshot([first])!;
            var repeated = engine.Snapshot([first])!;
            check(Damage(one, 100) && Damage(repeated, 100) && engine.Diagnostics is { IngestedLines: 1, ReportBuilds: 1, CachedReads: 1 },
                "An unchanged read reuses its completed snapshot without parsing or allocating the same evidence again");
            ((Dictionary<string, EvidenceValue>)Battle(one).Fields)["total_damage"] = new EvidenceInteger(-1);
            check(Damage(engine.Snapshot([first])!, 100), "Caller mutation cannot poison the completed snapshot cache");
            var two = engine.Snapshot([first, second])!;
            check(Damage(two, 150) && engine.Diagnostics.IngestedLines == 2,
                "Appending a line advances persistent ingestion exactly once");
            var late = first.Replace("hit=100", "hit=20", StringComparison.Ordinal);
            var replaced = engine.Snapshot([late])!;
            check(Damage(replaced, 20) && engine.Diagnostics.TraceReplays == 1,
                "A shortened or replaced trace rebuilds its own session and retracts the old total");
            var summary = engine.Snapshot([late], summary: true)!;
            check(Damage(summary, 20) && summary.Get("quality_summary") is EvidenceObject && summary.Get("timeline_events") is EvidenceNull,
                "The same canonical live entry publishes compact summaries for native overlays");
            var other = LiveBattleEngine.Load(files, new(2026, 10, 29), TimeZoneInfo.Utc);
            check(Damage(other.Snapshot([second])!, 50) && Damage(engine.Snapshot([late])!, 20),
                "Separate live sessions keep ingestion, totals and published views independent");
            using CancellationTokenSource canceled = new();
            canceled.Cancel();
            var observed = false;
            try { engine.Snapshot([first, second], cancellationToken: canceled.Token); }
            catch (OperationCanceledException) { observed = true; }
            check(observed && Damage(engine.Snapshot([late])!, 20),
                "A canceled request publishes no replacement and leaves the last completed input intact");
            engine.Reset();
            check(engine.Snapshot([]) is null && Damage(engine.Snapshot([second])!, 50),
                "Reset removes old evidence and cached results before the next session");
            const string start = "[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7\n";
            engine.Reset();
            var clocked = engine.Snapshot([start, first], "[00:00:02.000] LIVE_TIMER_TICK elapsedMs=1000\n")!;
            var unclocked = engine.Snapshot([start, first])!;
            check(Battle(clocked).Get("duration_ms") is EvidenceInteger { Value: var duration } && duration == 1000
                && Battle(unclocked).Get("duration_ms") is EvidenceInteger plain && plain.Value != 1000,
                "An observer clock affects one snapshot and cannot become persistent timer evidence");
            engine.Reset();
            engine.Snapshot([start, first], "[00:00:02.000] LIVE_TIMER_TICK elapsedMs=1000\n", summary: true);
            var builds = engine.Diagnostics.ReportBuilds;
            var advanced = engine.Snapshot([start, first], "[00:00:02.500] LIVE_TIMER_TICK elapsedMs=1500\n", summary: true)!;
            check(engine.Diagnostics.ClockProjections == 1 && engine.Diagnostics.ReportBuilds == builds
                && Battle(advanced).Get("total_dps") is EvidenceReal { Value: 66.67 }
                && Battle(advanced).Get("battle_end_at") is EvidenceText { Value: "2026-10-29T00:00:02.500+00:00" },
                "A proven clock-only summary advances rates and ISO time without executing report allocation again");
            var regressed = engine.Snapshot([start, first], "[00:00:02.000] LIVE_TIMER_TICK elapsedMs=1000\n", summary: true)!;
            check(engine.Diagnostics.ReportBuilds == builds + 1 && Battle(regressed).Get("duration_ms") is EvidenceInteger shorter && shorter.Value == 1000,
                "A regressing observer clock takes the canonical semantic path");
            engine.Reset();
            const string future = "[00:00:04.000] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=50\n";
            engine.Snapshot([start, first, future], "[00:00:02.000] LIVE_TIMER_TICK elapsedMs=1000\n", summary: true);
            builds = engine.Diagnostics.ReportBuilds;
            var expanded = engine.Snapshot([start, first, future], "[00:00:05.000] LIVE_TIMER_TICK elapsedMs=4000\n", summary: true)!;
            check(engine.Diagnostics.ReportBuilds == builds + 1 && Damage(expanded, 150),
                "Future-dated evidence prevents clock reuse when the expanded window can admit another damage event");

            // Exercise the consumed live capture against the reusable public entry, including nested observations.
            string[] observations = [
                "[00:00:00.900] BUFF_START uid=7 id=buff_test owner=eny_0001_test ownerId=22 src=chr_0001_test srcId=11\n",
                "[00:00:00.950] BB_MODIFY_DYNAMIC seq=101 tick=1000 inst=7 ownerId=22 skill=buff_test actionId=45 value=200\n",
                "[00:00:01.000] SKILL_CAST_START skill=chr_0001_test_normal_skill owner=chr_0001_test ownerId=11 inst=cast\n",
                first,
                "[00:00:01.100] POISE_V1 type=PoiseDamage source=chr_0001_test_normal_skill value=4 cur=12\n",
                "[00:00:01.200] SKILL_CAST_END inst=cast\n",
                second,
            ];
            BattleIngestionStream source = new(BattleIngestionResources.Load(files));
            var publicAnalysis = BattleReportAnalysis.Load(files, TimeZoneInfo.Utc);
            var isolated = LiveBattleEngine.Load(files, new(2026, 10, 29), TimeZoneInfo.Utc);
            static void Poison(EvidenceValue value)
            {
                if (value is EvidenceObject obj)
                {
                    foreach (var nested in obj.Fields.Values) Poison(nested);
                    if (obj.Fields is Dictionary<string, EvidenceValue> fields) fields.Clear();
                }
                else if (value is EvidenceArray array) foreach (var nested in array.Items) Poison(nested);
            }
            for (var index = 0; index < observations.Length; index++)
            {
                source.Accept(index + 1, observations[index].TrimEnd('\n'));
                if (index < 4) continue;
                var prefix = observations.Take(index + 1).ToArray();
                var captured = BattleReportInput.Capture(source, new(2026, 10, 29));
                foreach (var compact in new[] { false, true })
                {
                    var expected = publicAnalysis.BuildSnapshot(captured, string.Concat(prefix), summary: compact);
                    var actual = isolated.Snapshot(prefix, summary: compact);
                    var withoutText = publicAnalysis.BuildSnapshot(captured, "", summary: compact);
                    var legacyInput = captured with { Calculation = captured.Calculation with { Ink = null } };
                    var legacy = publicAnalysis.BuildSnapshot(legacyInput, string.Concat(prefix), summary: compact);
                    check(EvidenceJson.PythonEquals(expected!, withoutText!) && EvidenceJson.PythonEquals(expected!, legacy!),
                        "Captured full and compact reports consume normalized ink observations without requiring legacy text");
                    check(EvidenceJson.PythonEquals(expected!, actual!),
                        "Owned live captures match reusable public reports after append and full/summary switches");
                    Poison(actual!);
                    check(EvidenceJson.PythonEquals(expected!, isolated.Snapshot(prefix, summary: compact)!),
                        "Mutating every returned nested container cannot affect ingestion or the cached snapshot");
                }
                check(captured.Calculation.Records.Single().Get("dynamic_bb_events") is EvidenceNull
                    && captured.Calculation.Baseline.Hits[0].Evidence.Get("poise_damage") is EvidenceNull
                    && captured.Sources.Casts[0].Get("dynamic_bb_events") is EvidenceNull,
                    "The public report entry keeps captured BUFF, hit and cast evidence reusable");
            }
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
