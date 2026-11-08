using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;

internal static class TraceV2Specs
{
    private static EvidenceObject Obj(string text) => (EvidenceObject)EvidenceJson.Parse(text);
    public static void Run(Action<bool, string> check)
    {
        TraceHeader header = new("v2-test", 1, null, "csharp", "test", "UTC", 0, new Dictionary<string, string>());
        var data = Obj("""{"actors":{"attacker_id":"101","target_id":"201"},"action":{"skill":"skill_template"},"evidence":{"debug":{"entity_ref":88}},"same_number":101}""");
        TraceEvent[] events = [new(1, 1000, "damage", data, Obj("""{"session_id":"捕获一","owner_id":"101","operation_seq":8}""")),
            new(2, 999, "damage", data, Obj("""{"session_id":"捕获一","owner_id":"101","operation_seq":9}""")),
            new(3, 1001, "damage", data, Obj("""{"session_id":"捕获二","owner_id":"101","operation_seq":0}"""))];
        using MemoryStream stream = new();
        using (TraceJsonlWriter writer = new(stream, header, leaveOpen: true)) foreach (var item in events) writer.Write(item);
        var wire = stream.ToArray();
        var rows = Encoding.UTF8.GetString(wire).Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(Obj).ToArray();
        var definitions = rows.Where(row => row.Get("type") is EvidenceText { Value: "definition" }).ToArray();
        check(rows[0].Get("version") is EvidenceInteger version && version.Value == 2
            && definitions.Count(row => row.Get("kind") is EvidenceText { Value: "capture_session" }) == 2
            && definitions.Count(row => row.Get("kind") is EvidenceText { Value: "entity" }) == 2
            && definitions.Count(row => row.Get("kind") is EvidenceText { Value: "template" }) == 1,
            "V2 defines each capture session, entity identity and template once per volume");
        using TraceJsonlReader reader = new(); List<TraceRecord> actual = [];
        for (var index = 0; index < wire.Length - 1; index++) actual.AddRange(reader.Feed(wire.AsSpan(index, 1)));
        check(reader.PendingBytes > 0, "V2 retains a partial UTF-8 event tail");
        actual.AddRange(reader.Feed(wire.AsSpan(wire.Length - 1)));
        check(actual.Count == 4 && actual.OfType<TraceEvent>().Select(TraceJsonl.Serialize).SequenceEqual(events.Select(TraceJsonl.Serialize)),
            "Definitions never become business events; reconnect, late timestamps and independent equal numbers survive framing");
        foreach (var invalid in new[] {
            """{"type":"definition","kind":"capture_session","ref":true,"session_id":"s"}""",
            """{"type":"definition","kind":"entity","ref":2,"id":"101"}""",
            """{"seq":1,"captured_at_ms":0,"type":"damage","source":{"session_ref":9},"data":{}}""",
            """{"seq":1,"captured_at_ms":0,"type":"damage","source":{},"data":{"entity_id":{"entity_ref":1}}}""",
            """{"seq":1,"captured_at_ms":0,"type":"damage","source":{},"data":{"legacy_layout":{}}}""" })
        {
            using TraceJsonlReader broken = new(); broken.Feed(Encoding.UTF8.GetBytes(TraceJsonl.Serialize(header)));
            try { broken.Feed(Encoding.UTF8.GetBytes(invalid + "\n")); throw new InvalidOperationException("Invalid v2 accepted"); }
            catch (InvalidDataException) { check(true, "V2 rejects invalid definitions, unresolved references and legacy layouts"); }
        }
        var source = Obj("""{"session_id":"s","owner_id":"101","operation_seq":8}""");
        var compact = TraceModel.Compact(Obj("""{"operation_seq":8,"owner_id":101,"event_owner_id":101,"observation":{"operation_seq":8,"target_id":101,"source_actor_id":true}}"""), source, 100, "buff_origin");
        var native = TraceModel.Data(new(1, 0, "buff_origin", compact, source, 100));
        check(compact.Get("owner_id") is EvidenceText { Value: "101" } && compact.Get("event_owner_id") is EvidenceText { Value: "101" }
            && ((EvidenceObject)compact.Get("observation")).Get("target_id") is EvidenceText { Value: "101" }
            && compact.Get("normalization_errors") is EvidenceArray { Items.Count: 1 }
            && ((EvidenceObject)native.Get("observation")).Get("operation_seq") is EvidenceInteger seq && seq.Value == 8
            && !((EvidenceObject)native.Get("observation")).Fields.ContainsKey("session_id")
            && !((EvidenceObject)native.Get("observation")).Fields.ContainsKey("client_tick_ms"),
            "Source compaction preserves independent owners and target facts, invalid raw evidence and actual field presence");
        var projection = TraceValueProjection.Capture(Obj("""{"entity_id":101,"template":"chr_test"}"""));
        var fields = ((EvidenceObject)projection.Value).Fields.ToDictionary(); fields["legacy_layout"] = projection.Layout;
        var old = new TraceEvent(1, 0, "actor_mapping", new(fields), Obj("{}"));
        using MemoryStream legacy = new();
        using (TraceJsonlWriter writer = new(legacy, header with { Version = 1 }, leaveOpen: true)) writer.Write(old);
        using TraceJsonlReader v1 = new(); var previous = v1.Feed(legacy.ToArray());
        check(previous[0] is TraceHeader { Version: 1 } && EvidenceJson.PythonEquals(TraceModel.Data((TraceEvent)previous[1]), Obj("""{"entity_id":"101","template":"chr_test"}"""))
            && TraceV1.ExportData(((TraceEvent)previous[1]).Data).Get("entity_id") is EvidenceInteger,
            "The v1 adapter yields the native model while independent export retains original scalar spelling");
        using MemoryStream refused = new(); using TraceJsonlWriter v2 = new(refused, header);
        try { v2.Write(old); throw new InvalidOperationException("V1 layout leaked into v2"); }
        catch (InvalidDataException) { check(true, "New recordings cannot persist old layout metadata"); }
        var typed = TraceModel.Compact(Obj("""{"tick_ms":"00042","operation_seq":"8","observation":{"client_tick_ms":"00042","generation":true},"evidence":{"debug_args":{"generation":"opaque"}}}"""), Obj("""{"operation_seq":8}"""), 42);
        check(typed.Get("tick_ms") is EvidenceInteger clock && clock.Value == 42 && !typed.Fields.ContainsKey("operation_seq")
            && ((EvidenceObject)typed.Get("observation")).Get("generation") is EvidenceNull
            && typed.Get("normalization_errors") is EvidenceArray { Items.Count: 1 }
            && ((EvidenceObject)((EvidenceObject)typed.Get("evidence")).Get("debug_args")).Get("generation") is EvidenceText { Value: "opaque" },
            "Declared integer fields have fixed types and invalid raw evidence; opaque arguments keep their values");
        var fixture = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../Specs/Fixtures/trace-v2-cross-language.jsonl"));
        using TraceJsonlReader shared = new(); var cross = shared.Feed(File.ReadAllBytes(fixture));
        var hit = (TraceEvent)cross[1]; var loadout = (TraceEvent)cross[2]; var origin = (TraceEvent)cross[3];
        check(cross[0] is TraceHeader { Version: 2 }
            && ((EvidenceObject)hit.Data.Get("amounts")).Get("value") is EvidenceReal { Value: 12345.6 }
            && EvidenceJson.PythonEquals(((EvidenceObject)hit.Data.Get("action")).Get("event_owner_id"), hit.Source.Get("owner_id"))
            && loadout.Data.Get("equip_inst_ids") is EvidenceArray { Items.Count: 1 }
            && origin.Source.Get("session_id") is EvidenceText { Value: "session-b" },
            "The shared Python-produced fixture preserves damage, independent equal owners, typed equipment and reconnect identity");
        using MemoryStream rewritten = new();
        using (TraceJsonlWriter writer = new(rewritten, (TraceHeader)cross[0], leaveOpen: true))
            foreach (var row in cross.OfType<TraceEvent>()) writer.Write(row);
        using TraceJsonlReader reread = new();
        check(reread.Feed(rewritten.ToArray()).Select(TraceJsonl.Serialize).SequenceEqual(cross.Select(TraceJsonl.Serialize)),
            "C# rewrites the shared v2 fixture without changing any native event facts");
        var damaged = TraceLoadout.Native(Obj("""{"template":"chr_test","equip_inst_ids":"{[bad-slot]=4}","equips":"damaged","equipment_snapshot_complete":true}"""));
        check(damaged.Get("invalid_fields") is EvidenceObject { Fields.Count: 2 }
            && EndfieldLogs.Core.Ingestion.LoadoutWire.Slot(damaged).EquipmentComplete is null
            && TraceLoadout.Legacy(damaged).Get("equip_inst_ids") is EvidenceText { Value: "{[bad-slot]=4}" },
            "Unparseable equipment keeps raw evidence and never becomes an authoritative empty equipment snapshot");
        var unknown = new TraceEvent(1, 1000, "entity_stats", TraceModel.Compact(
            Obj("""{"entity_id":101,"template":"chr_0001_alpha","kind":"character","attributes":[{"attr_type":9,"value":NaN},{"attr_type":10,"value":Infinity},{"attr_type":3}]}"""), Obj("{}"), null), Obj("{}"));
        using MemoryStream unknownWire = new();
        using (TraceJsonlWriter writer = new(unknownWire, header, leaveOpen: true)) writer.Write(unknown);
        using TraceJsonlReader unknownReader = new();
        var nativeStream = StructuredDamageSpecs.Stream();
        nativeStream.Accept(1, (TraceEvent)unknownReader.Feed(unknownWire.ToArray())[1]);
        var observed = nativeStream.Entities.Timelines["101"][0].Snapshot;
        check(observed.InvalidAttributeTypes.SequenceEqual(new System.Numerics.BigInteger[] { 9, 10 })
            && !observed.Attributes.ContainsKey(9) && !observed.Attributes.ContainsKey(10) && observed.Attributes[3] == 0,
            "V2 disk roundtrip keeps nonfinite attributes unknown rather than replacing them with the missing-value zero default");
        var opaque = Obj("""{"entity_id":"000101","bb":{"entity_id":true,"skill":"opaque"},"evidence":{"debug_args":{"entity_id":{"entity_ref":999},"legacy_layout":{"source_actor_id":"0007"}}}}""");
        var opaqueData = TraceModel.Compact(opaque, Obj("{}"), null);
        check(opaqueData.Get("entity_id") is EvidenceText { Value: "101" }
            && EvidenceJson.PythonEquals(opaqueData.Get("bb"), opaque.Get("bb"))
            && EvidenceJson.PythonEquals(opaqueData.Get("evidence"), opaque.Get("evidence"))
            && !opaqueData.Fields.ContainsKey("normalization_errors"),
            "Opaque blackboard and debug keys keep their own scalar meaning even when named like schema fields");
        using MemoryStream opaqueWire = new();
        using (TraceJsonlWriter writer = new(opaqueWire, header, leaveOpen: true)) writer.Write(new(1, 1000, "actor_mapping", opaqueData, Obj("{}")));
        using TraceJsonlReader opaqueReader = new();
        check(EvidenceJson.PythonEquals(((TraceEvent)opaqueReader.Feed(opaqueWire.ToArray())[1]).Data, opaqueData),
            "Opaque reference-shaped debug objects are never resolved as entity definitions");
        foreach (var stats in new[] { false, true })
        {
            try
            {
                var oldFields = Obj(stats ? """{"template":"chr_test","weapon_source_skills":"old:level=1"}""" : """{"template":"chr_test","equip_suit":"{[suit]=3}"}""");
                if (stats) _ = EndfieldLogs.Core.Ingestion.LoadoutWire.Stats(oldFields);
                else _ = EndfieldLogs.Core.Ingestion.LoadoutWire.Slot(oldFields);
                throw new InvalidOperationException("Native analysis accepted old string grammar");
            }
            catch (InvalidDataException) { check(true, "Native loadout analysis requires typed arrays; old string decoding stays in the boundary adapter"); }
        }
        var calculation = new TraceEvent(1, 1000, "blackboard_calculation", TraceModel.Compact(
            Obj("""{"key":"ink","final_value":Infinity,"value_a":NaN,"value_b":2}"""), Obj("{}"), null), Obj("{}"));
        var ink = EndfieldLogs.Core.Allocation.InkObservation.FromEvent(1, calculation);
        check(ink.Fields["final"] == "unknown" && ink.Fields["valueA"] == "unknown" && ink.Fields["valueB"] == "2.0"
            && calculation.Data.Get("final_value") is EvidenceObject status && status.Get("number_status") is EvidenceText { Value: "positive_infinity" },
            "Nonfinite calculation evidence remains explicit and cannot become a valid ink ledger value or crash native analysis");
    }
}
