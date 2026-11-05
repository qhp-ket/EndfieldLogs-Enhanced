using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Realtime;

internal static class LiveSessionSpecs
{
    private const string First = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    private const string Second = "[00:00:02.100] HP_V2 #2 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=50";
    private const string Start = "[00:00:01.000] OFFICIAL_TIMER_START gameId=challenge";

    private static EvidenceObject Value(int number) => (EvidenceObject)EvidenceJson.Parse($"{{\"value\":{number}}}");
    private static bool Is(EvidenceObject? result, int number) => result?.Get("value") is EvidenceInteger value && value.Value == number;
    private static EvidenceObject? Get(Task<EvidenceObject?> task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
    private static void Wait(ManualResetEventSlim signal) { if (!signal.Wait(TimeSpan.FromSeconds(15))) throw new TimeoutException("Live session barrier"); }

    public static void Run(Action<bool, string> check)
    {
        var directory = Directory.CreateTempSubdirectory("endfield-live-session-");
        try
        {
            using var actual = LiveBattleSession.Create(new ResourceFiles(directory.FullName), new(2026, 10, 29), timeZone: TimeZoneInfo.Utc);
            actual.FeedLine(First);
            var report = Get(actual.SnapshotAsync())!;
            var battle = (EvidenceObject)report.Get("battle");
            check(battle.Get("total_damage") is EvidenceInteger damage && damage.Value == 100,
                "Runtime session connects production ingestion and compact allocation");
            ((Dictionary<string, EvidenceValue>)battle.Fields)["total_damage"] = new EvidenceInteger(-1);
            check(((EvidenceObject)actual.ReadSnapshot()!.Get("battle")).Get("total_damage") is EvidenceInteger saved && saved.Value == 100,
                "UI receives an owned publication without access to the persistent calculation cache");
            actual.FeedLine(Second);
            Get(actual.SnapshotAsync(refresh: false));
            check(actual.State is { Calculations: 1, Dirty: true }, "Read-only UI queries never calculate dirty source input");
            Get(actual.SnapshotAsync());
            check(actual.State is { Calculations: 2, Dirty: false, SourceRevision: 2 }, "Refresh publishes its completed source watermark");
        }
        finally { directory.Delete(recursive: true); }

        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        var inputs = new List<int>();
        using (var concurrent = new LiveBattleSession(() => (lines, _, _, _) =>
        {
            inputs.Add(lines.Count);
            if (inputs.Count == 1) { entered.Set(); Wait(release); }
            return Value(lines.Count);
        }))
        {
            concurrent.FeedLine(First);
            var old = concurrent.SnapshotAsync();
            Wait(entered);
            try
            {
                concurrent.FeedLine(Second);
                check(concurrent.ReadSnapshot() is null && concurrent.State.LineCount == 2,
                    "Ingestion and UI reads remain responsive while calculation owns CPU work");
                var queued = concurrent.SnapshotAsync();
                release.Set();
                check(Is(Get(old), 1) && Is(Get(queued), 2) && inputs.SequenceEqual([1, 2])
                    && concurrent.State is { SourceRevision: 2, Dirty: false },
                    "Queued refresh captures input after calculator acquisition and cannot publish an older watermark last");
            }
            finally { release.Set(); }
        }

        entered.Reset(); release.Reset();
        var factories = 0;
        using (var reset = new LiveBattleSession(() =>
        {
            var identity = ++factories;
            return (_, _, _, _) => { if (identity == 1) { entered.Set(); Wait(release); } return Value(identity); };
        }))
        {
            reset.FeedLine(First);
            var old = reset.SnapshotAsync();
            Wait(entered);
            try
            {
                reset.Reset();
                reset.FeedLine(Second);
                release.Set();
                check(Get(old) is null && reset.State is { Dirty: true, DiscardedResults: 1 },
                    "Reset rejects an old generation completion and preserves new input for refresh");
                check(Is(Get(reset.SnapshotAsync()), 2), "A replaced generation receives independent calculator state");
            }
            finally { release.Set(); }
        }

        var calls = 0;
        using (var failing = new LiveBattleSession(() => (_, _, _, _) =>
        {
            calls++;
            if (calls >= 2) throw new InvalidDataException("synthetic invalid evidence");
            return Value(1);
        }))
        {
            failing.FeedLines([Start, First]);
            Get(failing.SnapshotAsync());
            failing.FeedLine(Second);
            check(Get(failing.SnapshotAsync()) is null && failing.ReadSnapshot() is null && failing.State.LastError is not null,
                "Failure after independent replay drops the stale display and keeps its diagnostic");
            Get(failing.SnapshotAsync(4000));
            check(calls == 3 && !failing.State.Dirty, "Unchanged failed evidence is not replayed by every clock or UI poll");
            failing.FeedLine("[00:00:03.000] HEARTBEAT");
            Get(failing.SnapshotAsync());
            check(calls == 5, "A new semantic revision permits recovery after an earlier failed calculation");
        }

        entered.Reset(); release.Reset();
        using (var cancel = new LiveBattleSession(() => (_, _, _, token) =>
        {
            entered.Set();
            Wait(release);
            token.ThrowIfCancellationRequested();
            return Value(1);
        }))
        {
            cancel.FeedLine(First);
            using CancellationTokenSource request = new();
            var pending = cancel.SnapshotAsync(cancellationToken: request.Token);
            Wait(entered);
            request.Cancel(); release.Set();
            var canceled = false;
            try { Get(pending); } catch (OperationCanceledException) { canceled = true; }
            check(canceled && cancel.State.Dirty && cancel.ReadSnapshot() is null,
                "Caller cancellation leaves unpublished input dirty and does not turn cancellation into invalid evidence");
            check(Is(Get(cancel.SnapshotAsync()), 1), "A later uncanceled refresh can publish the retained input");
        }

        entered.Reset(); release.Reset();
        var closing = new LiveBattleSession(() => (_, _, _, _) => { entered.Set(); Wait(release); return Value(1); });
        closing.FeedLine(First);
        var finishing = closing.SnapshotAsync();
        Wait(entered);
        closing.Dispose();
        check(!finishing.IsCompleted && closing.ReadSnapshot() is null, "Disposal returns while CPU work is still running and removes its publication");
        release.Set();
        var stopped = false;
        try { Get(finishing); } catch (OperationCanceledException) { stopped = true; }
        check(stopped && closing.ReadSnapshot() is null, "A worker completing after close cannot restore a display snapshot");
    }
}
