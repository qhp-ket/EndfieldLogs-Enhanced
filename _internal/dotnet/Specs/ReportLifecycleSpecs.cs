using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportLifecycleSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-report-calculation-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            ResourceFiles files = new(root);
            var resources = BattleIngestionResources.Load(files);
            BattleIngestionStream stream = new(resources);
            string[] lines = [
                "[00:00:00.500] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=100",
                "[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START challengeStartTs=7",
                "[00:00:01.200] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=60",
                "[00:00:01.400] HP_V2 #3 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=40",
                "[00:00:01.500] OFFICIAL_TIMER_END gameId=challenge source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE isPass=1 passTime=400",
                "[00:00:01.600] HP_V2 #4 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_skill hit=200",
            ];
            stream.Accept(lines.Select((line, index) => (index + 1, line)));
            check(stream.Hits.Hits.Count == 4, "Connected report tests begin with four real ingested HP events");
            var input = ReportCalculationInput.Capture(stream);
            var timer = ReportTimingInput.Capture(stream);
            var before = string.Join('|', input.Baseline.Hits.Select(hit => EvidenceJsonSignature.Sorted(hit.Evidence)));
            var selected = ReportLifecycle.Load(files).Select(input, timer, string.Join('\n', lines));
            check(selected.Input.Baseline.Hits.Count == 2 && selected.Input.Baseline.Hits.All(hit =>
                ((EvidenceInteger)hit.Evidence.Get("line_no")).Value is var line && line > 2 && line < 5),
                "Official lifecycle selects hits by explicit line membership, excluding previous and subsequent damage");
            check(selected.DurationMs == 400 && selected.Window is { StartMs: var start, EndMs: var end, HasGameTimer: true }
                && start == 1000 && end == 1500 && selected.TimelineScale == .8,
                "Server pass duration remains separate from the observed 500ms wall interval");
            check(selected.OffsetMs(1200) == 160 && selected.OffsetMs(900) == 0 && selected.OffsetMs(900, clamp: false) == -80,
                "Shared coordinates preserve exact ties-to-even conversion, optional clamping and pre-battle casts");
            var calculation = ReportCalculation.Load(files);
            var result = calculation.Calculate(selected, string.Join('\n', lines), includeDebug: true);
            check(result.Calculation is { Hits.Count: 2, DebugHits.Count: 2 } computed
                && computed.Totals.GetValueOrDefault("chr_0001_test") == 100,
                "Real resource factories connect ingestion, timing, baseline, windows, allocation, conservation and debug rows");
            check(result.Calculation!.DamageBasis.Get("rdps_conservation_ok") is EvidenceBoolean { Value: true }
                && result.Calculation.DamageBasis.Get("rdps_strict_ok") is EvidenceBoolean { Value: false },
                "Missing action/packet evidence keeps strict quality false without losing the observed 100 damage");
            check(before == string.Join('|', input.Baseline.Hits.Select(hit => EvidenceJsonSignature.Sorted(hit.Evidence)))
                && stream.Hits.Hits.Count == 4 && timer.GameElapsedMs == 400,
                "Report calculation leaves captured source evidence and the ingestion state intact");
            var second = calculation.Calculate(selected, includeDebug: true);
            check(EvidenceJsonSignature.Sorted(second.Calculation!.DamageBasis) == EvidenceJsonSignature.Sorted(result.Calculation.DamageBasis),
                "Repeated analysis of an owned snapshot yields identical quality and accounting");
            using CancellationTokenSource cancelled = new();
            cancelled.Cancel();
            try { calculation.Calculate(selected, cancellationToken: cancelled.Token); check(false, "Cancelled report ran"); }
            catch (OperationCanceledException) { check(true, "Cancellation stops the connected report before computation"); }
            var empty = selected with { Window = null, Input = selected.Input with { Baseline = selected.Input.Baseline with { Hits = [] } } };
            check(calculation.Calculate(empty).Calculation is null, "An empty official scope never falls back to previous-session hits");
            BattleIngestionStream isolated = new(resources);
            check(ReportCalculationInput.Capture(isolated).Baseline.Hits.Count == 0, "Concurrent resource reuse does not leak the previous report into another stream");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
