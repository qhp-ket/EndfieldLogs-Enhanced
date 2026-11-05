using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Realtime;

internal static class LiveAnalysisStreamsSpecs
{
    private const string Hit = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    private static LiveSnapshotFrame Read(LiveAnalysisSubscription subscription)
    {
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(15));
        return subscription.ReadAsync(timeout.Token).AsTask().GetAwaiter().GetResult() ?? throw new IOException("Stream completed before the expected frame");
    }
    private static void Wait(Task task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();

    public static void Run(Action<bool, string> check)
    {
        var summaries = 0; var reports = 0;
        using var streams = new LiveAnalysisStreams(compact => new(() => (lines, _, _, _) =>
        {
            if (compact) Interlocked.Increment(ref summaries); else Interlocked.Increment(ref reports);
            return new(new Dictionary<string, EvidenceValue> { ["lines"] = new EvidenceInteger(lines.Count) });
        }, new(Summary: compact)), TimeSpan.Zero, TimeSpan.Zero);
        using var summary = streams.Subscribe(); using CancellationTokenSource stop = new();
        var run = streams.RunAsync(stop.Token);
        try
        {
            check(Read(summary) is { Snapshot: null, Type: "analysis_summary" }, "A new observer receives the initial clear without waiting for a packet");
            streams.FeedLine(Hit);
            var first = Read(summary);
            check(first.Snapshot is not null && Volatile.Read(ref summaries) == 1 && Volatile.Read(ref reports) == 0,
                "A compact-only observer runs no full-report calculation");
            using var report = streams.Subscribe(compact: false);
            check(Read(report) is { Snapshot: null, Type: "analysis_snapshot" }, "A full-report observer retains its independent message type and initial clear");
            check(Read(report).Snapshot is not null && Volatile.Read(ref reports) == 1,
                "A late full-report subscriber replays retained canonical context without needing a new capture event");
            report.Dispose();
            streams.FeedLine(Hit.Replace("#1", "#2", StringComparison.Ordinal));
            check(Read(summary).SourceRevision == 2 && Volatile.Read(ref reports) == 1,
                "Removing the last full-report observer stops report work while compact publication continues");
            streams.Reset(); streams.FeedLine(Hit);
            var clear = Read(summary); var next = Read(summary);
            check(clear is { Snapshot: null, SourceGeneration: 1 } && next.SourceGeneration == 1 && next.Snapshot is not null,
                "New-battle publication preserves the ordered reset before subsequent data");
        }
        finally
        {
            stop.Cancel();
            try { Wait(run); } catch (OperationCanceledException) { }
        }

        // Deliberately leave an observer unread across many updates; storage is bounded by semantic coalescing.
        using var coalesced = new LiveAnalysisStreams(compact => new(() => (_, _, _, _) =>
            new(new Dictionary<string, EvidenceValue> { ["value"] = new EvidenceInteger(100) }), new(Summary: compact)), TimeSpan.Zero, TimeSpan.Zero);
        using var slow = coalesced.Subscribe(); using var other = coalesced.Subscribe();
        Wait(coalesced.FlushPendingAsync());
        for (var index = 1; index <= 100; index++)
        {
            coalesced.FeedLine(Hit.Replace("#1", "#" + index, StringComparison.Ordinal));
            Wait(coalesced.FlushPendingAsync());
        }
        check(slow.TryRead(out var initial) && initial?.Snapshot is null && slow.TryRead(out var latest)
            && latest?.SourceRevision == 100 && !slow.TryRead(out _),
            "An arbitrarily slow observer holds only one clear and the latest result");
        other.TryRead(out _); other.TryRead(out var owned);
        ((Dictionary<string, EvidenceValue>)owned!.Snapshot!.Fields)["value"] = new EvidenceInteger(-1);
        check(coalesced.Current().Snapshot!.Get("value") is EvidenceInteger { Value: var value } && value == 100,
            "Mailbox reads detach mutable evidence from the stream and other observers");
        coalesced.Reset(); Wait(coalesced.FlushPendingAsync()); coalesced.Dispose();
        check(Read(slow).Snapshot is null && slow.ReadAsync().AsTask().GetAwaiter().GetResult() is null,
            "Orderly completion retains the final clear until the consumer drains it, then ends the stream");
    }
}
