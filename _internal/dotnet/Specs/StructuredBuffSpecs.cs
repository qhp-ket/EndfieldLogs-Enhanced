using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredBuffSpecs
{
    private static EvidenceObject E(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static TraceEvent Event(string type, EvidenceObject raw, long time = 1000)
    {
        var projected = TraceValueProjection.Capture(raw);
        var fields = ((EvidenceObject)projected.Value).Fields.ToDictionary(); fields["legacy_layout"] = projected.Layout;
        return new(1, time, type, new(fields), E("{}"));
    }
    private static TraceEvent Start(long uid = 71, long time = 1000, EvidenceObject? extra = null)
    {
        var fields = E("""{"buff_seq":1,"template":"buff_test","owner":"eny_0001_test","source":"chr_0001_alpha","target_id":21,"source_actor_id":11}""").Fields.ToDictionary();
        fields["buff_inst_id"] = new EvidenceInteger(uid);
        foreach (var pair in extra?.Fields ?? E("{}").Fields) fields[pair.Key] = pair.Value;
        return Event("buff_start", new(fields), time);
    }
    private static BuffInstanceState Stream()
    {
        Dictionary<string, EvidenceObject> roots = [];
        Dictionary<string, string> numbers = [];
        return new(new(roots, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers), roots, numbers, key => key, key => key);
    }
    internal static void Run(Action<bool, string> check)
    {
        var state = Stream();
        StructuredBuff.Accept(Start(), 3, state);
        var bb = Event("buff_blackboard", E("""{"buff_inst_id":71,"values":[{"key":"def_decrease","value":-0.123456789},{"key":"rate","value":0}]}"""));
        StructuredBuff.Accept(bb, 4, state);
        var first = state.Records.Single();
        check(first.BlackboardValues["def_decrease"] == -0.123457 && first.BlackboardValues["rate"] == 0,
            "Signed and zero observed BB values keep the established six-digit analysis projection");
        StructuredBuff.Accept(Start(time: 1500), 5, state);
        var second = state.Records[1];
        check(second.InstanceStartLineNumber == 3 && second.SnapshotUpdate && ReferenceEquals(second.PreviousSnapshot, first)
            && first.SnapshotEndTimestampMs == 1500 && first.SnapshotEndLineNumber == 5,
            "A repeated UID creates a snapshot boundary and retains its original instance start");
        StructuredBuff.Accept(Event("buff_blackboard", E("""{"buff_inst_id":71,"values":[{"key":"rate","value":2}]}"""), 1500), 6, state);
        check(second.BlackboardValues["rate"] == 2 && first.BlackboardValues["rate"] == 0,
            "Snapshot blackboards are independently owned");
        StructuredBuff.Accept(Event("buff_end", E("""{"buff_seq":2,"buff_inst_id":71}"""), 1200), 7, state);
        check(second.EndTimestampMs == 1200 && second.EndLineNumber == 7 && first.EndTimestampMs is null
            && state.ActiveByUid.Count == 0 && ReferenceEquals(state.PendingRecord, second),
            "End closes only the latest UID snapshot, preserving late capture time and pending-record semantics");
        foreach (var uid in new long[] { 0, uint.MaxValue })
        {
            var sentinel = Stream(); StructuredBuff.Accept(Start(uid), 1, sentinel);
            check(sentinel.Records.Single().ObservationOnly && sentinel.Records[0].Uid.Length == 0 && sentinel.ActiveByUid.Count == 0,
                "Sentinel Buff identities remain observation-only: " + uid);
        }
        var pending = Stream(); StructuredBuff.Accept(Start(), 1, pending);
        StructuredBuff.Accept(Event("buff_blackboard", E("""{"buff_inst_id":999,"values":[{"key":"rate","value":2}]}""")), 2, pending);
        check(pending.Records[0].BlackboardValues["rate"] == 2, "BB retains pending-record attachment without inventing UID rebinding");
        StructuredBuff.Accept(Start(72, extra: E("""{"owner":null,"source":null}""")), 3, pending);
        check(pending.Records.Count == 1 && pending.PendingRecord is null, "An unknown actor does not manufacture a live window");
        var wide = Start(extra: E("""{"buff_inst_id":18446744073709551615,"source_actor_id":9007199254740993}"""));
        check(wide.Data.Get("buff_inst_id") is EvidenceText { Value: "18446744073709551615" }
            && wide.Data.Get("source_actor_id") is EvidenceText { Value: "9007199254740993" }
            && BuffLegacyExporter.Lines(wide, 480).Single() == "[08:00:01.000] BUFF_START #1 id=\"buff_test\" uid=18446744073709551615 owner=eny_0001_test src=chr_0001_alpha ownerId=21 srcId=9007199254740993 dur=unknown lifeT=unknown passed=unknown enh=unknown\n",
            "Canonical wide identities and independent old-log export remain exact");
        var validation = Stream(); StructuredBuff.Accept(Start(), 1, validation);
        var rejected = false;
        try { StructuredBuff.Accept(Event("buff_blackboard", E("""{"buff_inst_id":71,"values":[{"key":"valid","value":1},{"key":"invalid","value":true}]}""")), 2, validation); }
        catch (InvalidDataException) { rejected = true; }
        check(rejected && validation.Records[0].BlackboardKeys.Count == 0, "Invalid BB data is rejected before any mutation");
        var special = E("""{"buff_inst_id":71}""").Fields.ToDictionary();
        special["values"] = new EvidenceArray([new EvidenceObject(new Dictionary<string, EvidenceValue>
            { ["key"] = new EvidenceText("rate"), ["value"] = new EvidenceReal(double.NaN) })]);
        var nonfinite = Event("buff_blackboard", new(special)); StructuredBuff.Accept(nonfinite, 3, validation);
        check(validation.Records[0].BlackboardKeys.SequenceEqual(["rate"]) && validation.Records[0].BlackboardValues.Count == 0
            && BuffLegacyExporter.Lines(nonfinite, -60).Single() == "[23:00:01.000] BB[71]: rate=nan\n",
            "Nonfinite observations retain keys and old export representation without becoming usable values");
        List<TraceEvent> events = []; List<string> fallback = [];
        TraceBridge bridge = new(fallback.Add, eventSink: events.Add);
        bridge.Handle(E("""{"type":"BattleOpAddBuff","timestamp_ms":1000,"buff_inst_id":71,"str_id":"buff_test","src_inst_id":11,"target_inst_id":21,"seq_id":7,"assigned_items":{"blackboard":{"rate":{"float_value":1.23456789}}}}"""));
        bridge.Handle(E("""{"type":"BattleOpFinishBuff","timestamp_ms":1200,"buff_inst_id":71}"""));
        check(events.Select(item => item.Type).SequenceEqual(["buff_start", "buff_blackboard", "buff_creation", "buff_end"])
            && events[0].Source.Get("operation_seq") is EvidenceInteger { Value: var sequence } && sequence == 7
            && ((EvidenceObject)((EvidenceArray)events[1].Data.Get("values")).Items[0]).Get("value") is EvidenceReal { Value: 1.23456789 },
            "Business production preserves delayed-start order, operation identity and raw BB precision");
        bridge.BeginCaptureSession(2000);
        bridge.Handle(E("""{"type":"BattleOpFinishBuff","timestamp_ms":2100,"buff_inst_id":71}"""));
        check(events[^1].Data.Get("template") is EvidenceNull && events[^1].Data.Get("buff_seq") is EvidenceInteger { Value.IsOne: true }
            && events.Select(item => item.Sequence).SequenceEqual(Enumerable.Range(1, events.Count).Select(index => (long)index)),
            "Capture reset clears Buff state while the recording event sequence remains continuous");
        bridge.Handle(E("""{"type":"BattleOpAddBuff","timestamp_ms":2200,"buff_inst_id":72}"""));
        bridge.Handle(E("""{"type":"BattleOpFinishBuff","timestamp_ms":2300,"buff_inst_id":72}"""));
        check(events[^1].Data.Get("template") is EvidenceNull && events[^1].Data.Get("template_status") is EvidenceText { Value: "unresolved" }
            && BuffLegacyExporter.Lines(events[^1], 0).Single().Contains("id=\"unknown_buff\" uid=72", StringComparison.Ordinal),
            "An unobserved template and an unresolved template stay distinct without text placeholders in the event");
        Packets(check);
        Auxiliary(check);
    }

    private static void Auxiliary(Action<bool, string> check)
    {
        var source = E("""{"inst_id":9007199254740993}""");
        var prefix = " seq=0 tick=0 inst=9007199254740993 ownerId=unknown owner=? packetSessionId=unknown skill=unknown_skill actionId=47 ";
        foreach (var (kind, values, expected) in new[]
        {
            ("blackboard_calculation", E("""{"key":"rate","final_value":-0.0,"value_a":1.234567891}"""), "BB_SIMPLE_CALC" + prefix + "key=rate final=-0.0 valueA=1.234567891"),
            ("blackboard_modify", E("""{"value":1.234567891}"""), "BB_MULTI_MODIFY" + prefix + "value=1.23457"),
            ("blackboard_preset", E("""{"modified_value":"甲 \"乙\""}"""), "BB_SET_PRESET" + prefix + "modifiedValue=\"甲 \\\"乙\\\"\""),
        })
        {
            var item = Event(kind, BlackboardWire.Data(source, 47, "?", "unknown_skill", values.Fields.Select(pair => (pair.Key, pair.Value)).ToArray()));
            item = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false);
            check(BlackboardLegacyExporter.Lines(item, 330).Single() == "[05:30:01.000] " + expected + "\n",
                "Auxiliary blackboard export preserves precision, optional fields and quoting: " + kind);
            var stream = StructuredDamageSpecs.Stream(); stream.Accept(8, item);
            check(stream.Hits.Hits.Count == 0 && stream.Buffs.Records.Count == 0 && stream.Buffs.DynamicEvents.Count == 0 && stream.LastContextMs == 1000,
                "Diagnostic blackboard actions do not create damage or effects: " + kind);
        }
        var release = Event("ink_release", BlackboardWire.ReleaseData(E("""{"schema_version":1,"template_key":"buff_test","action_id":14,"session_id":null,"operation_seq":0,"client_tick_ms":null,"buff_uid":"0007","owner_id":"None","source_actor_id":"None","projectile_id":"9007199254740993"}""")), 0);
        release = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(release), header: false);
        var observation = (EvidenceObject)release.Data.Get("observation");
        check(observation.Get("buff_inst_id") is EvidenceText { Value: "7" } && observation.Get("owner_id") is EvidenceNull
            && observation.Get("projectile_id") is EvidenceText { Value: "9007199254740993" }
            && BlackboardLegacyExporter.Lines(release, 0).Single() == "[00:00:00.000] INK_RELEASE {\"schema_version\":1,\"template_key\":\"buff_test\",\"action_id\":14,\"session_id\":null,\"operation_seq\":0,\"client_tick_ms\":null,\"buff_uid\":\"0007\",\"owner_id\":\"None\",\"source_actor_id\":\"None\",\"projectile_id\":\"9007199254740993\"}\n",
            "Ink release uses canonical decimal identities and nulls while independent export restores order and original tokens");
    }

    private static TraceEvent Packet(string kind, EvidenceObject observation) => Event(kind, BuffPacketWire.Data(observation));
    private static EvidenceObject Creation(long sequence = 1)
    {
        var fields = E("""
        {"schemaVersion":1,"buffUid":"71","buffTemplate":"buff_test","sourceActorId":"11","targetActorId":"21",
         "sessionId":"s","operationOwnerId":"21","operationGeneration":0,"generationScope":"operation_owner",
         "sourceEvent":"BattleOpAddBuff","buffId":"buff_test","assignedItems":[{"target_key":"rate","use_direct_value":true,"numeric_value":0.123456789}]}
        """).Fields.ToDictionary();
        fields["operationSeq"] = new EvidenceInteger(sequence);
        return new(fields);
    }

    private static void Packets(Action<bool, string> check)
    {
        var state = Stream(); StructuredBuff.Accept(Start(), 1, state);
        BuffPacketObservations packets = new(state);
        StructuredBuffPacket.Accept(Packet("buff_creation", Creation()), 2, packets);
        var record = state.Records[0];
        check(record.CreationObservations.Count == 1 && ((EvidenceObject)record.CreationObservations[0].Get("bb_values")).Get("rate") is EvidenceReal { Value: 0.123456789 },
            "Typed creation binds the existing instance and preserves raw assigned values");
        StructuredBuffPacket.Accept(Packet("buff_origin", E("""{"schemaVersion":1,"buffUid":"71","buffTemplate":"buff_test","sourceActorId":"11","targetActorId":"21","environmentInstId":"11","actionId":4,"operationSeq":1,"triggerType":0}""")), 3, packets);
        check(record.OriginObservations?.Single().Get("_boundCreateRecord") is EvidenceBoolean { Value: true },
            "Typed origin retains the existing identity and creation binding");
        foreach (var enabled in new[] { "true", "false" })
            StructuredBuffPacket.Accept(Packet("buff_enable", E("{\"schemaVersion\":1,\"buffUid\":\"71\",\"ownerId\":\"21\",\"operationSeq\":2,\"enabled\":" + enabled + "}")), 4, packets);
        check(record.ConflictingEnableState && record.EnableObservations.Count == 2
            && state.UnresolvedActions[^1].Get("reason") is EvidenceText { Value: "conflicting_buff_enable_state" },
            "Contradictory enable observations stay conflicting instead of selecting the latest value");
        StructuredBuffPacket.Accept(Packet("buff_creation", Creation(0)), 5, packets);
        StructuredBuffPacket.Accept(Packet("buff_creation", Creation()), 6, packets);
        check(record.CreationObservations.Count == 1 && record.RepeatedCreationObservations?.Select(row => PythonDisplay.String(row.Get("status"))).SequenceEqual(["out_of_order", "duplicate"]) == true,
            "Out-of-order and repeated creation packets preserve the established history");
        StructuredBuffPacket.Accept(Packet("buff_creation", E("""{"schemaVersion":1,"buffUid":"71","buffTemplate":"buff_test","buffId":"buff_test"}""")), 7, packets);
        check(record.CreationObservations.Count == 1 && state.UnresolvedActions[^1].Get("reason") is EvidenceText { Value: "unbound_buff_creation_observation" },
            "Missing packet identity remains unresolved");
        var ordered = Packet("buff_creation", E("""{"buffTemplate":"unknown_buff","buffUid":"9007199254740993","assignedItems":[{"numeric_value":0.123456789,"target_key":"增伤"}]}"""));
        ordered = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(ordered), header: false);
        check(((EvidenceObject)ordered.Data.Get("observation")).Get("template") is EvidenceNull
            && ordered.Data.Get("template_status") is EvidenceText { Value: "unresolved" }
            && BuffPacketLegacyExporter.Lines(ordered, 0).Single() == "[00:00:01.000] BUFF_CREATE_OBSERVED {\"buffTemplate\":\"unknown_buff\",\"buffUid\":\"9007199254740993\",\"assignedItems\":[{\"numeric_value\":0.123456789,\"target_key\":\"增伤\"}]}\n",
            "Packet JSONL roundtrip retains nested order, Unicode, wide IDs and unresolved template state");
        check(BuffPacketLegacyExporter.Lines(Packet("buff_enable", E("""{"enabled":true,"sessionId":"会话","buffUid":"71"}""")), 0).Single()
            == "[00:00:01.000] BUFF_ENABLE {\"enabled\":true,\"sessionId\":\"\\u4f1a\\u8bdd\",\"buffUid\":\"71\"}\n",
            "Enable export preserves the established ASCII JSON policy");
        foreach (var (extra, token) in new[] { ("", "unknown"), (",\"operation_seq\":null", "None"), (",\"operation_seq\":0", "0") })
        {
            var item = Event("buff_unresolved", E("{\"buff_inst_id\":71,\"action_id\":null,\"trigger_type\":null,\"target_id\":21,\"source_actor_id\":null" + extra + "}"));
            StructuredBuffPacket.Accept(item, 8, packets);
            check(state.UnresolvedActions[^1].Get("seq") is EvidenceText sequence && sequence.Value == token
                && BuffPacketLegacyExporter.Lines(item, 0).Single() == $"[00:00:01.000] BUFF_ACTION_UNRESOLVED uid=71 seq={token} triggerType=unknown actionId=None ownerId=21 srcId=None\n",
                "Unresolved actions distinguish absent, null and zero operation sequences: " + token);
        }
        KeywordPackets(check);
        DynamicPackets(check);
    }

    private static void KeywordPackets(Action<bool, string> check)
    {
        Dictionary<string, EvidenceObject> roots = new()
        {
            ["buff_chr_0023_antal_tageffect"] = E("""{"$type":"Beyond.Gameplay.Core.VulnerableAction.Data","serverActionIndex":5,"enhancingList":[{"operationType":"Add","value":{"useBlackboardKey":true,"blackboardKey":"potential_5_rate"},"buffIds":["buff_mark"]}]}"""),
        };
        Dictionary<string, string> numbers = new() { ["9"] = "buff_mark" };
        BuffInstanceState state = new(new(roots, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers), roots, numbers, key => key, key => key);
        var approved = E("""{"_rdps_whitelist_keys":["buff_chr_0023_antal_normal_fragile"],"_keyword_origin":[{"actionId":5}]}""");
        BuffPacketObservations packets = new(state, _ => approved);
        StructuredBuff.Accept(Start(), 1, state); StructuredBuffPacket.Accept(Packet("buff_creation", Creation()), 2, packets);
        TraceEvent Keyword(int sequence, string rows) => Packet("buff_keyword", E("{\"schemaVersion\":1,\"buffUid\":\"71\",\"ownerId\":\"21\",\"sessionId\":\"s\",\"generation\":0,\"addedBuffNumId\":9,\"operationPayloadCase\":\"trigger_keyword_op_data\",\"operationSeq\":" + sequence + ",\"modify\":" + rows + "}"));
        StructuredBuffPacket.Accept(Keyword(2, "[{\"configIndex\":0,\"rateAfter\":0.5}]"), 3, packets);
        var record = state.Records[0];
        check(record.KeywordRateSnapshots?.Single().Get("rate_after") is EvidenceReal { Value: 0.5 },
            "Typed keyword evidence retains approval and configured-marker requirements");
        StructuredBuffPacket.Accept(Keyword(2, "[{\"configIndex\":0,\"rateAfter\":0.7}]"), 4, packets);
        check(record.KeywordRateSnapshots?.Single().Get("status") is EvidenceText { Value: "conflicting_keyword_update" },
            "Different keyword rates for the same operation invalidate the original snapshot");
        foreach (var (sequence, rows, reason) in new[] { (3, "[[]]", "invalid_keyword_config_index"), (4, "[7]", "invalid_keyword_modify_row") })
        {
            StructuredBuffPacket.Accept(Keyword(sequence, rows), 5, packets);
            check(record.KeywordRateSnapshots?[^1].Get("status") is EvidenceText { Value: "unresolved_keyword_update" }
                && state.UnresolvedActions[^1].Get("reason") is EvidenceText text && text.Value == reason,
                "Malformed keyword rows reach the shared evidence validator: " + reason);
        }
        StructuredBuffPacket.Accept(Keyword(5, "[{\"configIndex\":0,\"rateAfter\":0.5}]"), 6, new(state));
        check(record.KeywordRateSnapshots?.Count == 3 && state.UnresolvedActions[^1].Get("reason") is EvidenceText { Value: "keyword_update_without_approved_origin" },
            "Structured keyword packets cannot bypass effect approval");
    }

    private static EvidenceObject DynamicIdentity(int sequence, bool refresh = false)
    {
        var fields = E("""{"schemaVersion":1,"sessionId":"s","operationOwnerId":"21","ownerType":1,"ownerId":"21","environmentInstId":"71","generation":0,"templateType":"Buff","templateIdCase":"str_id","templateStrId":"buff_test","templateIntId":null,"triggerType":0,"operationPayloadCase":"trigger_action_op_data"}""").Fields.ToDictionary();
        fields["operationSeq"] = new EvidenceInteger(sequence);
        fields["actionId"] = new EvidenceInteger(refresh ? 2 : 1); fields["actionType"] = new EvidenceInteger(refresh ? 31 : 7);
        fields["actionRuntimeCase"] = new EvidenceText(refresh ? "refresh_buff_attr_modifier_value_action" : "modify_dynamic_blackboard_action");
        if (refresh) fields["buffUid"] = new EvidenceText("71");
        return new(fields);
    }
    private static TraceEvent DynamicUpdate(int sequence, double value)
    {
        var source = E("""{"inst_id":71,"owner_id":21,"client_tick_tms":700}""").Fields.ToDictionary(); source["seq_id"] = new EvidenceInteger(sequence);
        return Event("blackboard_dynamic", DynamicWire.Data(new(source), new EvidenceInteger(1), value, "eny_0001_test", "buff_test", DynamicIdentity(sequence)));
    }
    private static void DynamicPackets(Action<bool, string> check)
    {
        Dictionary<string, EvidenceObject> roots = new()
        {
            ["buff_test"] = E("""
                {"actions":[{"$type":"Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data","serverActionIndex":1,"isEnable":true,"key":"rate","operation":"Add","value":{}},
                 {"$type":"Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data","serverActionIndex":2,"isEnable":true}],
                 "attributeModifier":{"attributeModifiers":[{"attributeType":"Atk","formulaItem":"Add","param":{"useBlackboardKey":true,"blackboardKey":"rate"}}]}}
                """),
        };
        Dictionary<string, string> numbers = [];
        BuffInstanceState state = new(new(roots, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers), roots, numbers, key => key, key => key);
        BuffDynamicObservations dynamics = new(state, _ => new("", "", "", new Dictionary<System.Numerics.BigInteger, string>()));
        StructuredBuff.Accept(Start(), 1, state); StructuredBuffPacket.Accept(Packet("buff_creation", Creation()), 2, new(state));
        StructuredDynamic.Accept(DynamicUpdate(2, 0.5), 3, dynamics);
        var record = state.Records[0];
        check(record.DynamicState?.Values.GetValueOrDefault("rate") == 0.5 && record.AttributeRefreshSnapshots.Count == 0 && record.BlackboardValues.Count == 0
            && state.DynamicEvents[^1].Get("state_status") is EvidenceText { Value: "pending_attribute_refresh" },
            "Typed runtime results remain pending and do not directly replace the live Buff values");
        StructuredDynamic.Accept(Packet("buff_attribute_refresh", DynamicIdentity(3, refresh: true)), 4, dynamics);
        var saved = record.AttributeRefreshSnapshots.Single();
        check(saved.Get("status") is EvidenceText { Value: "attribute_parameters_observed" }
            && ((EvidenceObject)saved.Get("bb_values")).Get("rate") is EvidenceReal { Value: 0.5 }
            && saved.Get("final_modifiers_verified") is EvidenceBoolean { Value: false },
            "Only an explicit compatible refresh emits an observed parameter snapshot");
        StructuredDynamic.Accept(DynamicUpdate(2, 0.7), 5, dynamics);
        check(saved.Get("status") is EvidenceText { Value: "conflicting_dynamic_operation" }
            && state.DynamicEvents[^1].Get("state_error") is EvidenceText { Value: "conflicting_dynamic_operation_order" },
            "Late conflicting runtime evidence invalidates the already published snapshot");
        var count = state.DynamicEvents.Count;
        StructuredDynamic.Accept(Packet("blackboard_skill_setting", E("""{"runtime":{},"actionSerialization":null,"validationErrors":["invalid_skill_setting_runtime"]}""")), 6, dynamics);
        check(state.DynamicEvents.Count == count && state.AttributeRefreshEvents.Count == 1,
            "Skill-setting packets remain diagnostic and cannot manufacture a refresh");
        var ordered = Event("blackboard_dynamic", DynamicWire.Data(E("""{"seq_id":0,"inst_id":71}"""), new EvidenceInteger(1), -0.0, "?", "unknown_skill",
            E("""{"schemaVersion":1,"eventContext":{"seq_id":0,"inst_id":71}}""")));
        ordered = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(ordered), header: false);
        check(DynamicLegacyExporter.Lines(ordered, 0).Single() == "[00:00:01.000] BB_MODIFY_DYNAMIC seq=0 tick=0 inst=71 ownerId=unknown owner=? packetSessionId=unknown skill=unknown_skill actionId=1 value=-0.0 identity={\"schemaVersion\":1,\"eventContext\":{\"seq_id\":0,\"inst_id\":71}}\n",
            "Dynamic export preserves nested proof order, absent fields, zero and signed zero");
        var unbound = Stream(); StructuredBuff.Accept(Start(), 1, unbound);
        StructuredDynamic.Accept(DynamicUpdate(2, 0.5), 2, new(unbound, _ => new("", "", "", new Dictionary<System.Numerics.BigInteger, string>())));
        check(unbound.DynamicEvents[^1].Get("state_error") is EvidenceText { Value: "missing_compatible_buff_creation_observation" },
            "A matching UID alone cannot bind runtime state without a creation anchor");
    }
}
