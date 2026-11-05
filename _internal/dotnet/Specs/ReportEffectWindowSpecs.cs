using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;
using System.Numerics;

internal static class ReportEffectWindowSpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject value,params (string Key,EvidenceValue Value)[] changes)
    {
        var fields=new Dictionary<string,EvidenceValue>(value.Fields);
        foreach(var (key,item) in changes) fields[key]=item;
        return new(fields);
    }

    public static void Run(Action<bool,string> check)
    {
        var root=Obj("""
            {"lifeType":"Infinity","stackingSettings":{"stackingType":"Unlimited"},"damageModifier":[
              {"enableSide":"Attacker","condition":{"onlyExecuteWhenSourceIsMainChar":false,"onlyExecuteWhenSourceIsGuard":false,"actionData":[]},
               "damageProcessors":[{"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Attacker","zoneName":"NormalCalcZone",
                 "addition":{"useBlackboardKey":true,"blackboardKey":"rate"}}]}]}
            """);
        var roots=new Dictionary<string,EvidenceObject> { ["buff"]=root,["buff_equipsuit_a"]=root,["buff_dynamic"]=Obj("""{"lifeType":"Infinity"}""") };
        var registry=Obj("""
            {"verified_effects":{"buff":{"effects":[{"zone":"dmg_inc","element":"all","bb_key":"rate"}]},
              "buff_dynamic":{"dynamic":true,"dynamic_effects":[{"zone":"amp","element":"all","base_bb_key":"base"}]}}}
            """);
        var record=Obj("""
            {"uid":"7","ts_ms":1000,"line_no":10,"event_key":"buff","raw_event_key":"buff","source_character_key":"source",
             "source_character_name":"提供者","target_character_key":"target","target_character_name":"接收者",
             "target_enemy_key":null,"target_enemy_name":null,"source_actor_id":"11","target_actor_id":"22","raw_source":"source",
             "lifetime_mode":"Infinity","bb_values":{"rate":0.2},"bb_keys":["rate"],"attr_mods":[],"enable_observations":[]}
            """);
        EffectWindowBuilder Builder(IReadOnlyDictionary<string,EvidenceObject>? actualRoots=null,EvidenceObject? actualRegistry=null)
        {
            var typed=actualRoots ?? roots;
            PacketBuffCatalog packets=new(new Dictionary<string,EvidenceObject>(),new Dictionary<string,IReadOnlyList<EvidenceObject>>(),new Dictionary<string,string>());
            EffectApproval approval=new(actualRegistry ?? registry,typed,new Dictionary<string,string>(),new Dictionary<string,string>());
            SemanticEffectCatalog semantics=new(typed,new Dictionary<string,EvidenceObject> { ["NormalCalcZone"]=Obj("{}") },approval);
            EffectSpecificationCatalog specifications=new(approval,semantics,new(typed));
            PacketEffectDisplayCatalog display=new(packets,new(new Dictionary<string,EvidenceObject>(),_=>null));
            return new(typed,new(semantics,new(packets,new Dictionary<string,EvidenceObject>(),new Dictionary<string,EvidenceObject>()),display),
                specifications,new(approval,specifications,typed,packets),display,
                new(packets,new Dictionary<string,IReadOnlySet<string>> { ["suit_a"]=new HashSet<string> { "buff_equipsuit_a" } }),
                new(typed),approval,new(typed,new Dictionary<string,string>(),approval));
        }
        var builder=Builder();
        EffectRecordCache ownedCache = new();
        EffectWindowBuildResult Owned(EvidenceObject source, int end) => builder.BuildOwned([source], [], end,
            new Dictionary<string,double>(), new Dictionary<string,HashSet<string>>(), new Dictionary<string,string>(), ownedCache);
        var ownedFirst = Owned(record, 2000);
        var ownedBefore = EvidenceJsonSignature.Sorted(ownedFirst.Records[0]);
        var ownedNext = Owned(record, 2500);
        check(ownedCache.ReusedRecords == 1
            && ReferenceEquals(ownedFirst.Records[0].Get("bb_values"), ownedNext.Records[0].Get("bb_values"))
            && EvidenceJson.PythonEquals(new EvidenceArray(ownedNext.Windows), new EvidenceArray(builder.Build([record], [], 2500).Windows)),
            "Owned live windows share protected record evidence and retain report-local lifetimes");
        EffectRecordCache frozenCache = new();
        EffectWindowBuildResult Frozen(EvidenceObject source, int end) => builder.BuildOwned([source], [], end,
            new Dictionary<string,double>(), new Dictionary<string,HashSet<string>>(), new Dictionary<string,string>(), frozenCache, readOnlyRecords: true);
        var frozenFirst = Frozen(record, 2000);
        var frozenNext = Frozen(record, 2500);
        var frozenBefore = EvidenceJsonSignature.Sorted(frozenFirst.Records[0]);
        check(ReferenceEquals(frozenFirst.Records[0], frozenNext.Records[0])
            && EvidenceJson.PythonEquals(new EvidenceArray(frozenNext.Windows), new EvidenceArray(builder.Build([record], [], 2500).Windows))
            && frozenFirst.Windows.Single().Get("end_ts_ms") is EvidenceInteger { Value: var frozenEnd } && frozenEnd == 2000,
            "Read-only summary records reuse the same cache root while open windows keep independent report end times");
        var frozenLate = Frozen(Change(record, ("bb_values", Obj("""{"rate":0.4}"""))), 2500);
        var publicFrozen = builder.Build([record], [], 2500, recordCache: frozenCache);
        ((Dictionary<string,EvidenceValue>)((EvidenceObject)publicFrozen.Records[0].Get("bb_values")).Fields)["rate"] = new EvidenceReal(99);
        check(((EvidenceObject)frozenLate.Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value: .4 }
            && frozenBefore == EvidenceJsonSignature.Sorted(frozenFirst.Records[0])
            && ((EvidenceObject)Frozen(record, 2500).Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value: .2 },
            "Late parameters and editable public reports cannot alter earlier or later protected summary records");
        var rejectedMutation = false;
        try { ((IDictionary<string,EvidenceValue>)((EvidenceObject)ownedNext.Records[0].Get("bb_values")).Fields)["rate"] = new EvidenceReal(99); }
        catch (NotSupportedException) { rejectedMutation = true; }
        ((Dictionary<string,EvidenceValue>)ownedNext.Records[0].Fields)["end_ts_ms"] = new EvidenceInteger(1100);
        var cachedEffect = (EvidenceObject)((EvidenceArray)ownedNext.Windows[0].Get("zone_effects")).Items[0];
        var rejectedEffectMutation = false;
        try { ((IDictionary<string,EvidenceValue>)cachedEffect.Fields)["rate"] = new EvidenceReal(99); }
        catch (NotSupportedException) { rejectedEffectMutation = true; }
        check(rejectedMutation && rejectedEffectMutation && EvidenceJsonSignature.Sorted(ownedFirst.Records[0]) == ownedBefore
            && Owned(record, 2500).Windows.Single().Get("end_ts_ms") is EvidenceInteger { Value: var ownedEnd } && ownedEnd == 2500,
            "Owned descendants reject mutation while writable report roots cannot alter previous reports or cached analyses");
        var publicAfterOwned = builder.Build([record], [], 2500, recordCache: ownedCache);
        ((Dictionary<string,EvidenceValue>)((EvidenceObject)publicAfterOwned.Records[0].Get("bb_values")).Fields)["rate"] = new EvidenceReal(99);
        check(((EvidenceObject)Owned(record, 2500).Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value: .2 },
            "Public cache reads remain deeply mutable without changing subsequent owned reads");
        var closed = Change(record, ("end_ts_ms", new EvidenceInteger(1800)), ("end_line_no", new EvidenceInteger(22)));
        var frozenClosed = Frozen(closed, 2000);
        var frozenClosedNext = Frozen(closed, 9000);
        check(ReferenceEquals(frozenClosed.Windows.Single(), frozenClosedNext.Windows.Single())
            && ReferenceEquals(FrozenEvidence.CopyOwned(frozenClosed.Windows.Single()), frozenClosed.Windows.Single())
            && EvidenceJsonSignature.Sorted(frozenClosedNext.Windows.Single()) == EvidenceJsonSignature.Sorted(builder.Build([closed], [], 9000).Windows.Single()),
            "A completed summary window reuses its final protected limits and passes through owned ledger capture without copying descendants");
        var frozenClosedBefore = EvidenceJsonSignature.Sorted(frozenClosed.Windows.Single());
        var frozenRevised = Frozen(Change(closed, ("bb_values", Obj("""{"rate":0.4}"""))), 9000);
        var frozenRebounded = Frozen(Change(closed, ("snapshot_end_ts_ms", new EvidenceInteger(1800)), ("snapshot_end_line_no", new EvidenceInteger(19))), 9000);
        check(!ReferenceEquals(frozenRevised.Windows.Single(), frozenClosed.Windows.Single())
            && ((EvidenceObject)((EvidenceArray)frozenRevised.Windows.Single().Get("zone_effects")).Items[0]).Get("rate") is EvidenceReal { Value: .4 }
            && frozenRebounded.Windows.Single().Get("end_line_no") is EvidenceInteger { Value: var rebound } && rebound == 19
            && frozenClosedBefore == EvidenceJsonSignature.Sorted(frozenClosed.Windows.Single()),
            "Late parameters and snapshot boundaries replace limited summary windows without changing earlier evidence");
        var editableLimited = builder.BuildOwned([closed], [], 9000, new Dictionary<string,double>(),
            new Dictionary<string,HashSet<string>>(), new Dictionary<string,string>(), frozenCache);
        ((Dictionary<string,EvidenceValue>)editableLimited.Windows.Single().Fields)["stack_limit"] = new EvidenceInteger(99);
        check(frozenClosedBefore == EvidenceJsonSignature.Sorted(Frozen(closed, 9000).Windows.Single()),
            "Switching from summary to an editable full report cannot mutate retained limited summary windows");
        var assembledBefore = ownedCache.AssembledWindows;
        var reusedBefore = ownedCache.ReusedWindows;
        var closedFirst = Owned(closed, 2000);
        var closedNext = Owned(closed, 9000);
        check(ownedCache.AssembledWindows == assembledBefore + 1 && ownedCache.ReusedWindows == reusedBefore + 1
            && EvidenceJsonSignature.Sorted(closedFirst.Windows.Single()) == EvidenceJsonSignature.Sorted(closedNext.Windows.Single())
            && EvidenceJsonSignature.Sorted(closedNext.Windows.Single()) == EvidenceJsonSignature.Sorted(builder.Build([closed], [], 9000).Windows.Single()),
            "A removed instance reuses its exact window when the report advances without extending its observed end");
        ((Dictionary<string,EvidenceValue>)closedFirst.Windows.Single().Fields)["end_ts_ms"] = new EvidenceInteger(9999);
        var shifted = Change(closed, ("snapshot_end_ts_ms", new EvidenceInteger(1800)), ("snapshot_end_line_no", new EvidenceInteger(19)));
        var revisedBoundary = Owned(shifted, 9000).Windows.Single();
        check(Owned(closed, 9000).Windows.Single().Get("end_ts_ms") is EvidenceInteger { Value: var retainedEnd } && retainedEnd == 1800
            && revisedBoundary.Get("end_line_no") is EvidenceInteger { Value: var earlierLine } && earlierLine == 19,
            "Returned window roots cannot corrupt reuse, and a late snapshot boundary replaces the removal line");
        var strength = new Dictionary<string,double> { ["source"] = 42.5 };
        var strengthened = builder.BuildOwned([closed], [], 9000, strength,
            new Dictionary<string,HashSet<string>>(), new Dictionary<string,string>(), ownedCache);
        check(strengthened.Windows.Single().Get("source_static_arts_strength") is EvidenceReal { Value: 42.5 }
            && EvidenceJsonSignature.Sorted(strengthened.Windows.Single()) == EvidenceJsonSignature.Sorted(builder.Build([closed], [], 9000, strength).Windows.Single())
            && Owned(closed, 9000).Windows.Single().Get("source_static_arts_strength") is EvidenceReal { Value: 0 },
            "A cached closed window follows late loadout strength changes and restores an earlier strength without stale evidence");
        var lateEnable = Change(closed, ("enable_observations", new EvidenceArray([Obj("""{"ts_ms":1200,"line_no":12,"enabled":false}""")])));
        var changedParameters = Change(closed, ("bb_values", Obj("""{"rate":0.4}""")));
        check(new[] { lateEnable, changedParameters }.All(source => EvidenceJsonSignature.Sorted(Owned(source, 9000).Windows.Single())
                == EvidenceJsonSignature.Sorted(builder.Build([source], [], 9000).Windows.Single())),
            "Late enable observations and parameter changes invalidate completed window evidence under the same UID");
        EffectRecordCache recordCache = new();
        var cachedFirst = builder.Build([record], [], 2000, recordCache: recordCache);
        ((Dictionary<string,EvidenceValue>)((EvidenceObject)cachedFirst.Records[0].Get("bb_values")).Fields)["rate"] = new EvidenceReal(9);
        var cachedNext = builder.Build([record], [], 2500, new Dictionary<string,double> { ["source"] = 8 }, recordCache: recordCache);
        check(recordCache.AnalyzedRecords == 1 && recordCache.ReusedRecords == 1
            && cachedNext.Windows.Single().Get("end_ts_ms") is EvidenceInteger { Value:var cachedEnd } && cachedEnd == 2500
            && cachedNext.Windows.Single().Get("source_static_arts_strength") is EvidenceReal { Value:8 }
            && ((EvidenceObject)cachedNext.Records[0].Get("bb_values")).Get("rate") is EvidenceReal { Value:.2 },
            "Record reuse preserves detached evidence while new report boundaries and static loadouts are still applied");
        var changedRate = Change(record, ("bb_values", Obj("{\"rate\":0.4}")));
        var cachedChanged = builder.Build([changedRate], [], 2500, recordCache: recordCache);
        check(recordCache.AnalyzedRecords == 2
            && EvidenceJson.PythonEquals(new EvidenceArray(cachedChanged.Windows), new EvidenceArray(builder.Build([changedRate], [], 2500).Windows))
            && EvidenceJson.PythonEquals(new EvidenceArray(builder.Build([record], [], 2500, recordCache: recordCache).Windows),
                new EvidenceArray(builder.Build([record], [], 2500).Windows)),
            "Changed parameters under the same UID invalidate record analysis; revisiting an earlier exact variant restores its own result");
        var integralEvidence = Change(record, ("extra_evidence", Obj("{\"value\":[0,1]}")));
        var realEvidence = Change(record, ("extra_evidence", Obj("{\"value\":[-0.0,1.0]}")));
        builder.Build([integralEvidence], [], 2500, recordCache: recordCache);
        var realResult = builder.Build([realEvidence], [], 2500, recordCache: recordCache);
        check(((EvidenceObject)realResult.Records[0].Get("extra_evidence")).Get("value") is EvidenceArray
                { Items: [EvidenceReal { Value: var signedZero }, EvidenceReal { Value: 1 }] }
            && BitConverter.DoubleToInt64Bits(signedZero) == BitConverter.DoubleToInt64Bits(-0.0),
            "Record reuse preserves nested numeric evidence types and the sign of zero");
        builder.Build([Change(record, ("extra_evidence", Obj("{\"a\":1,\"b\":2}")))], [], 2500, recordCache: recordCache);
        var reordered = builder.Build([Change(record, ("extra_evidence", Obj("{\"b\":2,\"a\":1}")))], [], 2500, recordCache: recordCache);
        check(((EvidenceObject)reordered.Records[0].Get("extra_evidence")).Fields.Keys.SequenceEqual(new[] { "b", "a" }),
            "Private field sharing preserves observed nested field order");
        var independentBuilder = Builder(actualRegistry: Obj("{\"verified_effects\":{}}"));
        check(EvidenceJson.PythonEquals(new EvidenceArray(independentBuilder.Build([record], [], 2500, recordCache: recordCache).Windows),
                new EvidenceArray(independentBuilder.Build([record], [], 2500).Windows)),
            "A record cache cannot transfer approvals between separate resource owners");
        var original=EvidenceJsonSignature.Sorted(record);
        var window=builder.Build([Change(record,("end_ts_ms",new EvidenceInteger(1800)),("raw_duration_ms",new EvidenceInteger(10)))],[],2000).Windows.Single();
        check(window.Get("end_ts_ms") is EvidenceInteger { Value:var observedEnd } && observedEnd==1800,
            "An explicit observed end includes pauses and wins over the shorter nominal lifetime");
        var snapshot=builder.Build([Change(record,("end_ts_ms",new EvidenceInteger(1800)),("end_line_no",new EvidenceInteger(22)),
            ("snapshot_end_ts_ms",new EvidenceInteger(1800)),("snapshot_end_line_no",new EvidenceInteger(19)))],[],2000).Windows.Single();
        check(snapshot.Get("end_line_no") is EvidenceInteger { Value:var boundaryLine } && boundaryLine==19
            && EffectWindowEvaluation.At(snapshot,new(1800,18)).Effects.Count==1 && EffectWindowEvaluation.At(snapshot,new(1800,19)).Effects.Count==0,
            "A coincident snapshot boundary supplies the exclusive end line, ahead of the later explicit removal");
        var open=builder.Build([record],[],2000,new Dictionary<string,double> { ["source"]=42.5 }).Windows.Single();
        check(open.Get("end_is_observation_boundary") is EvidenceBoolean { Value:true }
            && open.Get("source_static_arts_strength") is EvidenceReal { Value:42.5 },
            "An observed Infinity instance is bounded by the report and retains its provider's static arts strength");
        var instant=builder.Build([record],[],1000).Windows.Single();
        check(instant.Get("end_ts_ms") is EvidenceInteger { Value:var sameTime } && sameTime==1000
            && instant.Get("duration_ms") is EvidenceInteger { Value:var duration } && duration==1
            && builder.Build([Change(record,("snapshot_end_ts_ms",new EvidenceInteger(999)))],[],2000).Windows.Count==0,
            "A zero-width observed window keeps its timestamp with duration one, while a reversed snapshot is excluded");
        var priorityRoots=new Dictionary<string,EvidenceObject>(roots) { ["buff"]=Change(root,("stackingSettings",Obj("""{"stackingType":"HighPriority"}"""))) };
        var priority=Builder(priorityRoots);
        var unobserved=priority.Build([record],[],2000).Windows.Single();
        var missing=EffectWindowEvaluation.At(unobserved,new(1200,12));
        check(unobserved.Get("requires_enable_observation") is EvidenceBoolean { Value:true }
            && unobserved.Get("stack_limit") is EvidenceInteger { Value:var limit } && limit==1
            && missing.Effects.Count==0 && missing.Window.Get("rdps_unresolved_enable_evidence") is EvidenceBoolean { Value:true },
            "HighPriority containers require observed enable state and expose unresolved evidence rather than assumed credit");
        var observations=(EvidenceArray)EvidenceJson.Parse("""
            [{"ts_ms":1000,"line_no":10,"operationSeq":1,"enabled":false},
             {"ts_ms":1200,"line_no":12,"operationSeq":2,"enabled":true}]
            """);
        var enabled=priority.Build([Change(record,("enable_observations",observations))],[],2000).Windows.Single();
        check(EffectWindowEvaluation.At(enabled,new(1100,11)).Effects.Count==0
            && EffectWindowEvaluation.At(enabled,new(1200,12)).Effects.Count==1,
            "The assembled enable timeline gates effects at the observed transition without shifting the skill window");
        var equipped=Change(record,("event_key",new EvidenceText("buff_equipsuit_a")));
        check(builder.Build([equipped],[],2000,activeSuits:new Dictionary<string,HashSet<string>> { ["source"]=[] }).Windows.Count==0
            && builder.Build([equipped],[],2000,activeSuits:new Dictionary<string,HashSet<string>>()).Windows.Count==1
            && builder.Build([equipped],[],2000,activeSuits:new Dictionary<string,HashSet<string>> { ["source"]=["suit_a"] }).Windows.Count==1,
            "Known empty equipment excludes its suit window; missing loadout evidence and the matching suit retain it");
        var repeats=builder.Build([record,record,Change(record,("uid",new EvidenceText("8")))],[],2000);
        check(repeats.Records.Count==3 && repeats.Windows.Count==2
            && repeats.Windows.Select(item=>((EvidenceText)item.Get("uid")).Value).SequenceEqual(["7","8"]),
            "Only an exact mirrored window is removed; an independently observed instance remains distinct");
        var stale=Change(record,("rdps_unresolved_semantic_condition",new EvidenceArray([new EvidenceText("old")])),
            ("rdps_unresolved_dynamic_effect",new EvidenceBoolean(true)));
        var refreshed=builder.Build([stale,Change(stale,("uid_observation_only",new EvidenceBoolean(true)))],[],2000);
        check(refreshed.Records[0].Get("rdps_unresolved_semantic_condition") is EvidenceNull
            && refreshed.Records[0].Get("rdps_unresolved_dynamic_effect") is EvidenceNull
            && refreshed.Records[1].Get("rdps_unresolved_dynamic_effect") is EvidenceBoolean { Value:true },
            "Quality is refreshed in the report-local label/static/dynamic pipeline while UID-only observations stay untouched");
        check(EvidenceJsonSignature.Sorted(record)==original
            && !ReferenceEquals(open.Get("bb_values"),record.Get("bb_values"))
            && !ReferenceEquals(refreshed.Records[0].Get("bb_values"),stale.Get("bb_values"))
            && builder.Build([record],[],2000).Windows.Count==1,
            "Window blackboards and enriched records are independently owned and repeated calls leave source evidence unchanged");
        var dynamic=builder.Build([Change(record,("event_key",new EvidenceText("buff_dynamic")),("raw_event_key",new EvidenceText("buff_dynamic")),
            ("bb_keys",new EvidenceArray([new EvidenceText("base")])),("bb_values",Obj("""{"base":0.3}""")))],[],2000).Windows.Single();
        var evaluated=EffectWindowEvaluation.At(dynamic,new(1200,12));
        check(dynamic.Get("zone_effects") is EvidenceArray { Items.Count:0 }
            && evaluated.Effects is [EvidenceObject effect] && effect.Get("rate") is EvidenceReal { Value:0.3 },
            "An approved dynamic-only instance becomes a window and resolves the observed base rate at a hit");

        // Reuse only fixed chain inputs; expected exact-hit behavior is asserted here rather than read from a golden.
        var fixture=JsonNode.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../Fixtures/combo-windows.json"))))!;
        var comboRoots=(EvidenceObject)EvidenceJson.Parse(fixture["roots_json"]!.GetValue<string>());
        var mergedRoots=new Dictionary<string,EvidenceObject>(roots);
        foreach(var pair in comboRoots.Fields) mergedRoots[pair.Key]=(EvidenceObject)pair.Value;
        var comboRegistry=(EvidenceObject)EvidenceJson.Parse(fixture["registry_json"]!.GetValue<string>());
        var config=(EvidenceObject)EvidenceJson.Parse(fixture["cases"]![0]!["config_json"]!.GetValue<string>());
        var hits=((EvidenceArray)config.Get("hits")).Items.Cast<EvidenceObject>().ToArray();
        var chain=((EvidenceArray)config.Get("records")).Items.Cast<EvidenceObject>().Select(item=>
            new EvidenceObject(new Dictionary<string,EvidenceValue>(record.Fields).Concat(item.Fields)
                .GroupBy(pair=>pair.Key).ToDictionary(group=>group.Key,group=>group.Last().Value))).ToArray();
        var joined=Builder(mergedRoots,comboRegistry).Build([record,..chain],hits,2000);
        var exactWindows=joined.Windows.Where(item=>item.Get("combo_source_uids") is EvidenceArray).ToArray();
        check(joined.Windows.Count>=2 && exactWindows is [var exact]
            && EffectWindowEvaluation.At(exact,new(1500,50,20,"synthetic-combo-session")).Effects.Count==1
            && EffectWindowEvaluation.At(exact,new(1500,51,21,"synthetic-combo-session")).Effects.Count==0,
            "Ordinary and combo windows share final assembly while combo attribution remains restricted to its exact hit");

        SkillIdentityCatalog identities=new(new Dictionary<string,string>(),new Dictionary<string,string>(),new Dictionary<string,RuntimeBuffDamageProfile>());
        var empty=new Dictionary<string,EvidenceObject>();
        BattleIngestionResources resources=new()
        {
            Identities=identities,BuffMappings=new(empty,new Dictionary<string,IReadOnlyList<EvidenceObject>>(),new Dictionary<string,string>()),
            BuffRoots=roots,BuffNumbers=new Dictionary<string,string>(),Loadouts=new(empty,empty,empty,new(empty),identities,key=>key),
            Metadata=_=>new("","","",new Dictionary<BigInteger,string>(),false),DamageUnits=_=>new Dictionary<BigInteger,IReadOnlyList<SkillDamageUnit>>(),
            SkillProfile=_=>null,CharacterName=key=>key,EnemyName=key=>key,SkillName=key=>key,Dungeon=_=>null,
        };
        BattleIngestionStream stream=new(resources);
        stream.Accept(1,"[00:00:01.000] BUFF_START uid=7 id=buff owner=chr_0001_alpha ownerId=11 src=chr_0001_alpha srcId=11");
        stream.Accept(2,"[00:00:01.000] BB[ rate=0.2 ]");
        stream.Accept(3,"[00:00:01.500] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target hit=100");
        stream.Party.ActiveSuits["chr_0001_alpha"]=["suit_a"];
        var captured=ReportEffectInput.Capture(stream,2000);
        stream.Accept(4,"[00:00:01.600] BASELINE #1 1=40");
        stream.Accept(5,"[00:00:01.800] BUFF_END uid=7");
        stream.Buffs.Records[0].BlackboardValues["rate"]=.9;
        stream.Party.ActiveSuits["chr_0001_alpha"].Clear();
        var built=builder.Build(captured);
        check(built.Windows is [var capturedWindow] && capturedWindow.Get("end_ts_ms") is EvidenceInteger { Value:var capturedEnd } && capturedEnd==2000
            && capturedWindow.Get("bb_values") is EvidenceObject bb && bb.Get("rate") is EvidenceReal { Value:.2 },
            "A captured report input remains independent of later BUFF removal and blackboard updates on its ingestion stream");
        check(captured.Hits.Single().Get("baseline") is EvidenceNull && captured.ActiveSuits["chr_0001_alpha"].SetEquals(["suit_a"])
            && ReportEffectInput.Capture(stream,2000).Hits.Single().Get("baseline") is EvidenceObject baseline
            && baseline.Get("1") is EvidenceReal { Value:40 },
            "Late packet evidence and loadout changes enter only the next report capture");

        var catalogFixture=JsonNode.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../Fixtures/catalogs.json"))))!
            .AsArray().Single(item=>item!["name"]!.GetValue<string>()=="buff_roots/145")!;
        var directory=Path.Combine(Path.GetTempPath(),"endfield-report-factory-"+Guid.NewGuid().ToString("N"));
        try
        {
            foreach(var (relative,contents) in catalogFixture["files"]!.AsObject())
            {
                var path=Path.Combine(directory,relative);Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllText(path,contents!.GetValue<string>());
            }
            foreach(var (relative,contents) in catalogFixture["binary_files"]!.AsObject())
            {
                var path=Path.Combine(directory,relative);Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllBytes(path,Convert.FromBase64String(contents!.GetValue<string>()));
            }
            var registryPath=Path.Combine(directory,"_internal/data/packet_semantics/rdps_semantics_registry.json");
            Directory.CreateDirectory(Path.GetDirectoryName(registryPath)!);
            File.WriteAllText(registryPath,"""
                {"verified_effects":{"buff_synthetic":{"dynamic":true,"dynamic_effects":[{"zone":"amp","element":"all","base_bb_key":"base"}]}}}
                """);
            var factoryRecord=Change(record,("event_key",new EvidenceText("buff_synthetic")),("raw_event_key",new EvidenceText("buff_synthetic")),
                ("bb_keys",new EvidenceArray([new EvidenceText("base")])),("bb_values",Obj("""{"base":0.3}""")));
            var loaded=EffectWindowBuilder.Load(new(Path.Combine(directory,"_internal")));
            var fromFiles=loaded.Build([factoryRecord],[],2000).Windows.Single();
            check(fromFiles.Get("end_ts_ms") is EvidenceInteger { Value:var factoryEnd } && factoryEnd==2000
                && EffectWindowEvaluation.At(fromFiles,new(1500,20)).Effects is [EvidenceObject factoryEffect]
                && factoryEffect.Get("rate") is EvidenceReal { Value:.3 },
                "The production resource loader joins the verified typed lifetime and reviewed dynamic formula");
            var before=EvidenceJsonSignature.Sorted(fromFiles);
            var separate=EffectWindowBuilder.Load(new(Path.Combine(directory,"_internal"))).Build([factoryRecord],[],1200).Windows.Single();
            check(separate.Get("end_ts_ms") is EvidenceInteger { Value:var separateEnd } && separateEnd==1200
                && EvidenceJsonSignature.Sorted(fromFiles)==before,
                "Independent resource-backed report builders cannot change an earlier report's window");
        }
        finally { if(Directory.Exists(directory)) Directory.Delete(directory,recursive:true); }
    }
}
