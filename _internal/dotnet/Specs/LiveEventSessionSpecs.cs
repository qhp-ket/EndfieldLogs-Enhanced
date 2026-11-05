using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Realtime;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Realtime;
using EndfieldLogs.Runtime.Tracing;

internal static class LiveEventSessionSpecs
{
    private static readonly long Start = new DateTimeOffset(2026, 10, 29, 23, 59, 59, TimeSpan.Zero).ToUnixTimeMilliseconds();
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Value(int count) => new(new Dictionary<string, EvidenceValue> { ["count"] = new EvidenceInteger(count) });
    private static int Count(EvidenceObject? value) => value?.Get("count") is EvidenceInteger count ? (int)count.Value : -1;
    private static T Get<T>(Task<T> task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
    private static void Complete(Task task) => task.WaitAsync(TimeSpan.FromSeconds(15)).GetAwaiter().GetResult();
    private static void Wait(ManualResetEventSlim barrier)
    { if (!barrier.Wait(TimeSpan.FromSeconds(15))) throw new TimeoutException("Structured session barrier"); }
    private static LiveBattleSession Session(Func<LiveEventCalculation> factory, LiveSessionOptions? options = null) =>
        new(() => (_, _, _, _) => throw new InvalidOperationException("Structured input used the legacy calculator"),
            options, eventCalculatorFactory: factory);
    private static TraceEvent Event(int seq, long timestamp, string type, string data)
    {
        var captured = TraceValueProjection.Capture(Obj(data));
        var fields = ((EvidenceObject)captured.Value).Fields.ToDictionary(); fields["legacy_layout"] = captured.Layout;
        return new(seq, timestamp, type, new(fields), Obj("{}"));
    }
    private static TraceEvent Damage(int seq, long timestamp) => Event(seq, timestamp, "damage", $$$$"""
        {"hit_seq":{{{{seq}}}},"actors":{"attacker":"chr_0001_test","target":"eny_0001_test"},
         "action":{"skill":"chr_0001_test_normal_skill"},"amounts":{"value":-100,"current_hp":900},
         "blackboards":{"dynamic":[],"calculation":[]},"evidence":{"presence":{}}}
        """);
    private static TraceEvent Timer(int seq, long timestamp, string phase, bool official = true) => Event(seq, timestamp,
        official ? "official_timer" : "battle_timer", $$"""{"phase":"{{phase}}","source":"synthetic","game_id":"challenge"}""");

    public static void Run(Action<bool, string> check)
    {
        SuffixesAndOwnership(check);
        ConcurrentAndReset(check);
        FailureAndCancellation(check);
        PublicationAndDemand(check);
        SharedEventOwnership(check);
        Production(check);
    }

    private static void SuffixesAndOwnership(Action<bool, string> check)
    {
        List<(LiveEventBatch Batch, LiveObserverClock? Observer)> requests = [];
        using var session = Session(() => (batch, observer, _, _) =>
        { requests.Add((batch, observer)); return Value(batch.AfterEvidenceIndex + batch.Events.Count); });
        session.FeedEvents([Timer(1, Start, "start"), Damage(2, Start + 100)]);
        check(Count(Get(session.SnapshotAsync())) == 2 && requests[0].Batch is { AfterEvidenceIndex: 0, Events.Count: 2 }
            && session.State is { StructuredInput: true, OfficialTimerActive: true, Dirty: false },
            "Structured sessions enter the event calculator directly with an owned initial batch");
        session.FeedEvent(Damage(3, Start + 1100)); Get(session.SnapshotAsync());
        check(requests[^1].Batch is { AfterEvidenceIndex: 2, Events.Count: 1 }
            && requests[^1].Batch.Events[0].Sequence == 3,
            "A normal append sends only the new event, without capturing the retained prefix");
        Get(session.SnapshotAsync(Start + 2500));
        check(requests[^1].Batch is { AfterEvidenceIndex: 3, Events.Count: 0 }
            && requests[^1].Observer is { TimestampMs: var stamp, ElapsedMs: var elapsed } && stamp == Start + 2500 && elapsed == 2500,
            "An observer refresh sends a numeric Unix clock and an empty event suffix");
        Get(session.SnapshotAsync()); var calculations = requests.Count; Get(session.SnapshotAsync());
        check(requests.Count == calculations, "Unchanged watermark reads return to the cached result without another event calculation");
        Complete(session.ReleaseCalculatorAsync()); session.FeedEvent(Damage(4, Start + 3100)); Get(session.SnapshotAsync());
        check(requests[^1].Batch is { AfterEvidenceIndex: 0, Events.Count: 4 },
            "Releasing a dormant calculator retains events and replays the prefix when new work is demanded");

        var data = Obj("""{"nested":{"value":7},"items":[{"value":8}]}""");
        var original = new TraceEvent(1, Start, "buff_start", data, Obj("""{"operation_seq":9}"""));
        TraceEvent? captured = null;
        using var isolated = Session(() => (batch, _, _, _) => { captured = batch.Events.Single(); return Value(1); });
        isolated.FeedEvent(original);
        ((IDictionary<string, EvidenceValue>)((EvidenceObject)data.Get("nested")).Fields)["value"] = new EvidenceInteger(-1);
        ((IDictionary<string, EvidenceValue>)original.Source.Fields)["operation_seq"] = new EvidenceInteger(-1);
        Get(isolated.SnapshotAsync());
        var frozen = isolated.HistoryEventContext().Single();
        check(captured is not null && ReferenceEquals(captured, frozen)
            && ((EvidenceObject)frozen.Data.Get("nested")).Get("value") is EvidenceInteger { Value: var saved } && saved == 7
            && frozen.Source.Get("operation_seq") is EvidenceInteger { Value: var operation } && operation == 9
            && ((IDictionary<string, EvidenceValue>)frozen.Data.Fields).IsReadOnly
            && ((IList<EvidenceValue>)((EvidenceArray)frozen.Data.Get("items")).Items).IsReadOnly,
            "New evidence is detached once, then immutable event objects are shared with calculator and history readers");
    }

    private static void ConcurrentAndReset(Action<bool, string> check)
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        List<LiveEventBatch> requests = [];
        using (var session = Session(() => (batch, _, _, _) =>
        {
            requests.Add(batch); if (requests.Count == 1) { entered.Set(); Wait(release); }
            return Value(batch.AfterEvidenceIndex + batch.Events.Count);
        }))
        {
            session.FeedEvent(Damage(1, Start)); var first = session.SnapshotAsync(); Wait(entered);
            try
            {
                session.FeedEvent(Damage(2, Start + 100)); var next = session.SnapshotAsync(); release.Set();
                check(Count(Get(first)) == 1 && Count(Get(next)) == 2
                    && requests[1] is { AfterEvidenceIndex: 1, Events.Count: 1 }
                    && session.State is { SourceRevision: 2, Dirty: false },
                    "A queued event refresh captures its suffix after acquiring the calculator and publishes the newest watermark last");
            }
            finally { release.Set(); }
        }

        entered.Reset(); release.Reset(); var factories = 0;
        using var reset = Session(() =>
        {
            var identity = ++factories;
            return (_, _, _, _) => { if (identity == 1) { entered.Set(); Wait(release); } return Value(identity); };
        });
        reset.FeedEvent(Damage(1, Start)); var obsolete = reset.SnapshotAsync(); Wait(entered);
        try
        {
            reset.Reset(); reset.FeedEvent(Damage(2, Start + 100)); release.Set();
            check(Get(obsolete) is null && reset.State is { Dirty: true, DiscardedResults: 1 }
                && Count(Get(reset.SnapshotAsync())) == 2 && factories == 2,
                "Reset rejects an old event completion and starts the new generation with independent state");
        }
        finally { release.Set(); }
    }

