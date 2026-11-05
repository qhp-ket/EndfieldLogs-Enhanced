using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;

internal static class InkProvenanceSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject item, string key, EvidenceValue value) => new(new Dictionary<string, EvidenceValue>(item.Fields) { [key] = value });
    internal static EvidenceObject Root() => Obj("""
        {"actions":[
          {"serverActionIndex":45,"isEnable":true,"$type":"Beyond.Gameplay.Core.SaveDamageContext.Data","saveTo":"ink_damage","valueType":"RealValue"},
          {"serverActionIndex":46,"isEnable":true,"$type":"Beyond.Gameplay.Core.SimpleCalcBBAction.Data","key":"ink_damage2","operation":"Multiply","value1":{"useBlackboardKey":true,"blackboardKey":"ink_damage"},"value2":{"useBlackboardKey":true,"blackboardKey":"ink_damage_rate"}},
          {"serverActionIndex":47,"isEnable":true,"$type":"Beyond.Gameplay.Core.SimpleCalcBBAction.Data","key":"EntityBB_ink_damage","operation":"Add","value1":{"useBlackboardKey":true,"blackboardKey":"EntityBB_ink_damage"},"value2":{"useBlackboardKey":true,"blackboardKey":"ink_damage2"}},
          {"serverActionIndex":14,"isEnable":true,"$type":"Beyond.Gameplay.Core.LaunchProjectile.Data"},
          {"serverActionIndex":15,"isEnable":true,"$type":"Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data","key":"EntityBB_ink_damage","operation":"Assign","value":{"value":0}}]}
        """);
    internal static (string[] Lines, EvidenceObject[] Hits, EvidenceObject[] Records) Scenario()
    {
        var buff = InkProvenanceStream.Buff;
        var lines = new[] { "[00:00:00.000] CONTEXT", "[00:00:00.000] SOURCE",
            $"[00:00:00.000] BB_MODIFY_DYNAMIC seq=101 tick=1000 inst=7 ownerId=3 skill={buff} actionId=45 value=200",
            $"[00:00:00.000] BB_SIMPLE_CALC seq=102 tick=1000 inst=7 ownerId=3 skill={buff} actionId=47 key=EntityBB_ink_damage valueA=0 valueB=200 final=200",
            "[00:00:00.000] INK_RELEASE {\"schema_version\":1,\"template_key\":\"" + buff + "\",\"action_id\":14,\"session_id\":\"s\",\"operation_seq\":130,\"buff_uid\":\"7\",\"owner_id\":\"3\",\"source_actor_id\":\"4\",\"projectile_id\":\"8\"}",
            $"[00:00:00.000] BB_MODIFY_DYNAMIC seq=132 tick=1000 inst=7 ownerId=3 skill={buff} actionId=15 value=0", "[00:00:00.000] EXPLOSION" };
        var source = Obj("""{"line_no":2,"seq":1,"character_key":"attacker","packet_session_id":"s","packet_seq_id":100,"client_tick_ms":1000,"target_actor_id":"3","packet_final_value":200,"rdps_contributions":{"attacker":100,"support":100}}""");
        var explosion = Obj("""{"line_no":7,"seq":2,"character_key":"chr_0036_jsspsi","target_actor_id":"3","source_actor_id":"4","packet_session_id":"s","packet_seq_id":140,"event_owner_id":"8","event_inst_id":"9","client_tick_ms":1000,"skill_key":"chr_0036_jsspsi_normal_skill_inkmark_projhit","packet_final_value":200,"hit_value":100,"rdps_contributions":{"chr_0036_jsspsi":100},"damage_calculation":{"atkCalculation":{"value":{"blackboardKey":"EntityBB_ink_damage","useBlackboardKey":true}}}}""");
        var record = Obj("""{"event_key":"buff_chr_0036_jsspsi_xianjing_inkhurteffect","uid":"7","source_character_key":"chr_0036_jsspsi","source_actor_id":"4","target_actor_id":"3","line_no":1,"packet_creation_contexts":[{"session_id":"s","operation_seq":1}]}""");
        return (lines, [source, explosion], [record]);
    }
    public static void Run(Action<bool, string> check)
    {
        var scenario = Scenario();
        var roots = new Dictionary<string, EvidenceObject> { [InkProvenanceStream.Buff] = Root() };
        var before = string.Join("", scenario.Hits.Concat(scenario.Records).Select(EvidenceJsonSignature.Sorted));
        var result = InkProvenanceStream.Apply(string.Join('\n', scenario.Lines), scenario.Hits, scenario.Records, roots);
        var shares = (EvidenceObject)result.Hits[1].Get("rdps_contributions");
        double Credit(string key) => ((EvidenceReal)shares.Get(key)).Value;
        check(Math.Abs(Credit(InkProvenanceStream.Owner) - 50) < 2e-12 && Math.Abs(Credit("support") - 50) < 2e-12,
            "Equal log(2) source and recording zones split the effective 100 damage equally by hand calculation");
        check(Math.Abs(Credit(InkProvenanceStream.Owner) + Credit("support") - 100) < 1e-12 && shares.Get("attacker") is EvidenceNull,
            "Recorded ink distributes the entire observed component without reserving an attacker baseline");
        check(result.Summary.Get("resolved") is EvidenceInteger resolved && resolved.Value == 1 && result.Summary.Get("paired_records") is EvidenceInteger paired && paired.Value == 1,
            "A uniquely paired source with verified release resolves once");
        check(((EvidenceObject)result.Hits[1].Get("ink_provenance")).Get("binding") is EvidenceText { Value: "packet_projectile_id" },
            "Explicit projectile identity binds the frozen release after accumulator reset");
        check(before == string.Join("", scenario.Hits.Concat(scenario.Records).Select(EvidenceJsonSignature.Sorted))
            && EvidenceJsonSignature.Sorted(result.Hits[0]) == EvidenceJsonSignature.Sorted(scenario.Hits[0]),
            "Source attribution and original report evidence remain unchanged");
        var stream = new InkProvenanceStream(roots);
        var numbered = scenario.Lines.Select((line, index) => new InkTraceLine(index + 1, line)).ToArray();
        var first = stream.Advance(numbered.Take(4), [scenario.Hits[0]], scenario.Records);
        ((Dictionary<string, EvidenceValue>)first.Hits[0].Fields)["rdps_contributions"] = Obj("""{"attacker":200}""");
        var continued = stream.Advance(numbered.Skip(4), scenario.Hits, scenario.Records);
        check(EvidenceJsonSignature.Sorted(continued.Hits[1]) == EvidenceJsonSignature.Sorted(result.Hits[1]),
            "Chunking and editing a returned snapshot cannot change the continuing source ledger");
        var repeated = Change(Change(scenario.Hits[1], "line_no", new EvidenceInteger(8)), "packet_seq_id", new EvidenceInteger(150));
        var duplicate = stream.Advance([new(8, "[00:00:00.000] EXPLOSION")], [repeated], scenario.Records);
        check(((EvidenceObject)duplicate.Hits[0].Get("ink_provenance")).Get("reason") is EvidenceText { Value: "ink_projectile_already_consumed" },
            "A projectile can account for only one explosion");
        stream.Reset();
        var reset = stream.Advance(numbered, scenario.Hits, scenario.Records);
        check(EvidenceJsonSignature.Sorted(reset.Summary) == EvidenceJsonSignature.Sorted(result.Summary),
            "Reset clears release, source, counters and sequence state for the next analysis");
        var missing = InkProvenanceStream.Apply(string.Join('\n', scenario.Lines), [scenario.Hits[1]], scenario.Records, roots);
        check(((EvidenceObject)missing.Hits[0].Get("rdps_contributions")).Get(InkProvenanceStream.Owner) is EvidenceReal { Value: 100 }
            && ((EvidenceObject)missing.Hits[0].Get("ink_provenance")).Get("status") is EvidenceText { Value: "partial" }
            && missing.Hits[0].Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true },
            "Missing source evidence keeps the entire component with its owner and reports partial quality");
        var unknown = InkProvenanceStream.Apply(string.Join('\n', scenario.Lines), scenario.Hits, scenario.Records, new Dictionary<string, EvidenceObject>());
        check(((EvidenceObject)unknown.Hits[1].Get("ink_provenance")).Get("reason") is EvidenceText { Value: "typed_ink_formula_unverified" },
            "Unverified resources cannot authorize the recording formula");
        check(InkProvenanceStream.VerifyProfile(Root()) && !InkProvenanceStream.VerifyProfile(Change(Root(), "actions", new EvidenceArray([]))),
            "The complete typed action profile is required");
        check(PythonTextLines.Split("a\r\nb\u2028c\n").SequenceEqual(["a", "b", "c"]) && !PythonTextLines.Split("").Any(),
            "Trace numbering preserves Python line boundaries without a terminal phantom line");
        var noExplosion = InkProvenanceStream.Apply("unrelated", [scenario.Hits[0]], scenario.Records, roots);
        check(noExplosion.Summary.Fields.Count == 0, "Offline traces without ink explosions have no ink summary");
        var weight = InkProvenanceStream.RecordWeights(Change(scenario.Hits[0], "packet_final_value", new EvidenceInteger(120)), .000001)!;
        check(BitConverter.DoubleToUInt64Bits(weight[InkProvenanceStream.Owner]) == 0x3e41e54c65e83354UL,
            "Small recording ratios keep the fixed Windows log1p result instead of log(1+x) cancellation");
        Structured(check);
    }

    private static TraceEvent Event(string kind, EvidenceObject data)
    {
        var value = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)value.Value).Fields.ToDictionary(); fields["legacy_layout"] = value.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, 1000, kind, new(fields), Obj("{}"))), header: false);
    }
    private static TraceEvent Dynamic(int sequence, int action, double value)
    {
        var source = Obj("""{"inst_id":7,"owner_id":3,"client_tick_tms":1000,"session_id":"s"}""");
        source = Change(source, "seq_id", new EvidenceInteger(sequence));
        var identity = Obj("""{"schemaVersion":1,"sessionId":"s","ownerType":1,"ownerId":"3","environmentInstId":"7","templateType":"Buff","clientTickMs":"1000","triggerType":0,"actionType":7,"actionRuntimeCase":"modify_dynamic_blackboard_action","operationPayloadCase":"trigger_action_op_data"}""");
        identity = Change(Change(identity, "operationSeq", new EvidenceInteger(sequence)), "actionId", new EvidenceInteger(action));
        return Event("blackboard_dynamic", DynamicWire.Data(source, new EvidenceInteger(action), value, "?", InkProvenanceStream.Buff, identity));
    }
    internal static TraceEvent[] Events()
    {
        var calculation = Event("blackboard_calculation", BlackboardWire.Data(Obj("""{"inst_id":7,"owner_id":3,"client_tick_tms":1000,"session_id":"s","seq_id":102}"""), 47, "?", InkProvenanceStream.Buff,
            ("key", new EvidenceText("EntityBB_ink_damage")), ("value_a", new EvidenceReal(0)), ("value_b", new EvidenceReal(200)), ("final_value", new EvidenceReal(200))));
        var release = Event("ink_release", BlackboardWire.ReleaseData(Obj("""{"schema_version":1,"template_key":"buff_chr_0036_jsspsi_xianjing_inkhurteffect","action_id":14,"session_id":"s","operation_seq":130,"client_tick_ms":1000,"buff_uid":"7","owner_id":"3","source_actor_id":"4","projectile_id":"8"}""")));
        return [Event("blackboard_preset", Obj("""{"modified_value":"context"}""")), Event("damage", Obj("{}")), Dynamic(101, 45, 200), calculation, release, Dynamic(132, 15, 0), Event("damage", Obj("{}"))];
    }

    private static void Structured(Action<bool, string> check)
    {
        var scenario = Scenario();
        Dictionary<string, EvidenceObject> roots = new() { [InkProvenanceStream.Buff] = Root() };
        var expected = InkProvenanceStream.Apply(string.Join('\n', scenario.Lines), scenario.Hits, scenario.Records, roots);
        var events = Events();
        var calculation = events[3];
        var numbered = events.Select((item, index) => (new BigInteger(index + 1), item)).ToArray();
        var stream = new InkProvenanceStream(roots);
        var first = stream.AdvanceEvents(numbered.Take(4), [scenario.Hits[0]], scenario.Records);
        ((Dictionary<string, EvidenceValue>)first.Hits[0].Fields)["rdps_contributions"] = Obj("""{"attacker":200}""");
        var result = stream.AdvanceEvents(numbered.Skip(4), scenario.Hits, scenario.Records);
        check(EvidenceJsonSignature.Sorted(result.Hits[1]) == EvidenceJsonSignature.Sorted(expected.Hits[1])
            && EvidenceJsonSignature.Sorted(result.Summary) == EvidenceJsonSignature.Sorted(expected.Summary),
            "Direct JSONL events preserve source pairing and frozen release through chunking and accumulator reset");
        stream.Reset();
        check(EvidenceJsonSignature.Sorted(stream.AdvanceEvents(numbered, scenario.Hits, scenario.Records).Hits[1]) == EvidenceJsonSignature.Sorted(expected.Hits[1]),
            "Direct event reset isolates the next analysis and does not mutate event inputs");
        var conflictData = BlackboardWire.Observation(calculation).Fields.ToDictionary();
        conflictData["value_b"] = new EvidenceReal(201); conflictData["final_value"] = new EvidenceReal(201); conflictData.Remove("legacy_layout");
        TraceEvent[] conflicting = [.. events.Take(4), Event("blackboard_calculation", new(conflictData)), .. events.Skip(4)];
        var shiftedHit = Change(scenario.Hits[1], "line_no", new EvidenceInteger(8));
        var rejected = new InkProvenanceStream(roots).AdvanceEvents(conflicting.Select((item, index) => (new BigInteger(index + 1), item)), [scenario.Hits[0], shiftedHit], scenario.Records);
        check(((EvidenceObject)rejected.Hits[1].Get("ink_provenance")).Get("reason") is EvidenceText { Value: "invalid_ink_ledger" },
            "Conflicting duplicate structured operations cannot authorize projectile attribution");
        TraceEvent[] legacyBinding = [.. events.Take(4), Dynamic(129, 13, 0),
            Event("actor_mapping", Obj("""{"entity_id":"8","template":"chr_0036_jsspsi","mapping_source":"launch_projectile"}""")),
            Event("skill_cast", Obj("""{"phase":"start","skill_inst_id":9,"owner_id":8,"client_tick_ms":1000,"operation_seq":131,"skill":"chr_0036_jsspsi_normal_skill_inkmark_projhit"}""")), Dynamic(132, 15, 0), events[^1]];
        var last = Change(scenario.Hits[1], "line_no", new EvidenceInteger(9));
        var bound = new InkProvenanceStream(roots).AdvanceEvents(legacyBinding.Select((item, index) => (new BigInteger(index + 1), item)), [scenario.Hits[0], last], scenario.Records);
        check(((EvidenceObject)bound.Hits[1].Get("ink_provenance")).Get("binding") is EvidenceText { Value: "legacy_typed_release_block" },
            "The historical mapping/cast release block retains its exact instance, tick and sequence requirements");

        InkObservationLog log = new();
        events[4] = events[4] with { Data = (EvidenceObject)EvidenceJson.Clone(events[4].Data) };
        foreach (var (item, index) in events.Select((item, index) => (item, index))) log.Observe(index + 1, item);
        var captured = log.Capture();
        var observation = captured.After().Single(row => row.Kind == "release");
        var releaseFields = (IDictionary<string, EvidenceValue>)((EvidenceObject)observation.Release!).Fields;
        var blocked = false;
        try { releaseFields["projectile_id"] = new EvidenceText("changed"); }
        catch (NotSupportedException) { blocked = true; }
        var callerFields = (Dictionary<string, EvidenceValue>)events[4].Data.Fields;
        callerFields["projectile_id"] = new EvidenceText("changed");
        check(blocked && EvidenceJson.PythonEquals(InkProvenanceStream.Apply(captured, scenario.Hits, scenario.Records, roots).Hits[1], expected.Hits[1]),
            "Captured structured observations reject mutation and detach nested evidence from the producer event");
    }
}
