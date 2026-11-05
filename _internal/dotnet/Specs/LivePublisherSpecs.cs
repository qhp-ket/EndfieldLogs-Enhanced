using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Realtime;

internal static class LivePublisherSpecs
{
    private const string Hit = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
    private static EvidenceObject Value() => (EvidenceObject)EvidenceJson.Parse("{\"value\":100}");
    private static T Get<T>(Task<T> task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();

    public static void Run(Action<bool, string> check)
    {
        var calls = 0;
        using (var publisher = new LiveSnapshotPublisher(new(() => (_, _, _, _) => { calls++; return Value(); }), TimeSpan.Zero))
        {
            var initial = Get(publisher.PublishPendingAsync())!;
            check(initial is { Type: "analysis_summary", Sequence: 0, Snapshot: null }
                && Get(publisher.PublishPendingAsync()) is null, "Startup emits one clear frame and then waits without calculating");
            publisher.FeedLine(Hit);
            publisher.FeedLine(Hit.Replace("#1", "#2", StringComparison.Ordinal));
            check(calls == 0, "Capture delivery only queues evidence; it never runs report allocation");
            var first = Get(publisher.PublishPendingAsync())!;
            check(calls == 1 && first is { Sequence: 1, SourceRevision: 2 } && publisher.IsCurrent(first),
                "A burst is coalesced into one completed report with its source watermark");
            ((Dictionary<string, EvidenceValue>)first.Snapshot!.Fields)["value"] = new EvidenceInteger(-1);
            check(publisher.Current.Snapshot!.Get("value") is EvidenceInteger { Value: var damage } && damage == 100,
                "An observer cannot mutate the shared publication");
            publisher.RequestCurrent();
            check(Get(publisher.PublishPendingAsync()) is null && calls == 1, "An unchanged request stays silent without calculating again");
            publisher.FeedLine("[00:00:01.500] UNKNOWN_EVIDENCE x=1");
            var newer = Get(publisher.PublishPendingAsync())!;
            check(newer is { Sequence: 2, SourceRevision: 3 } && !publisher.IsCurrent(first),
                "A completed semantic revision is published even when displayed numbers remain identical");
            publisher.FeedLine("GAME_TIMER_RESET");
            publisher.FeedLine(Hit);
            var clear = Get(publisher.PublishPendingAsync())!;
            var next = Get(publisher.PublishPendingAsync())!;
            check(clear is { Snapshot: null, SourceRevision: 0 } && next.Sequence == clear.Sequence + 1
                && next is { SourceGeneration: 1, SourceRevision: 1 } && next.StreamId == first.StreamId,
                "Reset publishes its clear before the next battle and rebases the source revision");
            publisher.Reset(newStream: true);
            var stream = Get(publisher.PublishPendingAsync())!;
            check(stream.Sequence == 0 && stream.StreamId != first.StreamId && !publisher.IsCurrent(next),
                "A restarted stream has an independent identity and rejects old observer messages");
        }

        using var entered = new ManualResetEventSlim();
        using var release = new ManualResetEventSlim();
        using (var publisher = new LiveSnapshotPublisher(new(() => (_, _, _, _) =>
        {
            entered.Set();
            if (!release.Wait(TimeSpan.FromSeconds(15))) throw new TimeoutException("Publisher barrier");
            return Value();
        }), TimeSpan.Zero))
        {
            Get(publisher.PublishPendingAsync());
            publisher.FeedLine(Hit);
            var pending = publisher.PublishPendingAsync();
            if (!entered.Wait(TimeSpan.FromSeconds(15))) throw new TimeoutException("Publisher did not start");
            try
            {
                publisher.Reset();
                publisher.FeedLine(Hit);
                release.Set();
                check(Get(pending) is null && publisher.Current.Snapshot is null,
                    "A reset during calculation rejects the old publication at both session and transport boundaries");
                check(Get(publisher.PublishPendingAsync())!.Snapshot is null && Get(publisher.PublishPendingAsync())!.Snapshot is not null,
                    "The new clear remains ordered ahead of input queued while the old calculator was running");
            }
            finally { release.Set(); }
        }

        var wide = BigInteger.One << 90;
        EvidenceObject original = new(new Dictionary<string, EvidenceValue>
        {
            ["wide"] = new EvidenceInteger(wide), ["edge"] = new EvidenceInteger(9_007_199_254_740_991L),
            ["values"] = new EvidenceArray([new EvidenceReal(double.NaN), new EvidenceReal(double.PositiveInfinity), new EvidenceInteger(-wide)]),
        });
        var safe = (EvidenceObject)LiveSnapshotPublisher.TransportCopy(original);
        check(safe.Get("wide") is EvidenceText text && text.Value == wide.ToString(System.Globalization.CultureInfo.InvariantCulture)
            && safe.Get("edge") is EvidenceInteger && ((EvidenceArray)safe.Get("values")).Items.Take(2).All(row => row is EvidenceNull)
            && original.Get("wide") is EvidenceInteger, "WS projection keeps safe integers and converts wide numbers/non-finite floats on an owned boundary");
        var encoded = new LiveSnapshotFrame("analysis_summary", "synthetic", 1, 2, 3, safe).ToEvidence();
        check(EvidenceJson.PythonEquals(encoded, EvidenceJson.Parse(PythonSortedJson.Serialize(encoded, compact: true))),
            "The public frame retains the schema and serializes as standards-compatible JSON");

        using (var publisher = new LiveSnapshotPublisher(new(() => (_, _, _, _) => Value()), TimeSpan.Zero))
        using (CancellationTokenSource stop = new())
        {
            TaskCompletionSource<bool> clear = new(TaskCreationOptions.RunContinuationsAsynchronously);
            TaskCompletionSource<bool> published = new(TaskCreationOptions.RunContinuationsAsynchronously);
            var running = publisher.RunAsync((frame, _) =>
            {
                if (frame.Snapshot is null) clear.TrySetResult(true); else published.TrySetResult(true);
                return ValueTask.CompletedTask;
            }, stop.Token);
            Get(clear.Task);
            publisher.FeedLine(Hit);
            Get(published.Task);
            check(!running.IsCompleted && publisher.Current.SourceRevision == 1,
                "The completion-driven scheduler wakes on evidence and sleeps again after its publication");
            stop.Cancel();
            var canceled = false;
            try { running.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult(); } catch (OperationCanceledException) { canceled = true; }
            check(canceled, "A sleeping scheduler exits on cancellation without polling or an animation timer");
        }
    }
}