    private static void FailureAndCancellation(Action<bool, string> check)
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        var factories = 0; List<(int Factory, LiveEventBatch Batch)> requests = [];
        using (var session = Session(() =>
        {
            var identity = ++factories;
            return (batch, _, _, _) =>
            {
                requests.Add((identity, batch));
                if (identity == 1 && batch.AfterEvidenceIndex > 0) { entered.Set(); Wait(release); throw new InvalidDataException("synthetic failure"); }
                return Value(batch.AfterEvidenceIndex + batch.Events.Count);
            };
        }))
        {
            session.FeedEvent(Damage(1, Start)); Get(session.SnapshotAsync());
            session.FeedEvent(Damage(2, Start + 100)); var failure = session.SnapshotAsync(); Wait(entered);
            try
            {
                session.FeedEvent(Damage(3, Start + 200)); release.Set();
                check(Count(Get(failure)) == 2 && session.State is { Dirty: true, SourceRevision: 2 }
                    && requests[^1] is { Factory: 2, Batch.AfterEvidenceIndex: 0, Batch.Events.Count: 2 },
                    "Independent fallback replays exactly the failed request prefix and excludes evidence arriving during that calculation");
                check(Count(Get(session.SnapshotAsync())) == 3 && factories == 2
                    && requests[^1] is { Factory: 2, Batch.AfterEvidenceIndex: 2, Batch.Events.Count: 1 },
                    "A successful fallback becomes the retained calculator for subsequent suffixes");
            }
            finally { release.Set(); }
        }

