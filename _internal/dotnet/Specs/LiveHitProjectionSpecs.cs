using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Reporting;

internal static class LiveHitProjectionSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-live-hit-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var stream = new BattleIngestionStream(BattleIngestionResources.Load(new ResourceFiles(root)));
            stream.Accept(1, "[00:00:01.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=100 eHP=1000");
            var hit = stream.Hits.Hits.Single();
            LiveHitProjectionCache cache = new();
            var first = cache.Capture(hit);
            ((Dictionary<string, EvidenceValue>)first.Evidence.Fields)["hit_value"] = new EvidenceInteger(-1);
            var again = cache.Capture(hit);
            check(cache.ProjectedHits == 1 && cache.ReusedHits == 1
                && EvidenceJson.PythonEquals(again.Evidence, ReportHitInput.Capture(hit).Evidence),
                "An unchanged live hit reuses its detached projection without exposing the cached root");
            var nested = (EvidenceObject)again.Evidence.Get("packet_modifier_uids");
            var protectedChild = false;
            try { ((IDictionary<string, EvidenceValue>)nested.Fields)["attacker"] = EvidenceNull.Value; }
            catch (NotSupportedException) { protectedChild = true; }
            check(protectedChild && ((EvidenceArray)nested.Get("attacker")).Items.Count == 0,
                "Shared projection descendants reject writes instead of exposing cached evidence");

            stream.Accept(2, "[00:00:01.100] BASELINE #1 1=5");
            var late = cache.Capture(hit);
            check(cache.ProjectedHits == 2 && first.Baseline.Count == 0 && late.Baseline[1] is EvidenceReal { Value: 5 }
                && EvidenceJson.PythonEquals(late.Evidence, ReportHitInput.Capture(hit).Evidence),
                "Late packet evidence invalidates its hit while the earlier capture remains unchanged");
            var protectedBaseline = false;
            try { ((IDictionary<BigInteger, EvidenceValue>)late.Baseline)[1] = new EvidenceReal(-1); }
            catch (NotSupportedException) { protectedBaseline = true; }
            check(protectedBaseline && ReferenceEquals(late.Baseline, FrozenEvidence.CaptureNumbers(late.Baseline))
                && cache.Capture(hit).Baseline[1] is EvidenceReal { Value: 5 },
                "Numeric live evidence rejects writes and can be retained by later caches without duplicating its protected map");
            stream.Packets.ObserveAttributeReport(1, EvidenceJson.Parse("{\"reportPresent\":true}"));
            var present = cache.Capture(hit);
            stream.Packets.ObserveAttributeReport(1, EvidenceJson.Parse("{\"reportPresent\":false}"));
            var conflict = cache.Capture(hit);
            check(present.Evidence.Get("packet_attribute_report_present") is EvidenceBoolean { Value: true }
                && conflict.Evidence.Get("packet_attribute_report_unresolved") is EvidenceBoolean { Value: true }
                && EvidenceJson.PythonEquals(conflict.Evidence, ReportHitInput.Capture(hit).Evidence),
                "Conflicting late packet observations retract a previously cached report-presence proof");
            stream.Packets.ObserveModifierHandles(1, EvidenceJson.Parse("{\"attacker\":[{\"index\":0,\"buff_inst_id\":123}],\"defender\":[]}"));
            var handles = cache.Capture(hit);
            check(EvidenceJson.PythonEquals(handles.Evidence, ReportHitInput.Capture(hit).Evidence)
                && handles.Evidence.Get("packet_modifier_handles") is EvidenceObject,
                "Late modifier identities enter the next projection without mutating earlier captures");
            stream.Accept(3, "[00:00:02.000] HP_V2 #2 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=50 eHP=950");
            var projections = stream.Hits.Hits.Select(cache.Capture).ToArray();
            check(cache.ProjectedHits == 6 && projections.Length == 2 && projections[1].Baseline[1] is EvidenceReal { Value: 5 },
                "Appending a new hit projects only that hit and preserves inherited packet baselines");
            var input = BattleReportInput.CaptureLive(stream, cache, new(), new(2026, 10, 29));
            var source = BattleReportInput.Capture(stream, new(2026, 10, 29));
            check(input.Calculation.Baseline.Hits.Zip(source.Calculation.Baseline.Hits)
                .All(pair => EvidenceJson.PythonEquals(pair.First.Evidence, pair.Second.Evidence)),
                "The live capture boundary preserves the public report capture's complete hit evidence");
            var publicCapture = ReportHitInput.Capture(hit);
            ((Dictionary<string, EvidenceValue>)((EvidenceObject)publicCapture.Evidence.Get("baseline")).Fields)["1"] = new EvidenceInteger(-1);
            check(((EvidenceObject)cache.Capture(hit).Evidence.Get("baseline")).Get("1") is EvidenceReal { Value: 5 },
                "Public mutable projections remain independent of the live engine's immutable cache");
            SummaryCapture(check, root);
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static void SummaryCapture(Action<bool, string> check, string root)
    {
        ResourceFiles files = new(root);
        var resources = BattleIngestionResources.Load(files);
        BattleIngestionStream stream = new(resources);
        string[] lines = [
            "[00:00:01.000] ATB_UPDATE owner=chr_0001_alpha ownerId=11 value=20 delta=5\n",
            "[00:00:01.000] POISE_V1 type=PoiseDamage value=5 cur=10 source=skill_test\n",
            "[00:00:01.000] BUFF_ATTR_REFRESH {\"schemaVersion\":1}\n",
            "[00:00:01.000] BB_MODIFY_DYNAMIC seq=1 tick=1 inst=7 ownerId=11 skill=unknown actionId=1 value=2 identity={\"schemaVersion\":1}\n",
            "[00:00:01.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=100 eHP=1000\n",
        ];
        stream.Accept(lines.Select((text, index) => (index + 1, text)));
        DateOnly date = new(2026, 10, 29);
        var full = BattleReportInput.Capture(stream, date);
        var summary = BattleReportInput.CaptureLive(stream, new(), new(), date, summary: true);
        check(full.Sources is { AtbEvents.Count: 1, PoiseEvents.Count: 1, RefreshEvents.Count: 1, DynamicEvents.Count: 1 }
            && summary.Sources is { AtbEvents.Count: 0, PoiseEvents.Count: 0, RefreshEvents.Count: 0, DynamicEvents.Count: 1 }
            && full.Sources.DynamicEvents.Zip(summary.Sources.DynamicEvents).All(pair => EvidenceJson.PythonEquals(pair.First, pair.Second)),
            "Summary capture omits display histories while retaining dynamic calculation evidence");
        var analysis = BattleReportAnalysis.Load(files, TimeZoneInfo.Utc);
        var expectedSummary = analysis.BuildSnapshot(full, "", summary: true)!;
        check(EvidenceJson.PythonEquals(expectedSummary, analysis.BuildSnapshot(summary, "", summary: true)!),
            "Capturing summary sources directly preserves the full-capture summary's damage, contributions and quality");
        var before = analysis.BuildSnapshot(full, "")!;
        var laterFull = BattleReportInput.CaptureLive(stream, new(), new(), date);
        check(laterFull.Sources is { AtbEvents.Count: 1, PoiseEvents.Count: 1, RefreshEvents.Count: 1 }
            && EvidenceJson.PythonEquals(before, analysis.BuildSnapshot(laterFull, "")!),
            "Requesting a full report after summary capture retains all original display histories and evidence");
        LiveBattleEngine engine = new(resources, analysis, date, TimeZoneInfo.Utc);
        var liveSummary = engine.Snapshot(lines, summary: true)!;
        var liveFull = engine.Snapshot(lines)!;
        check(EvidenceJson.PythonEquals(liveSummary, expectedSummary) && EvidenceJson.PythonEquals(liveFull, before)
            && EvidenceJson.PythonEquals(engine.Snapshot(lines, summary: true)!, expectedSummary)
            && engine.Diagnostics.TraceReplays == 0,
            "Switching live summary to full and back preserves complete output without replaying ingestion");
    }
}
