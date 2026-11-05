using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredEntitySpecs
{
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static TraceEvent Event(string rows, bool partial = false, long timestamp = 1793412000123)
    {
        var data = E("""{"entity_id":9007199254740993,"template":"chr_0001_alpha","level":80,"attributes":[]} """);
        var fields = (Dictionary<string, EvidenceValue>)data.Fields;
        if (!partial) fields["kind"] = new EvidenceText("character");
        fields["attributes"] = EvidenceJson.Parse(rows);
        var projection = TraceValueProjection.Capture(data);
        var projected = ((EvidenceObject)projection.Value).Fields.ToDictionary(); projected["legacy_layout"] = projection.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, timestamp,
            partial ? "entity_attributes" : "entity_stats", new(projected), E("{}"))), header: false);
    }

    public static void Run(Action<bool, string> check)
    {
        const string id = "9007199254740993";
        var full = Event("""[{"attr_type":9,"value":0.123456789,"basic_value":0.12},{"attr_type":10,"value":0.5},{"attr_type":3,"value":100}]""");
        var stream = StructuredDamageSpecs.Stream(); stream.Accept(4, full);
        var snapshot = stream.Entities.Timelines[id].Single().Snapshot;
        check(snapshot.Attributes[9] == 0.123457 && snapshot.BasicAttributes[9] == 0.12 && snapshot.Level == 80
            && stream.PartyActorIds.SetEquals([id]), "Typed entity preserves full snapshot and party identity with the established six-digit projection");
        var update = Event("""[{"attr_type":9,"value":0.25},{"attr_type":3,"value":200}]""", true, full.CapturedAtMs - 1);
        stream.Accept(new[] { (5, update) });
        check(stream.Entities.Timelines[id].Count == 1 && snapshot.Attributes[3] == 100
            && stream.Entities.CriticalAttributesByActor[id].Values[9] == 0.25
            && stream.Entities.CriticalAttributesByActor[id].Values[10] == 0.5
            && stream.Entities.CriticalAttributesByActor[id].Times[9] == full.CapturedAtMs - 1
            && stream.LastContextMs == full.CapturedAtMs - 1, "Partial attributes update critical evidence without replacing the full timeline and retain late time");
        stream.Accept(6, Event("""[{"attr_type":9,"value":1},{"attr_type":9,"value":2},{"attr_type":9,"value":3}]""", true));
        check(!stream.Entities.CriticalAttributesByActor[id].Values.ContainsKey(9)
            && stream.Entities.CriticalAttributesByActor[id].Values[10] == 0.5, "Duplicate entity attributes remain invalid after later repetitions");
        var changed = Event("[]", true); var changedFields = changed.Data.Fields.ToDictionary();
        changedFields["template"] = new EvidenceText("chr_0002_beta"); changed = changed with { Data = new(changedFields) };
        stream.Accept(7, changed);
        check(!stream.Entities.CriticalAttributesByActor.ContainsKey(id), "A partial observation with different identity clears prior critical evidence");
        var unknown = Event("""[{"attr_type":9,"value":NaN},{"attr_type":10,"value":Infinity},{"attr_type":3,"value":-0.0},{"attr_type":4},{"value":99},{"attr_type":5,"value":1,"basic_value":-Infinity}]""", timestamp: -1);
        var unknownStream = StructuredDamageSpecs.Stream(); unknownStream.Accept(1, unknown);
        var observed = unknownStream.Entities.Timelines[id][0].Snapshot;
        check(observed.InvalidAttributeTypes.SequenceEqual(new System.Numerics.BigInteger[] { 9, 10 })
            && observed.Attributes[4] == 0 && !observed.BasicAttributes.ContainsKey(5)
            && double.IsNegative(observed.Attributes[3]), "Nonfinite attributes remain invalid, missing values follow producer defaults, and signed zero survives");
        check(EntityLegacyExporter.Lines(unknown, 330).SequenceEqual(new[] {
            "[05:29:59.999] ENTITY_STATS id=9007199254740993 template=chr_0001_alpha kind=character level=80 hp=unknown attrs=[9:nan/nan 10:inf/inf 3:-0/-0 4:0/0 5:1/-inf]\n" }),
            "Independent entity export restores unknown values, pre-epoch time, timezone, precision and LF");
        foreach (var mutation in new[] { "numeric-id", "missing-id", "label" })
        {
            var invalid = Event("[]"); var fields = invalid.Data.Fields.ToDictionary();
            if (mutation == "numeric-id") fields["entity_id"] = new EvidenceInteger(11);
            else if (mutation == "missing-id") fields.Remove("entity_id");
            else fields["template"] = new EvidenceArray([]);
            invalid = invalid with { Data = new(fields) };
            var untouched = StructuredDamageSpecs.Stream();
            try { untouched.Accept(1, invalid); throw new InvalidOperationException("Invalid entity accepted"); }
            catch (InvalidDataException)
            { check(untouched.Entities.Timelines.Count == 0 && untouched.PartyActorIds.Count == 0 && untouched.FirstContextMs is null, "Malformed entity rejected before stream mutation"); }
        }
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Typed entity emitted text"), eventSink: events.Add);
        var source = E("""{"type":"SC_SELF_SCENE_INFO","timestamp_ms":1793412000123,"session_id":"合成","seq_id":7,"generation":0,"operation_owner_id":11,"client_tick_tms":0,"char_list":[{"battle_inst_id":9007199254740993,"templateid":"chr_0001_alpha","attrs":[{"attr_type":9,"value":0.123456789}]}]}""");
        bridge.Handle(source);
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)((EvidenceObject)((EvidenceArray)source.Get("char_list")).Items[0]).Get("attrs")).Items[0]).Fields)["value"] = new EvidenceInteger(99);
        check(((EvidenceObject)((EvidenceArray)events[0].Data.Get("attributes")).Items[0]).Get("value") is EvidenceReal { Value: 0.123456789 }
            && events[0].Data.Get("entity_id") is EvidenceText { Value: id } && events[0].ClientTickMs == 0,
            "Business entity production owns nested evidence, normalizes wide identity, and retains observed zero clock");
        bridge.Handle(E("""{"type":"SC_SYNC_ATTR","timestamp_ms":1793412000122,"battle_inst_id":9007199254740993,"obj_id":0,"attrs":[{"attr_type":9,"value":0.25}]}"""));
        check(events.Select(item => item.Sequence).SequenceEqual(new long[] { 1, 2 })
            && events[1].Data.Get("object_id") is EvidenceText { Value: "0" }
            && events[1].Data.Get("template") is EvidenceText { Value: "chr_0001_alpha" }, "Connected entity families share sequence, known mapping and explicit zero object identity");
        try { _ = new TraceBridge(_ => { }, damageSink: _ => { }, eventSink: _ => { }); throw new InvalidOperationException("Ambiguous destination accepted"); }
        catch (ArgumentException) { check(true, "Partial structured destinations cannot compete"); }
        Diagnostics(check);
    }

    private static void Diagnostics(Action<bool, string> check)
    {
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Structured diagnostic emitted text"), eventSink: events.Add);
        bridge.Handle(E("""{"type":"BattleOpEntityValueModify","timestamp_ms":-1,"entity_inst_id":"0007","seq_id":null,"scene_num_id":0,"hp":Infinity,"delta_value":-0.0,"template_int_id":0}"""));
        bridge.Handle(E("""{"type":"BattleOpEntityDie","timestamp_ms":-1,"entity_inst_id":"0007"}"""));
        bridge.Handle(E("""{"type":"BattleOpEntityDie","timestamp_ms":-1}"""));
        var spawn = E("""{"type":"BattleOpTriggerAction","timestamp_ms":-1,"seq_id":0,"client_tick_tms":0,"inst_id":0,"owner_id":"0007","action":{"action_type":"BattleActionSpawnAbilityEntity","action_id":4,"spawn_ability_entity_action":{"details":[null,{"source_id":0,"client_ability_entity_id":9007199254740993,"init_pos":{"x":1.23456789,"y":null,"z":-0.0},"rotation":{"x":Infinity}},{}]}}}""");
        bridge.Handle(spawn);
        var originalPosition = (EvidenceObject)((EvidenceObject)((EvidenceArray)((EvidenceObject)((EvidenceObject)spawn.Get("action")).Get("spawn_ability_entity_action")).Get("details")).Items[1]).Get("init_pos");
        ((Dictionary<string, EvidenceValue>)originalPosition.Fields)["x"] = new EvidenceInteger(99);
        events = events.Select(item => (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false)).ToList();
        check(events.Select(item => item.Type).SequenceEqual(new[] { "entity_value", "entity_die", "entity_die", "ability_spawn", "ability_spawn" })
            && events.Select(item => item.Sequence).SequenceEqual(new long[] { 1, 2, 3, 4, 5 }), "Entity diagnostics share ordered sequence and skip invalid spawn detail rows");
        check(events[0].Data.Get("entity_id") is EvidenceText { Value: "7" } && !events[0].Data.Fields.ContainsKey("ultimate_sp")
            && !events[2].Data.Fields.ContainsKey("entity_id") && ((EvidenceObject)events[3].Data.Get("detail")).Get("source_actor_id") is EvidenceText { Value: "0" },
            "Diagnostics preserve missing fields, zero source identity and canonical instance strings");
        check(((EvidenceObject)((EvidenceObject)events[3].Data.Get("detail")).Get("position")).Get("x") is EvidenceReal { Value: 1.23456789 }
            && events[4].Data.Get("detail") is EvidenceObject { Fields.Count: 0 }, "Spawn vectors retain precision and caller isolation without filling missing coordinates");
        check(events.SelectMany(item => EntityLegacyExporter.Lines(item, 0)).SequenceEqual(new[] {
            "[23:59:59.999] ENTITY_VALUE seq=None id=7 scene=0 hp=inf ult=unknown delta=-0.0 srcType=unknown srcInt=0 origSrcType=unknown origSrcInt=unknown\n",
            "[23:59:59.999] ENTITY_DIE id=0007\n", "[23:59:59.999] ENTITY_DIE id=None\n",
            "[23:59:59.999] ABILITY_ENTITY_SPAWN seq=0 tick=0 actionId=4 inst=0 skill=unknown_skill templateIntId=unknown ownerId=7 owner=id_7 sourceId=7 source=id_7 entityId=9007199254740993 pos=1.23456789,unknown,-0.0 rot=inf,unknown,unknown\n",
            "[23:59:59.999] ABILITY_ENTITY_SPAWN seq=0 tick=0 actionId=4 inst=0 skill=unknown_skill templateIntId=unknown ownerId=7 owner=id_7 sourceId=7 source=id_7 entityId=unknown pos=unknown,unknown,unknown rot=unknown,unknown,unknown\n" }),
            "Independent entity export restores raw death identity, unknowns, negative zero, nonfinite vectors and source fallback");
        var stream = StructuredDamageSpecs.Stream();
        stream.Accept(events.Select((item, index) => (index + 1, item)));
        check(stream.LastContextMs == -1 && stream.Entities.Timelines.Count == 0 && stream.Entities.CriticalAttributesByActor.Count == 0
            && stream.PartyActorIds.Count == 0 && stream.Hits.Hits.Count == 0, "Diagnostics update context time without inferring attributes, party membership or hits");
        foreach (var (kind, data) in new[] { ("entity_die", """{"entity_id":7}"""), ("entity_value", """{"entity_id":"-1"}"""), ("ability_spawn", """{"detail":{"source_actor_id":1}}""") })
        {
            var clean = StructuredDamageSpecs.Stream();
            try { clean.Accept(1, new TraceEvent(1, 0, kind, E(data), E("{}"))); throw new InvalidOperationException("Invalid diagnostic accepted"); }
            catch (InvalidDataException) { check(clean.FirstContextMs is null && clean.PartyActorIds.Count == 0, "Invalid diagnostic rejected before state mutation"); }
        }
    }
}
