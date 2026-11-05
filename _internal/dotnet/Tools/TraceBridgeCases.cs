using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Timing;
using System.Numerics;
using EndfieldLogs.Core.Allocation;

internal static class TraceBridgeCases
{
    public static int StructuredDamage(string inputPath, string outputPath, bool includeEntities = false)
    {
        static (HitObservationState Hits, PacketObservationState Packets, HitBuffLifecycleObservations Lifecycle,
            EntityObservationState Entities, HashSet<string> PartyIds, LoadoutObservations Loadouts, SkillObservationState Skills, BuffInstanceState Buffs, BuffPacketObservations BuffPackets, BuffDynamicObservations Dynamics, TimerObservationState Timers) Stream()
        {
            SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            PacketObservationState packets = new(); PartyObservationState party = new();
            EntityObservationState entities = new();
            HitObservationState hits = new(identities, _ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>(),
                _ => null, key => key, key => key, key => key, entities, packets, party);
            Dictionary<string, string> numbers = []; Dictionary<string, EvidenceObject> roots = [];
            BuffInstanceState buffs = new(new(roots, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers), roots, numbers, key => key, key => key, party);
            return (hits, packets, new(hits, buffs), entities, [], new(new(roots, roots, roots, new(roots), identities, key => key), identities, party), new(), buffs, new(buffs), new(buffs, _ => new("", "", "", new Dictionary<BigInteger, string>())), new(_ => null));
        }
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        var temporary = Path.Combine(Path.GetTempPath(), "endfield-structured-damage-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        List<EvidenceValue> outcomes = [];
        var count = 0;
        try
        {
            foreach (var test in cases)
            {
                var config = JsonNode.Parse(test!["config_json"]!.GetValue<string>())!;
                var root = config["resource_root"]?.GetValue<string>() ?? temporary;
                if (config["table"] is { } table)
                {
                    var tables = Path.Combine(root, "data", "local_tables"); Directory.CreateDirectory(tables);
                    File.WriteAllText(Path.Combine(tables, "NumIdStrTable.json"), table.ToJsonString());
                }
                List<EvidenceValue> events = [];
                List<TraceEvent> typedEvents = [];
                List<string> exported = [];
                List<string> fallback = [];
                void Receive(TraceEvent item)
                {
                    var restored = (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(item), header: false);
                    events.Add(TraceJsonl.ToObject(restored)); typedEvents.Add(restored);
                    exported.AddRange(TraceJsonlCases.ConnectedLines(restored, 480));
                }
                TraceBridge bridge = new(fallback.Add, new SkillResourceCatalog(new ResourceFiles(root)),
                    TimeZoneInfo.FindSystemTimeZoneById("China Standard Time"), () => 0,
                    damageSink: includeEntities ? null : Receive, eventSink: includeEntities ? Receive : null);
                foreach (var step in config["steps"]!.AsArray())
                {
                    if (step!["begin"] is { } begin) bridge.BeginCaptureSession(begin.GetValue<long>());
                    else if (step["end"] is not null) bridge.EndCaptureSession();
                    else bridge.Handle((EvidenceObject)EvidenceJson.Parse(step["event_json"]!.GetValue<string>()));
                }
                bool EntityLine(string line) => includeEntities && (line.Contains(" ENTITY_STATS ", StringComparison.Ordinal) || line.Contains(" ENTITY_ATTR_UPDATE ", StringComparison.Ordinal)
                    || line.Contains(" ENTITY_VALUE ", StringComparison.Ordinal) || line.Contains(" ENTITY_DIE ", StringComparison.Ordinal) || line.Contains(" ABILITY_ENTITY_SPAWN ", StringComparison.Ordinal));
                bool IdentityLine(string line) => includeEntities && (line.Contains(" SQUAD ", StringComparison.Ordinal) || line.Contains(" ACTOR_MAP ", StringComparison.Ordinal));
                bool SkillLine(string line) => includeEntities && line.Contains(" CHAR_SKILLS ", StringComparison.Ordinal);
                bool LoadoutLine(string line) => includeEntities && (line.Contains(" LOADOUT ", StringComparison.Ordinal) || line.Contains(" LOADOUT_STATS ", StringComparison.Ordinal));
                bool ActivityLine(string line) => includeEntities && (line.Contains(" SKILL_CAST_START ", StringComparison.Ordinal) || line.Contains(" SKILL_CAST_END ", StringComparison.Ordinal)
                    || line.Contains(" ATB_UPDATE ", StringComparison.Ordinal) || line.Contains(" POISE_V1 ", StringComparison.Ordinal));
                bool BuffLine(string line) => includeEntities && (line.Contains(" BUFF_START ", StringComparison.Ordinal)
                    || line.Contains(" BUFF_END ", StringComparison.Ordinal) || line.Contains(" BB[", StringComparison.Ordinal)
                    || line.Contains(" BUFF_CREATE_OBSERVED ", StringComparison.Ordinal) || line.Contains(" BUFF_ORIGIN ", StringComparison.Ordinal)
                    || line.Contains(" BUFF_ENABLE ", StringComparison.Ordinal) || line.Contains(" BUFF_KEYWORD_UPDATE", StringComparison.Ordinal)
                    || line.Contains(" BUFF_ACTION_UNRESOLVED ", StringComparison.Ordinal) || line.Contains(" BB_MODIFY_DYNAMIC ", StringComparison.Ordinal)
                    || line.Contains(" BUFF_ATTR_REFRESH", StringComparison.Ordinal) || line.Contains(" BB_READ_SKILL_SETTING", StringComparison.Ordinal)
                    || line.Contains(" BB_SIMPLE_CALC ", StringComparison.Ordinal) || line.Contains(" BB_MULTI_MODIFY ", StringComparison.Ordinal)
                    || line.Contains(" BB_SET_PRESET ", StringComparison.Ordinal) || line.Contains(" INK_RELEASE ", StringComparison.Ordinal));
                bool HitLine(string line) => line.Contains(" HP_V2 #", StringComparison.Ordinal);
                bool ClockLine(string line) => includeEntities && (line.Contains(" GAME_CLOCK_TICK ", StringComparison.Ordinal) || line.Contains(" GAME_CLOCK_SYNC ", StringComparison.Ordinal)
                    || line.Contains(" GAME_TIME_FREEZE_REQUEST ", StringComparison.Ordinal) || line.Contains(" GAME_TIME_FREEZE_STATE ", StringComparison.Ordinal));
                bool TimerLine(string line) => includeEntities && new[] { "GAME_TIMER_START", "GAME_TIMER_END", "GAME_TIMER_RESET", "OFFICIAL_TIMER_START", "OFFICIAL_TIMER_END", "OFFICIAL_TIMER_AWAIT", "OFFICIAL_TIMER_MISSING", "BATTLE_TIMER_MISSING", "BATTLE_PHASE_START" }
                    .Any(marker => line.Contains(" " + marker + " ", StringComparison.Ordinal));
                bool ContextLine(string line) => includeEntities && new[] { "GAME_MECHANICS_PREPARE_FINISH", "GAME_MECHANICS_REQ_START", "GAME_MECHANICS_REQ_STOP",
                    "GAME_MECHANICS_TIME_FREEZE", "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD", "GAME_INST_ENTER", "GAME_INST_LEAVE", "GAME_INST_RESTART",
                    "SCENE_BATTLE_STATE", "BATTLE_RESET_STATUS", "SESSION_WARNING" }
                    .Any(marker => line.Contains(" " + marker + " ", StringComparison.Ordinal) || line.EndsWith(" " + marker + "\n", StringComparison.Ordinal));
                bool StageLine(string line) => includeEntities && new[] { "DUNGEON_CONTEXT", "CONTRACT_TAGS", "BATTLE_RESULT" }
                    .Any(marker => line.Contains(" " + marker + " ", StringComparison.Ordinal));
                if (fallback.Any(line => ContextLine(line) || StageLine(line) || TimerLine(line) || ClockLine(line) || BuffLine(line) || ActivityLine(line) || LoadoutLine(line) || SkillLine(line) || IdentityLine(line) || EntityLine(line) || HitLine(line) || line.Contains(" PKT_", StringComparison.Ordinal)))
                    throw new InvalidDataException("Connected event family leaked to legacy sink: " + test["name"]);
                var expectedCount = test["expected"]!.AsArray().Last()!.AsArray().Count(line => HitLine(line!.GetValue<string>()) || EntityLine(line.GetValue<string>()) || IdentityLine(line.GetValue<string>()) || SkillLine(line.GetValue<string>()) || LoadoutLine(line.GetValue<string>()) || ActivityLine(line.GetValue<string>()) || BuffLine(line.GetValue<string>()) || ClockLine(line.GetValue<string>()) || TimerLine(line.GetValue<string>()) || StageLine(line.GetValue<string>()) || ContextLine(line.GetValue<string>()));
                if (events.Count != expectedCount) throw new InvalidDataException("Structured damage count differs from fixed reference: " + test["name"]);
                var expectedDamage = test["expected"]!.AsArray().Last()!.AsArray().Select(row => row!.GetValue<string>())
                    .Where(line => HitLine(line) || EntityLine(line) || IdentityLine(line) || SkillLine(line) || LoadoutLine(line) || ActivityLine(line) || BuffLine(line) || ClockLine(line) || TimerLine(line) || StageLine(line) || ContextLine(line) || line.Contains(" PKT_", StringComparison.Ordinal)).ToArray();
                if (!exported.SequenceEqual(expectedDamage)) throw new InvalidDataException("Independent damage export differs from fixed bytes: " + test["name"]);
                var oldStream = Stream(); var typedStream = Stream();
                TimerEvidenceCollector oldOfficial = new(), typedOfficial = new();
                InkObservationLog oldInk = new(), typedInk = new();
                var eventIndex = 0; long stamp = 0; var lineNumber = 0;
                foreach (var row in test["expected"]!.AsArray().Last()!.AsArray())
                {
                    lineNumber++; var line = row!.GetValue<string>();
                    var previousEvent = eventIndex;
                    if (ContextLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        ContextWire.Observation(item);
                        oldOfficial.Observe(lineNumber, line, stamp); typedOfficial.Observe(lineNumber, item);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(oldOfficial.Evidence?.ToEvidence()), FieldCases.Canonical(typedOfficial.Evidence?.ToEvidence())))
                            throw new InvalidDataException("Per-event official timer context differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (StageLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Timers.ObserveStage(line);
                        var (marker, fields, tags) = StageWire.Observation(item);
                        typedStream.Timers.ObserveStage(marker, fields, tags);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(TimerCases.Project(oldStream.Timers)), FieldCases.Canonical(TimerCases.Project(typedStream.Timers))))
                            throw new InvalidDataException("Per-event stage state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (TimerLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Timers.ObserveTimer(line, stamp);
                        var (marker, fields) = TimerWire.Observation(item);
                        typedStream.Timers.ObserveTimer(marker, fields, stamp);
                        oldOfficial.Observe(lineNumber, line, stamp); typedOfficial.Observe(lineNumber, item);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(oldOfficial.Evidence?.ToEvidence()), FieldCases.Canonical(typedOfficial.Evidence?.ToEvidence())))
                            throw new InvalidDataException("Per-event official timer evidence differs at line " + lineNumber + ": " + test["name"]);
                        if (marker == "GAME_TIMER_RESET" && fields.GetValueOrDefault("source") == "CAPTURE_SESSION_START")
                        {
                            oldStream.Entities.CriticalAttributesByActor.Clear(); typedStream.Entities.CriticalAttributesByActor.Clear();
                        }
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(TimerCases.Project(oldStream.Timers)), FieldCases.Canonical(TimerCases.Project(typedStream.Timers))))
                            throw new InvalidDataException("Per-event timer state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (ClockLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        ClockWire.Observation(item);
                    }
                    else if (IdentityLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        if (item.Type == "squad") ActorIdentity.ObserveSquad(line, oldStream.PartyIds, oldStream.Loadouts.SquadActorKeys);
                        StructuredIdentity.Accept(item, typedStream.PartyIds, typedStream.Loadouts.SquadActorKeys);
                        if (!oldStream.PartyIds.SetEquals(typedStream.PartyIds) || !oldStream.Loadouts.SquadActorKeys.SequenceEqual(typedStream.Loadouts.SquadActorKeys))
                            throw new InvalidDataException("Per-event squad state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (SkillLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Loadouts.ObserveCharacterSkills(line, lineNumber, stamp);
                        StructuredCharacterSkills.Accept(item, lineNumber, typedStream.Loadouts);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(LoadoutStateCases.Snapshot(oldStream.Loadouts)), FieldCases.Canonical(LoadoutStateCases.Snapshot(typedStream.Loadouts))))
                            throw new InvalidDataException("Per-event character skill state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (LoadoutLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Loadouts.Observe(line, lineNumber, stamp);
                        StructuredLoadout.Accept(item, lineNumber, typedStream.Loadouts);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(LoadoutStateCases.Snapshot(oldStream.Loadouts)), FieldCases.Canonical(LoadoutStateCases.Snapshot(typedStream.Loadouts))))
                            throw new InvalidDataException("Per-event loadout state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (ActivityLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        if (item.Type == "poise") oldStream.Packets.Observe(line, lineNumber, stamp);
                        else oldStream.Skills.Observe(line, lineNumber, stamp);
                        StructuredSkill.Accept(item, lineNumber, typedStream.Skills, typedStream.Packets);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(ObservationCases.Project(oldStream.Skills)), FieldCases.Canonical(ObservationCases.Project(typedStream.Skills)))
                            || !JsonNode.DeepEquals(FieldCases.Canonical(((Dictionary<string, object?>)PacketEvidenceCases.Project(oldStream.Packets))["poise_damage_events"]),
                                FieldCases.Canonical(((Dictionary<string, object?>)PacketEvidenceCases.Project(typedStream.Packets))["poise_damage_events"])))
                            throw new InvalidDataException("Per-event skill/resource state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (BuffLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        if (!oldStream.BuffPackets.Observe(line, lineNumber, stamp) && !oldStream.Dynamics.Observe(line, lineNumber, stamp) && !oldStream.Buffs.ObserveBlackboard(line)) oldStream.Buffs.ObserveLifecycle(line, lineNumber, stamp);
                        if (item.Type is "buff_start" or "buff_end" or "buff_blackboard") StructuredBuff.Accept(item, lineNumber, typedStream.Buffs);
                        else if (item.Type is "blackboard_dynamic" or "buff_attribute_refresh" or "blackboard_skill_setting") StructuredDynamic.Accept(item, lineNumber, typedStream.Dynamics);
                        else if (item.Type is "blackboard_calculation" or "blackboard_modify" or "blackboard_preset" or "ink_release") BlackboardWire.Observation(item);
                        else StructuredBuffPacket.Accept(item, lineNumber, typedStream.BuffPackets);
                        if (!JsonNode.DeepEquals(BuffInstanceCases.Snapshot(oldStream.Buffs), BuffInstanceCases.Snapshot(typedStream.Buffs)))
                            throw new InvalidDataException("Per-event BUFF state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (EntityLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Entities.Observe(line, lineNumber, stamp);
                        oldStream.PartyIds.UnionWith(ActorIdentity.PartyActorIds(line));
                        StructuredEntity.Accept(StructuredEntity.Observation(item), lineNumber, stamp, typedStream.Entities, typedStream.PartyIds);
                        if (!JsonNode.DeepEquals(FieldCases.Canonical(ObservationCases.Project(oldStream.Entities)), FieldCases.Canonical(ObservationCases.Project(typedStream.Entities)))
                            || !oldStream.PartyIds.SetEquals(typedStream.PartyIds))
                            throw new InvalidDataException("Per-event entity state differs at line " + lineNumber + ": " + test["name"]);
                    }
                    else if (HitLine(line))
                    {
                        var item = typedEvents[eventIndex++]; stamp = item.CapturedAtMs;
                        oldStream.Lifecycle.Observe(line, lineNumber, stamp);
                        EndfieldLogs.Core.Ingestion.StructuredDamage.Accept(item, lineNumber, typedStream.Lifecycle, typedStream.Packets);
                    }
                    else if (line.Contains(" PKT_", StringComparison.Ordinal)) oldStream.Packets.Observe(line, lineNumber, stamp);
                    if (eventIndex > previousEvent)
                    {
                        oldInk.Observe(lineNumber, line);
                        typedInk.Observe(lineNumber, typedEvents[previousEvent]);
                    }
                }
                static EvidenceArray InkState(InkObservationInput input) => new(input.After().Select(item => (EvidenceValue)BuffEvidence.Object(
                    ("number", new EvidenceInteger(item.Number)), ("kind", new EvidenceText(item.Kind)),
                    ("fields", new EvidenceObject(item.Fields.Where(pair => item.Kind switch
                    {
                        "cast" => pair.Key is "ownerId" or "skill" or "inst" or "seq" or "startMs",
                        "mapping" => pair.Key is "source" or "template" or "id",
                        _ => true,
                    }).ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceText(pair.Value)))),
                    ("release", item.Release ?? EvidenceNull.Value), ("identity", item.Identity ?? EvidenceNull.Value),
                    ("identity_present", new EvidenceBoolean(item.IdentityPresent)), ("invalid_identity", new EvidenceBoolean(item.InvalidIdentity)))).ToArray());
                if (!JsonNode.DeepEquals(FieldCases.Canonical(InkState(oldInk.Capture())), FieldCases.Canonical(InkState(typedInk.Capture()))))
                    throw new InvalidDataException("Structured report ink observations differ from fixed legacy inputs: " + test["name"]);
                var oldState = FieldCases.Canonical(HitObservationCases.Project(oldStream.Hits, oldStream.Packets));
                var typedState = FieldCases.Canonical(HitObservationCases.Project(typedStream.Hits, typedStream.Packets));
                if (!JsonNode.DeepEquals(oldState, typedState))
                    throw new InvalidDataException("Structured nested damage evidence differs from fixed reference: " + test["name"]);
                var oldEntities = FieldCases.Canonical(ObservationCases.Project(oldStream.Entities));
                var typedEntities = FieldCases.Canonical(ObservationCases.Project(typedStream.Entities));
                if (!JsonNode.DeepEquals(oldEntities, typedEntities) || !oldStream.PartyIds.SetEquals(typedStream.PartyIds))
                    throw new InvalidDataException("Structured entity state differs from fixed reference: " + test["name"]);
                if (!oldStream.Loadouts.SquadActorKeys.OrderBy(pair => pair.Key).SequenceEqual(typedStream.Loadouts.SquadActorKeys.OrderBy(pair => pair.Key)))
                    throw new InvalidDataException("Structured squad state differs from fixed reference: " + test["name"]);
                count += events.Count;
                Dictionary<string, EvidenceValue> outcome = new()
                { ["name"] = new EvidenceText(test["name"]!.GetValue<string>()), ["events"] = new EvidenceArray(events),
                    [includeEntities ? "legacy_observations" : "legacy_damage"] = new EvidenceArray(exported.Select(line => (EvidenceValue)new EvidenceText(line)).ToArray()) };
                if (includeEntities)
                {
                    outcome["entity_state"] = EvidenceJson.Parse(typedEntities!.ToJsonString());
                    outcome["party_actor_ids"] = new EvidenceArray(typedStream.PartyIds.Order(StringComparer.Ordinal).Select(id => (EvidenceValue)new EvidenceText(id)).ToArray());
                    outcome["squad_actor_keys"] = new EvidenceObject(typedStream.Loadouts.SquadActorKeys.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceText(pair.Value)));
                    outcome["char_skill_levels"] = EvidenceJson.Parse(FieldCases.Canonical(LoadoutStateCases.Snapshot(typedStream.Loadouts).Get("skills"))!.ToJsonString());
                    outcome["loadout_state"] = EvidenceJson.Parse(FieldCases.Canonical(LoadoutStateCases.Snapshot(typedStream.Loadouts))!.ToJsonString());
                    outcome["skill_state"] = EvidenceJson.Parse(FieldCases.Canonical(ObservationCases.Project(typedStream.Skills))!.ToJsonString());
                    outcome["poise_damage_events"] = EvidenceJson.Parse(FieldCases.Canonical(((Dictionary<string, object?>)PacketEvidenceCases.Project(typedStream.Packets))["poise_damage_events"])!.ToJsonString());
                    outcome["timer_state"] = EvidenceJson.Parse(FieldCases.Canonical(TimerCases.Project(typedStream.Timers))!.ToJsonString());
                    outcome["official_timer_evidence"] = EvidenceJson.Parse(FieldCases.Canonical(typedOfficial.Evidence?.ToEvidence())?.ToJsonString() ?? "null");
                }
                outcomes.Add(new EvidenceObject(outcome));
            }
        }
        finally { Directory.Delete(temporary, recursive: true); }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, PythonSortedJson.Serialize(new EvidenceArray(outcomes), compact: true));
        Console.WriteLine($"Structured damage producers: {cases.Count} fixed scenarios, {count} details");
        return 0;
    }

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        var temporary = Path.Combine(Path.GetTempPath(), "endfield-trace-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        JsonArray outcomes = [];
        try
        {
            foreach (var test in cases)
            {
                var config = JsonNode.Parse(test!["config_json"]!.GetValue<string>())!;
                var root = config["resource_root"]?.GetValue<string>() ?? temporary;
                if (config["table"] is { } table)
                {
                    var tables = Path.Combine(root, "data", "local_tables"); Directory.CreateDirectory(tables);
                    File.WriteAllText(Path.Combine(tables, "NumIdStrTable.json"), table.ToJsonString());
                }
                List<string> lines = []; JsonArray actual = [];
                TraceBridge bridge = new(lines.Add, new SkillResourceCatalog(new ResourceFiles(root)),
                    TimeZoneInfo.FindSystemTimeZoneById("China Standard Time"), () => 0);
                foreach (var step in config["steps"]!.AsArray())
                {
                    if (step!["begin"] is { } begin) bridge.BeginCaptureSession(begin.GetValue<long>());
                    else if (step["end"] is not null) bridge.EndCaptureSession();
                    else bridge.Handle((EvidenceObject)EvidenceJson.Parse(step["event_json"]!.GetValue<string>()));
                    actual.Add(new JsonArray(lines.Select(line => JsonValue.Create(line)).ToArray()));
                }
                outcomes.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                    ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) });
            }
        }
        finally { Directory.Delete(temporary, recursive: true); }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, outcomes.ToJsonString());
        var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Trace bridge differential: {outcomes.Count} cases, {failures} differences");
        return failures == 0 ? 0 : 1;
    }
}
