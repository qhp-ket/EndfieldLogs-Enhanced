using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredDamageSpecs
{
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    internal static BattleIngestionStream Stream()
    {
        SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
        Dictionary<string, EvidenceObject> objects = []; Dictionary<string, string> numbers = [];
        return new(new()
        {
            Identities = identities, BuffMappings = new(objects, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers),
            BuffRoots = objects, BuffNumbers = numbers, Loadouts = new(objects, objects, objects, new(objects), identities, key => key),
            Metadata = _ => new("", "", "", new Dictionary<BigInteger, string>(), false),
            DamageUnits = _ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>(),
            SkillProfile = _ => null, CharacterName = key => key, EnemyName = key => key, SkillName = key => key, Dungeon = _ => null,
        });
    }
    private static TraceEvent Event() => new(1, 1793412000123, "damage", E("""
        {"hit_seq":1,"actors":{"attacker":"chr_0001_alpha","target":"eny_0001_target","attacker_id":"11","target_id":"22"},
         "action":{"skill":"skill_test","part_inst_id":"9007199254740993","action_id":14,"damage_unit_index":0},
         "amounts":{"value":-123.45678901234567,"current_hp":900.5,"is_crit":false},
         "blackboards":{"dynamic":[{"action_id":14,"value":1.23456789}],"calculation":[{"action_id":14,"key":"scale","value":2.123456789}]},
         "evidence":{"modifier_args":{"attacker_modifiers":[{"index":0,"buff_inst_id":"99","debug_args":{"scale":[0.5]}}],"defender_modifiers":[]},
          "battle_report_info":{"attacker_attr_modify_info":[{"attr_type":9,"attrs":[0.25]}]},
          "presence":{"has_battle_report_info":false,"has_calculation_check_args":true},
          "packet_context":{"packetSeq":7,"packetSessionId":"合成"}}}
        """), E("""{"owner_id":"18446744073709551615","session_id":"合成","operation_seq":7,"generation":0,"action_id":14,"detail_index":0} """), 0);

    public static void Run(Action<bool, string> check)
    {
        var item = Event(); var stream = Stream(); stream.Accept(4, item);
        var hit = stream.Hits.Hits.Single();
        check(hit.Amounts.Value == 123 && hit.Amounts.PacketRaw == 123.46 && hit.Amounts.PacketFinal == 123.45678901234567
            && hit.Amounts.EnemyHpAfter == 900 && hit.Action.PartInstance == BigInteger.Parse("9007199254740993"),
            "Structured damage preserves original precision while applying the established analysis projection");
        check(hit.Blackboards.Dynamic[14] == 1.23457 && hit.Blackboards.Calculation[14]["scale"] is EvidenceReal { Value: 2.12346 },
            "Blackboard analysis uses the established six-digit projection without reparsing a trace row");
        check(hit.Packet.AttributeReportPresent == false && hit.Packet.Attributes!.Attacker.SequenceEqual(new[] { "9:0.25" })
            && hit.Packet.ModifierHandles!.Get("attacker") is EvidenceArray { Items.Count: 1 },
            "Nested presence, attributes and modifier processor handles enter the actual hit evidence");
        var modifierArgs = (EvidenceObject)((EvidenceObject)item.Data.Get("evidence")).Get("modifier_args");
        var handles = (EvidenceArray)modifierArgs.Get("attacker_modifiers");
        var callerHandle = (EvidenceObject)handles.Items[0];
        ((Dictionary<string, EvidenceValue>)callerHandle.Fields)["debug_args"] = E("""{"scale":[9]}""");
        var accepted = (EvidenceObject)((EvidenceArray)hit.Packet.ModifierHandles!.Get("attacker")).Items[0];
        check(!EvidenceJson.PythonEquals(accepted.Get("debug_args"), callerHandle.Get("debug_args")),
            "Accepted nested modifier evidence owns its containers independently of the event caller");
        check(stream.FirstContextMs == item.CapturedAtMs && stream.LastContextMs == item.CapturedAtMs && hit.Action.ClientTick == 0,
            "Structured ingestion retains full capture instants and observed zero game clocks");
        stream.Accept(5, Event() with { Sequence = 2, CapturedAtMs = item.CapturedAtMs - 1 });
        check(stream.LastContextMs == item.CapturedAtMs - 1 && stream.Hits.Hits.Count == 2,
            "Late structured observations keep their actual capture timestamp");
        foreach (var mutation in new[] { "numeric-id", "missing-value", "bad-blackboards" })
        {
            var invalid = Event(); var untouched = Stream();
            if (mutation == "numeric-id") ((Dictionary<string, EvidenceValue>)((EvidenceObject)invalid.Data.Get("actors")).Fields)["attacker_id"] = new EvidenceInteger(11);
            else if (mutation == "missing-value") ((Dictionary<string, EvidenceValue>)((EvidenceObject)invalid.Data.Get("amounts")).Fields).Remove("value");
            else ((Dictionary<string, EvidenceValue>)((EvidenceObject)invalid.Data.Get("blackboards")).Fields)["dynamic"] = new EvidenceArray([new EvidenceInteger(7)]);
            try { untouched.Accept(1, invalid); throw new InvalidOperationException("Invalid damage was accepted"); }
            catch (InvalidDataException)
            {
                check(untouched.Hits.Hits.Count == 0 && untouched.FirstContextMs is null,
                    "Malformed structured damage is rejected before stream state changes");
            }
        }
        var unsupported = Stream();
        try { unsupported.Accept(1, Event() with { Type = "future_event" }); throw new InvalidOperationException("Unknown family disappeared"); }
        catch (NotSupportedException) { check(unsupported.FirstContextMs is null, "Unconnected structured families are explicit failures"); }
        Export(check);
    }

    private static void Export(Action<bool, string> check)
    {
        var original = E("""
            {"modifier_args":{"attacker_modifiers":[
                {"index":0,"buff_inst_id":18446744073709551615,"debug_args":{"z":-0.0,"a":[1,null]}},
                {"buff_inst_id":"00099"},{"buff_inst_id":-3},{"buff_inst_id":"unknown"},
                {"buff_inst_id":1.5},{"buff_inst_id":true},{"buff_inst_id":null}],"defender_modifiers":[]}}
            """);
        var captured = TraceValueProjection.Capture(original);
        var wire = new TraceEvent(1, 0, "damage", new(new Dictionary<string, EvidenceValue>
            { ["value"] = captured.Value, ["layout"] = captured.Layout }), E("{}"));
        var saved = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(wire), header: false);
        var projected = (EvidenceArray)((EvidenceObject)((EvidenceObject)saved.Data.Get("value")).Get("modifier_args")).Get("attacker_modifiers");
        check(EvidenceJson.PythonEquals(((EvidenceObject)projected.Items[0]).Get("buff_inst_id"), new EvidenceText("18446744073709551615"))
            && EvidenceJson.PythonEquals(((EvidenceObject)projected.Items[1]).Get("buff_inst_id"), new EvidenceText("99"))
            && ((EvidenceObject)projected.Items[2]).Get("buff_inst_id") is EvidenceNull,
            "Nested instance IDs normalize to decimal strings while invalid originals remain unresolved");
        var restored = (EvidenceObject)TraceValueProjection.Restore(saved.Data.Get("value"), (EvidenceObject)saved.Data.Get("layout"));
        var restoredHandles = (EvidenceArray)((EvidenceObject)restored.Get("modifier_args")).Get("attacker_modifiers");
        var first = (EvidenceObject)restoredHandles.Items[0];
        check(EvidenceJson.PythonEquals(restored, original) && first.Fields.Keys.SequenceEqual(new[] { "index", "buff_inst_id", "debug_args" })
            && ((EvidenceObject)first.Get("debug_args")).Fields.Keys.SequenceEqual(new[] { "z", "a" })
            && ((EvidenceObject)restoredHandles.Items[4]).Get("buff_inst_id") is EvidenceReal
            && ((EvidenceObject)restoredHandles.Items[5]).Get("buff_inst_id") is EvidenceBoolean,
            "Disk-roundtripped export metadata restores original key order and scalar representations");
        var callerHandle = (EvidenceObject)((EvidenceArray)((EvidenceObject)original.Get("modifier_args")).Get("attacker_modifiers")).Items[0];
        ((Dictionary<string, EvidenceValue>)callerHandle.Fields)["debug_args"] = E("{\"changed\":true}");
        check(!EvidenceJson.PythonEquals(original, TraceValueProjection.Restore(captured.Value, captured.Layout)),
            "Projection owns nested containers without requiring an earlier full evidence clone");
        foreach (var number in new[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity })
        {
            var value = TraceValueProjection.Capture(new EvidenceReal(number));
            var eventData = new EvidenceObject(new Dictionary<string, EvidenceValue> { ["value"] = value.Value, ["layout"] = value.Layout });
            var roundtrip = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(wire with { Data = eventData }), header: false);
            var actual = (EvidenceReal)TraceValueProjection.Restore(roundtrip.Data.Get("value"), (EvidenceObject)roundtrip.Data.Get("layout"));
            check(double.IsNaN(number) ? double.IsNaN(actual.Value) : actual.Value == number,
                "Non-finite evidence uses an explicit JSON status without non-standard numeric tokens");
        }
        foreach (var keys in new[] { "[\"a\"]", "[\"a\",\"a\"]", "[\"a\",\"other\"]" })
        {
            try { TraceValueProjection.Restore(E("{\"a\":1,\"b\":2}"), E("{\"keys\":" + keys + "}")); throw new InvalidOperationException("Invalid order accepted"); }
            catch (InvalidDataException) { check(true, "Legacy layout cannot silently omit or duplicate evidence keys"); }
        }
        var minimal = E("""
            {"hit_seq":4,"actors":{"attacker":"chr_alpha","target":"?"},"action":{"skill":"技能"},
             "amounts":{"value":-12.5,"current_hp":-0.0},"blackboards":{"dynamic":[],"calculation":[]},
             "evidence":{"packet_context":{"packetSeq":null,"packetSessionId":null},"presence":{}}}
            """);
        var projection = TraceValueProjection.Capture(minimal);
        var fields = ((EvidenceObject)projection.Value).Fields.ToDictionary(); fields["legacy_layout"] = projection.Layout;
        var item = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, -1, "damage", new(fields), E("{}"))), header: false);
        var expected = "[05:29:59.999] HP_V2 #4 hit=13 cum=13 raw=12.50 packetFinalValue=12.5 pHP=0 eHP=0 skill=\"技能\" hits=1 " +
            "skillLv=unknown templateIntId=unknown templateType=unknown actionId=unknown origTemplateIntId=unknown " +
            "damageUnitIndex=unknown partInstId=unknown dynBB=unknown calcBB=unknown src=chr_alpha tgt=? atk=chr_alpha " +
            "atkId=unknown tgtId=unknown seg=0 shared=2 critFlag=0 critDmg=-1.0000 eventInstId=unknown eventOwnerId=unknown " +
            "packetSeq=unknown clientTick=unknown \n";
        check(DamageLegacyExporter.Lines(item, 330).SequenceEqual(new[] { expected }),
            "Independent export preserves timezone, pre-epoch milliseconds, rounding, placeholders, spacing and LF");
    }
}