        entered.Reset(); release.Reset(); factories = 0; requests.Clear();
        using var cancel = Session(() =>
        {
            var identity = ++factories;
            return (batch, _, _, token) =>
            {
                requests.Add((identity, batch));
                if (identity == 1 && batch.AfterEvidenceIndex > 0) { entered.Set(); Wait(release); token.ThrowIfCancellationRequested(); }
                return Value(batch.AfterEvidenceIndex + batch.Events.Count);
            };
        });
        cancel.FeedEvent(Damage(1, Start)); Get(cancel.SnapshotAsync()); cancel.FeedEvent(Damage(2, Start + 100));
        using CancellationTokenSource request = new(); var pending = cancel.SnapshotAsync(cancellationToken: request.Token); Wait(entered);
        try
        {
            request.Cancel(); release.Set(); var canceled = false;
            try { Get(pending); } catch (OperationCanceledException) { canceled = true; }
            check(canceled && cancel.State.Dirty && Count(cancel.ReadSnapshot()) == 1
                && Count(Get(cancel.SnapshotAsync())) == 2 && factories == 2
                && requests[^1].Batch is { AfterEvidenceIndex: 0, Events.Count: 2 },
                "Cancellation preserves the publication and retained evidence but discards a potentially partial calculator before replay");
        }
        finally { release.Set(); }
    }

    private static void PublicationAndDemand(Action<bool, string> check)
    {
        using var publisher = new LiveSnapshotPublisher(Session(() => (batch, _, _, _) =>
            Value(batch.AfterEvidenceIndex + batch.Events.Count)), TimeSpan.Zero);
        check(Get(publisher.PublishPendingAsync()) is { Snapshot: null, SourceGeneration: 0 },
            "An event publisher begins with the same ordered clear envelope as a legacy publisher");
        publisher.FeedEvent(Damage(1, Start)); var first = Get(publisher.PublishPendingAsync())!;
        publisher.FeedEvent(Timer(2, Start + 100, "reset", official: false)); publisher.FeedEvent(Damage(3, Start + 200));
        var clear = Get(publisher.PublishPendingAsync())!; var next = Get(publisher.PublishPendingAsync())!;
        check(first.Snapshot is not null && clear is { Snapshot: null, SourceGeneration: 1, SourceRevision: 0 }
            && next.SourceGeneration == 1 && next.SourceRevision == 1 && Count(next.Snapshot) == 1
            && first.Sequence < clear.Sequence && clear.Sequence < next.Sequence,
            "A structured timer reset publishes its clear before any data in the replacement generation");
        publisher.FeedEvents([Damage(4, Start + 300), Timer(5, Start + 400, "reset", official: false),
            Damage(6, Start + 500), Damage(7, Start + 600)]);
        var batchClear = Get(publisher.PublishPendingAsync())!;
        var batchResult = Get(publisher.PublishPendingAsync())!;
        check(batchClear is { Snapshot: null, SourceGeneration: 2 } && batchResult.SourceGeneration == 2
            && batchResult.SourceRevision == 2 && Count(batchResult.Snapshot) == 2 && batchClear.Sequence < batchResult.Sequence,
            "A complete batch retains ordered reset publication and only the subsequent business evidence");

        var compactCalls = 0; var fullCalls = 0;
        using var streams = new LiveAnalysisStreams(compact => Session(() => (batch, _, _, _) =>
        {
            if (compact) compactCalls++; else fullCalls++;
            return Value(batch.AfterEvidenceIndex + batch.Events.Count);
        }, new(Summary: compact)), TimeSpan.Zero, TimeSpan.Zero);
        using var compact = streams.Subscribe(); compact.TryRead(out _); Complete(streams.FlushPendingAsync());
        streams.FeedEvent(Damage(1, Start)); Complete(streams.FlushPendingAsync()); compact.TryRead(out var compactResult);
        check(Count(compactResult?.Snapshot) == 1 && compactCalls == 1 && fullCalls == 0,
            "A compact-only event subscriber performs no full-report work");
        using var full = streams.Subscribe(compact: false); full.TryRead(out _);
        Complete(streams.FlushPendingAsync()); Complete(streams.FlushPendingAsync()); full.TryRead(out var fullResult);
        check(Count(fullResult?.Snapshot) == 1 && fullCalls == 1 && compactCalls == 1,
            "A late full-report observer receives retained event context without a new packet or legacy conversion");
        full.Dispose(); streams.FeedEvent(Damage(2, Start + 100)); Complete(streams.FlushPendingAsync()); compact.TryRead(out compactResult);
        check(Count(compactResult?.Snapshot) == 2 && compactCalls == 2 && fullCalls == 1,
            "Removing full-report demand stops that calculation while the compact event stream advances");
    }

    private static void SharedEventOwnership(Action<bool, string> check)
    {
        var observed = new Dictionary<bool, IReadOnlyList<TraceEvent>>();
        using var streams = new LiveAnalysisStreams(compact => Session(() => (batch, _, _, _) =>
        {
            observed[compact] = batch.Events;
            return Value(batch.AfterEvidenceIndex + batch.Events.Count);
        }, new(Summary: compact)), TimeSpan.Zero, TimeSpan.Zero);
        using var compact = streams.Subscribe(); compact.TryRead(out _);
        var original = new TraceEvent(1, Start, "buff_start", Obj("""{"nested":{"value":7}}"""), Obj("""{"seq":1}"""));
        streams.FeedEvent(original);
        ((IDictionary<string, EvidenceValue>)((EvidenceObject)original.Data.Get("nested")).Fields)["value"] = new EvidenceInteger(-1);
        Complete(streams.FlushPendingAsync()); Complete(streams.FlushPendingAsync());
        using var full = streams.Subscribe(compact: false); full.TryRead(out _);
        Complete(streams.FlushPendingAsync()); Complete(streams.FlushPendingAsync());
        check(ReferenceEquals(observed[true][0], observed[false][0])
            && ((EvidenceObject)observed[false][0].Data.Get("nested")).Get("value") is EvidenceInteger { Value: var value } && value == 7,
            "A late full subscriber shares the compact stream's immutable event while caller mutations remain isolated");

        var backing = new Dictionary<string, EvidenceValue> { ["value"] = new EvidenceInteger(8) };
        var pairs = new List<KeyValuePair<string, EvidenceValue>> { new("duplicate", new EvidenceInteger(1)), new("duplicate", new EvidenceInteger(2)) };
        var external = new EvidenceObject(new System.Collections.ObjectModel.ReadOnlyDictionary<string, EvidenceValue>(backing)) { SourcePairs = pairs };
        var batch = new List<TraceEvent> { new(2, Start + 100, "buff_start", external, Obj("{}")), Damage(3, Start + 200) };
        streams.FeedEvents(batch); backing["value"] = new EvidenceInteger(-1); pairs.Clear(); batch.Clear();
        Complete(streams.FlushPendingAsync());
        check(observed[true].Count == 2 && observed[false].Count == 2
            && observed[true].Zip(observed[false]).All(pair => ReferenceEquals(pair.First, pair.Second))
            && observed[false][0].Sequence == 2 && observed[false][1].Sequence == 3
            && observed[false][0].Data.Get("value") is EvidenceInteger { Value: var saved } && saved == 8
            && observed[false][0].Data.SourcePairs is { Count: 2 },
            "Grouped input detaches arbitrary read-only wrappers, duplicate source pairs and the caller's list once before sharing ordered events");

        var trusted = observed[true][0];
        var attached = new List<KeyValuePair<string, EvidenceValue>> { new("later", new EvidenceInteger(9)) };
        var recaptured = LiveBattleSession.CaptureEvent(trusted with { Data = trusted.Data with { SourcePairs = attached } });
        attached.Clear();
        check(recaptured.Data.SourcePairs is { Count: 1 },
            "Reusing protected fields does not make newly attached mutable source-pair evidence trusted");

        var parsed = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(original with { Sequence = 4 }), false);
        streams.FeedEvent(parsed); Complete(streams.FlushPendingAsync()); Complete(streams.FlushPendingAsync());
        check(ReferenceEquals(observed[true].Single(), parsed) && ReferenceEquals(observed[false].Single(), parsed),
            "Parsed immutable events pass unchanged through both runtime streams and their independent session boundaries");
        var nested = (EvidenceObject)parsed.Data.Get("nested");
        var writable = (EvidenceObject)EvidenceJson.Clone(parsed.Data);
        ((IDictionary<string, EvidenceValue>)((EvidenceObject)writable.Get("nested")).Fields)["value"] = new EvidenceInteger(99);
        check(!ReferenceEquals(writable, parsed.Data) && nested.Get("value") is EvidenceInteger { Value: var unchanged } && unchanged == -1,
            "Public writable copies cannot alter a parsed event shared with runtime consumers");
    }

    private static void Production(Action<bool, string> check)
    {
        var directory = Directory.CreateTempSubdirectory("endfield-event-session-");
        try
        {
            foreach (var compact in new[] { true, false })
            {
                ResourceFiles resources = new(directory.FullName);
                using var direct = LiveBattleSession.Create(resources, new(2026, 10, 29), new(Summary: compact), TimeZoneInfo.Utc);
                using var legacy = LiveBattleSession.Create(resources, new(2026, 10, 29), new(Summary: compact), TimeZoneInfo.Utc);
                var events = new[] { Timer(1, Start, "start"), Damage(2, Start + 100), Damage(3, Start + 1100) };
                foreach (var item in events)
                {
                    direct.FeedEvent(item);
                    legacy.FeedLines(item.Type == "damage" ? DamageLegacyExporter.Lines(item, 0) : TimerLegacyExporter.Lines(item, 0));
                }
                check(EvidenceJson.PythonEquals(Get(direct.SnapshotAsync())!, Get(legacy.SnapshotAsync())!)
                    && EvidenceJson.PythonEquals(Get(direct.SnapshotAsync(Start + 2100))!, Get(legacy.SnapshotAsync(1100))!),
                    "Production event sessions preserve legacy report/summary evidence and numeric observer timing across midnight");
                var end = Timer(4, Start + 3100, "end"); direct.FeedEvent(end); legacy.FeedLines(TimerLegacyExporter.Lines(end, 0));
                check(EvidenceJson.PythonEquals(Get(direct.SnapshotAsync())!, Get(legacy.SnapshotAsync())!)
                    && direct.State is { ClosedByOfficialTimerEnd: true, OfficialTimerActive: false },
                    "Official completion closes the structured battle using the same timing and evidence rules");
                var calculations = direct.State.Calculations;
                direct.FeedEvent(Event(5, Start + 4100, "clock_tick", """{"source":"GAME_CLOCK_TICK"}""")); Get(direct.SnapshotAsync());
                check(direct.State.Calculations == calculations,
                    "A heartbeat following official completion does not recalculate the closed structured battle");
            }
        }
        finally { directory.Delete(recursive: true); }
    }
}
