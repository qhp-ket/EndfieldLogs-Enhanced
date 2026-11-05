using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Runtime.Realtime;

internal static class ReportExportSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool, string> check)
    {
        var exclusive = (EvidenceObject)EvidenceJson.ParseWithPairs("""
            {"branch":{"value":1},"branch":{"value":2},"items":[{"wide":9223372036854775808,"zero":-0.0,"bad":Infinity}]}
            """);
        var original = EvidenceJson.Clone(exclusive);
        var immutable = (EvidenceObject)EvidenceJson.TakeReadOnlyOwnership(exclusive);
        var item = (EvidenceObject)((EvidenceArray)immutable.Get("items")).Items[0];
        check(EvidenceJsonSignature.Sorted(immutable) == EvidenceJsonSignature.Sorted(original)
            && immutable.Fields.Keys.SequenceEqual(((EvidenceObject)original).Fields.Keys)
            && immutable.SourcePairs!.Select(pair => pair.Key).SequenceEqual(["branch", "branch", "items"])
            && immutable.SourcePairs!.Take(2).Select(pair => ((EvidenceInteger)((EvidenceObject)pair.Value).Get("value")).Value).SequenceEqual([1, 2]),
            "Owned immutable handoff preserves duplicate source evidence, field order and exact scalar representation");
        check(((IDictionary<string, EvidenceValue>)immutable.Fields).IsReadOnly
            && ((IDictionary<string, EvidenceValue>)item.Fields).IsReadOnly
            && ((IList<EvidenceValue>)((EvidenceArray)immutable.Get("items")).Items).IsReadOnly
            && ((IList<KeyValuePair<string, EvidenceValue>>)immutable.SourcePairs!).IsReadOnly
            && immutable.SourcePairs!.Take(2).All(pair => ((IDictionary<string, EvidenceValue>)((EvidenceObject)pair.Value).Fields).IsReadOnly)
            && ReferenceEquals(immutable, EvidenceJson.TakeReadOnlyOwnership(immutable)),
            "Shared detail evidence is recursively protected, including arrays and duplicate-source branches");
        var editable = (EvidenceObject)EvidenceJson.Clone(immutable);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)editable.Get("items")).Items[0]).Fields)["wide"] = EvidenceNull.Value;
        check(item.Get("wide") is EvidenceInteger && item.Get("zero") is EvidenceReal negativeZero && BitConverter.DoubleToInt64Bits(negativeZero.Value) < 0,
            "Explicit editable reads remain independent and cannot change the shared snapshot or signed zero");
        var shared = Obj("""{"uid":9223372036854775808,"bad":Infinity,"nested":{"value":1}}""");
        var protectedValue = FrozenEvidence.Capture(shared);
        var privateReport = new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["first"] = shared, ["second"] = shared, ["protected"] = protectedValue,
            ["items"] = new EvidenceArray([new EvidenceInteger(BigInteger.One << 63), new EvidenceReal(double.NaN)]),
        });
        var expectedTransport = EvidenceJsonSignature.Sorted(SnapshotQuality.JsonEvidence(privateReport));
        var transferred = (EvidenceObject)SnapshotQuality.JsonEvidenceOwned(privateReport);
        check(ReferenceEquals(transferred, privateReport) && ReferenceEquals(transferred.Get("first"), shared)
            && EvidenceJsonSignature.Sorted(transferred) == expectedTransport,
            "Private report containers transfer without changing transport numbers, field order or nested evidence");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)shared.Get("nested")).Fields)["value"] = new EvidenceInteger(-1);
        check(((EvidenceObject)((EvidenceObject)transferred.Get("second")).Get("nested")).Get("value") is EvidenceInteger { Value.IsOne: true },
            "Repeated private containers become independent writable output branches");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)transferred.Get("protected")).Fields)["uid"] = EvidenceNull.Value;
        check(((EvidenceObject)protectedValue).Get("uid") is EvidenceInteger
            && ((EvidenceObject)protectedValue).Get("bad") is EvidenceReal { Value: double.PositiveInfinity },
            "Transport output never exposes shared immutable resources as writable report data");
        var payload = Obj("""{"z":1,"a":[true,null,"中文"],"n":1.0}""");
        check(ReportIntegrity.CanonicalJson(payload) == "{\"a\":[true,null,\"中文\"],\"n\":1.0,\"z\":1}",
            "Uploader fingerprints use sorted compact UTF-8 JSON and preserve float identity");
        var evidence = SnapshotQuality.JsonEvidence(Obj("""{"uid":9223372036854775808,"safe":9007199254740991,"bad":Infinity}""")) as EvidenceObject;
        check(evidence?.Get("uid") is EvidenceText { Value: "9223372036854775808" }
            && evidence.Get("safe") is EvidenceInteger && evidence.Get("bad") is EvidenceNull,
            "Quality evidence retains wide identities as decimal strings and replaces nonfinite values with null");
        var qualityInput = Obj("""
            {"battle":{"duration_ms":1000,"time_source":"game_timer","timer_integrity_ok":true,"timer_integrity_reasons":[],
                        "timer_window_valid":true,"timer_start_inferred":false},
             "rdps_preflight":{"ok":true,"blocker_count":0,"blockers":[]},
             "rdps_damage_basis":{"rdps_preflight_ok":true,"rdps_strict_ok":true,"rdps_conservation_ok":true,"hit_count":1}}
            """);
        check(SnapshotQuality.Build(qualityInput).Get("status") is EvidenceText { Value: "verified" },
            "Only complete canonical timing and allocation evidence produces a verified snapshot");
        var missing = SnapshotQuality.Build(Obj("{}"));
        check(missing.Get("status") is EvidenceText { Value: "unavailable" }
            && missing.Get("rdps") is EvidenceObject rdps && rdps.Get("reasons") is EvidenceArray reasons
            && reasons.Items.Contains(new EvidenceText("missing_rdps_preflight")),
            "Missing evidence stays unavailable with explicit reasons rather than passing a truthiness test");
        var root = Path.Combine(Path.GetTempPath(), "endfield-report-export-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ResourceFiles files = new(root);
            var resources = BattleIngestionResources.Load(files);
            var analysis = BattleReportAnalysis.Load(files, TimeZoneInfo.Utc);
            BattleIngestionStream stream = new(resources);
            string[] lines = [
                "[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7",
                "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100",
                "[00:00:01.500] OFFICIAL_TIMER_END gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=400",
            ];
            stream.Accept(lines.Select((line, index) => (index + 1, line)));
            var input = BattleReportInput.Capture(stream, new(2026, 10, 29));
            var report = analysis.BuildReport(input, string.Join('\n', lines), "synthetic.log", includeDebug: true)!;
            var battle = (EvidenceObject)report.Get("battle");
            check(battle.Get("duration_ms") is EvidenceInteger { Value: var duration } && duration == 400
                && battle.Get("total_dps") is EvidenceReal { Value: 250 }
                && battle.Get("battle_end_at") is EvidenceText { Value: "2026-10-29T00:00:01.500+00:00" },
                "A complete report separates the server's 400ms rate denominator from its 500ms observed wall interval");
            check(battle.Get("timer_integrity_ok") is EvidenceBoolean { Value: true }
                && battle.Get("clear_flag") is EvidenceBoolean { Value: true }
                && battle.Get("battle_fingerprint") is EvidenceText { Value.Length: 64 },
                "Official completion produces validated clear evidence and the canonical report fingerprint");
            check(report.Get("debug_context") is EvidenceObject && report.Get("snapshot_quality") is EvidenceObject
                && report.Get("debug_hits") is EvidenceArray { Items.Count: 1 }
                && report.Get("timeline_events") is EvidenceArray { Items.Count: 1 },
                "The external report exposes analysis, debug and quality together rather than returning only totals");
            var replay = analysis.BuildReport(input, string.Join('\n', lines), "synthetic.log", includeDebug: true)!;
            ((Dictionary<string, EvidenceValue>)battle.Fields)["total_damage"] = new EvidenceInteger(-1);
            check(((EvidenceObject)replay.Get("battle")).Get("total_damage") is EvidenceInteger { Value: var damage } && damage == 100,
                "Changing a returned report cannot alter another analysis or the captured ingestion snapshot");
            var standard = analysis.BuildReport(input, string.Join('\n', lines), "synthetic.log")!;
            var expectedHistory = (EvidenceObject)LiveSnapshotPublisher.TransportCopy(LiveReportProjection.Overlay(standard));
            var history = analysis.BuildHistorySnapshot(stream, new(2026, 10, 29), string.Join('\n', lines), "synthetic.log")!;
            var expectedSignature = EvidenceJsonSignature.Sorted(expectedHistory);
            check(EvidenceJsonSignature.Sorted(history) == expectedSignature,
                "Private history calculation preserves every field and numeric category of the public report, overlay and transport chain");
            var timelineEvent = (EvidenceObject)((EvidenceArray)history.Get("timeline_events")).Items[0];
            ((Dictionary<string, EvidenceValue>)timelineEvent.Fields)["skill_key"] = new EvidenceText("consumer mutation");
            ((Dictionary<string, EvidenceValue>)((EvidenceObject)history.Get("battle")).Fields)["duration_ms"] = new EvidenceInteger(-1);
            var historyAgain = analysis.BuildHistorySnapshot(stream, new(2026, 10, 29), string.Join('\n', lines), "synthetic.log")!;
            check(EvidenceJsonSignature.Sorted(historyAgain) == expectedSignature
                && EvidenceJsonSignature.Sorted(LiveSnapshotPublisher.TransportCopy(LiveReportProjection.Overlay(
                    analysis.BuildReport(input, string.Join('\n', lines), "synthetic.log")!))) == expectedSignature,
                "Mutating a history snapshot cannot alter captured input, ingestion state or a later public report");
            stream.Accept(4, "[00:00:01.700] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=50");
            check(EvidenceJsonSignature.Sorted(historyAgain) == expectedSignature,
                "Later ingestion cannot change a completed history snapshot");
            BattleIngestionStream noHits = new(resources);
            noHits.Accept([(1, lines[0]), (2, lines[^1])]);
            var empty = analysis.BuildReport(BattleReportInput.Capture(noHits, new(2026, 10, 29)), lines[0] + "\n" + lines[^1])!;
            check(((EvidenceObject)empty.Get("battle")).Get("clear_flag") is EvidenceBoolean { Value: false }
                && ((EvidenceObject)empty.Get("battle")).Get("duration_ms") is EvidenceInteger { Value.IsZero: true }
                && ((EvidenceObject)empty.Get("snapshot_quality")).Get("status") is EvidenceText { Value: "unavailable" },
                "An officially completed scope with no damage remains an unavailable empty report and cannot inherit a previous battle");
            var emptyInput = BattleReportInput.Capture(new BattleIngestionStream(resources), new(2026, 10, 29));
            check(analysis.BuildReport(emptyInput, "", allowEmpty: true) is null,
                "A live source without reportable evidence returns no report when explicitly allowed");
            check(ReportExport.LocalIso(new(2026, 10, 29), 86400001, TimeZoneInfo.Utc) == "2026-10-30T00:00:00.001+00:00",
                "Report dates retain millisecond precision across midnight rollover");
            BattleIngestionStream dynamic = new(resources);
            dynamic.Accept(1, """
                [00:00:01.000] BB_MODIFY_DYNAMIC seq=1 tick=1 inst=7 ownerId=11 skill=unknown actionId=1 value=2 identity={"schemaVersion":1,"eventContext":{"owner_id":11,"inst_id":7}}
                """);
            var source = ReportSourceInput.Capture(dynamic);
            check(source.DynamicEvents.Single().Get("identity") is EvidenceObject identity && identity.Get("eventContext") is EvidenceArray { Items.Count: 2 }
                && dynamic.Buffs.DynamicEvents.Single().Get("identity") is EvidenceObject rawIdentity && rawIdentity.Get("eventContext") is EvidenceObject,
                "Report capture preserves the existing nested object-pairs contract while ingestion keeps its typed identity object");
            stream.Accept(5, "[00:00:01.800] IDENTITY_INFERENCE source=legacy");
            var inferredInput = BattleReportInput.Capture(stream, new(2026, 10, 29));
            var inferred = analysis.BuildReport(inferredInput, "", "synthetic.log")!;
            check(((EvidenceObject)inferred.Get("battle")).Get("boss_identity_source") is EvidenceText { Value: "trace_inference" },
                "Captured identity provenance no longer needs a full trace-text scan during report export");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
