using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using EndfieldLogs.Core.Realtime;

internal static class LiveBuffProjectionSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static BuffInstanceState State() => new(new PacketBuffCatalog(new Dictionary<string, EvidenceObject>(),
        new Dictionary<string, IReadOnlyList<EvidenceObject>>(), new Dictionary<string, string>()),
        new Dictionary<string, EvidenceObject>(), new Dictionary<string, string>(), key => key, key => key);
    private static void Start(BuffInstanceState state, int line, string uid = "7") => state.ObserveLifecycle(
        $" BUFF_START uid={uid} id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11", line, line * 100);

    public static void Run(Action<bool, string> check)
    {
        var state = State();
        LiveBuffProjectionCache cache = new();
        cache.Capture(state);
        Start(state, 1);
        state.ObserveBlackboard(" BB[ resistance=-0.2 ]");
        var first = cache.Capture(state);
        var again = cache.Capture(state);
        check(cache.ProjectedRecords == 1 && cache.ReusedRecords == 1 && ReferenceEquals(first[0], again[0]),
            "Unchanged BUFF captures reuse one protected projection");
        again[0] = Obj("{}");
        check(cache.Capture(state)[0].Get("uid") is EvidenceText { Value: "7" },
            "Captured reference arrays cannot replace the live cache's slots");
        try
        {
            ((IDictionary<string, EvidenceValue>)((EvidenceObject)first[0].Get("bb_values")).Fields)["resistance"] = new EvidenceReal(5);
            throw new Exception("Writable cached blackboard");
        }
        catch (NotSupportedException) { check(true, "Shared BUFF descendants reject mutations"); }
        var mutable = FrozenEvidence.OwnedMutableRoot(first[0]);
        ((Dictionary<string, EvidenceValue>)mutable.Fields)["dynamic_bb_events"] = new EvidenceArray([]);
        check(!first[0].Fields.ContainsKey("dynamic_bb_events"), "Report preparation owns a mutable root without changing cached evidence");
        LiveSourcePreparationCache preparation = new();
        var prepared = preparation.Prepare(first[0], null);
        check(ReferenceEquals(prepared, preparation.Prepare(first[0], null))
            && prepared.Get("dynamic_bb_events") is EvidenceArray { Items.Count: 0 }
            && !first[0].Fields.ContainsKey("dynamic_bb_events"),
            "Summary annotations reuse unchanged protected records without modifying ingestion projections");
        var refreshed = preparation.Prepare(first[0], 1234);
        check(!ReferenceEquals(refreshed, prepared)
            && refreshed.Get("packet_modifier_last_seen_ts_ms") is EvidenceInteger { Value: var stamp } && stamp == 1234
            && prepared.Get("packet_modifier_last_seen_ts_ms") is EvidenceNull,
            "A later modifier observation invalidates only the annotated record and leaves prior reports intact");
        var mutableSource = Obj("""{"uid":"7","bb_values":{"rate":1}}""");
        var saved = preparation.Prepare(mutableSource, null);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)mutableSource.Get("bb_values")).Fields)["rate"] = new EvidenceInteger(2);
        check(((EvidenceObject)saved.Get("bb_values")).Get("rate") is EvidenceInteger { Value: var oldRate } && oldRate == 1
            && ((EvidenceObject)preparation.Prepare(mutableSource, null).Get("bb_values")).Get("rate") is EvidenceInteger { Value: var newRate } && newRate == 2,
            "Mutable record inputs cannot enter the identity reuse path or alter retained summary evidence");
        state.ObserveBlackboard(" BB[ resistance=-0.3 ]");
        var changed = cache.Capture(state);
        check(((EvidenceObject)first[0].Get("bb_values")).Get("resistance") is EvidenceReal { Value: -0.2 }
            && ((EvidenceObject)changed[0].Get("bb_values")).Get("resistance") is EvidenceReal { Value: -0.3 },
            "Changed blackboards enter the next capture and leave earlier snapshots detached");
        Start(state, 2);
        var updated = cache.Capture(state);
        new BuffPacketObservations(state).Observe("buff_enable",
            Obj("""{"schemaVersion":1,"buffUid":"7","ownerId":"22","enabled":false,"operationSeq":3}"""), 3, 300);
        var enabled = cache.Capture(state);
        check(updated.Length == 2 && enabled.All(row => row.Get("enable_observations") is EvidenceArray { Items.Count: 1 })
            && updated.All(row => row.Get("enable_observations") is EvidenceArray { Items.Count: 0 }),
            "Shared enable lists invalidate both snapshots while earlier arrays remain unchanged");
        state.ObserveLifecycle(" BUFF_END uid=7", 4, 400);
        var ended = cache.Capture(state);
        check(ended[^1].Get("end_ts_ms") is EvidenceInteger { Value: var end } && end == 400,
            "An explicit end updates the live projection's lifetime boundary");

        var rollback = State();
        LiveBuffProjectionCache rollbackCache = new();
        rollbackCache.Capture(rollback);
        Start(rollback, 1);
        const string creation = """{"schemaVersion":1,"buffUid":"7","buffTemplate":"buff_test","buffId":"buff_test","sourceEvent":"BattleOpAddBuff","sessionId":"s","operationSeq":1,"sourceActorId":"11","targetActorId":"22","operationOwnerId":"11","generationScope":"operation_owner"}""";
        var observations = new BuffPacketObservations(rollback);
        observations.Observe("buff_creation", Obj(creation), 2, 200);
        rollbackCache.Capture(rollback);
        Start(rollback, 3);
        var beforeRollback = rollbackCache.Capture(rollback);
        observations.Observe("buff_creation", Obj(creation), 4, 400);
        var rolled = rollbackCache.Capture(rollback);
        check(beforeRollback.Length == 2 && rolled.Length == 1 && rollbackCache.StructureResets == 1
            && EvidenceJson.PythonEquals(rolled[0], BuffReportEvidence.Project(rollback.Records[0]))
            && rolled[0].Get("repeated_creation_observations") is EvidenceArray { Items.Count: 1 }
            && rolled[0].Get("snapshot_end_ts_ms") is EvidenceNull,
            "Duplicate creation retracts the incoming snapshot and rebuilds its original order and boundary");

        (long Projected, long Reused) AppendAfter(int count)
        {
            var completed = State();
            for (var index = 1; index <= count; index++)
            {
                Start(completed, index * 2, index.ToString());
                completed.ObserveLifecycle($" BUFF_END uid={index}", index * 2 + 1, index * 200 + 100);
            }
            LiveBuffProjectionCache history = new();
            history.Capture(completed);
            var priorProjected = history.ProjectedRecords;
            Start(completed, count * 2 + 2, "99999");
            history.Capture(completed);
            return (history.ProjectedRecords - priorProjected, history.ReusedRecords);
        }
        check(AppendAfter(10) == (1, 10) && AppendAfter(1000) == (1, 1000),
            "The same added instance after short or long completed history projects exactly one BUFF");

        var root = Path.Combine(Path.GetTempPath(), "endfield-live-buff-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var engine = LiveBattleEngine.Load(new ResourceFiles(root), new(2026, 11, 1));
            const string line = "[00:00:01.000] BUFF_START uid=7 id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11\n";
            engine.Snapshot([line], summary: true);
            engine.Snapshot([line, "[00:00:02.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target skill=skill_test hit=100 eHP=900\n"], summary: true);
            check(engine.Diagnostics.ProjectedBuffs == 1 && engine.Diagnostics.ReusedBuffProjections == 1,
                "Live report capture shares an unchanged BUFF across new hit batches");
            engine.Reset();
            engine.Snapshot([line], summary: true);
            check(engine.Diagnostics.ProjectedBuffs == 1 && engine.Diagnostics.ReusedBuffProjections == 0,
                "A new live generation starts with its own projection tracker and cache");
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
