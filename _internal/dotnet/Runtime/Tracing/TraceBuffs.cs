using EndfieldLogs.Core.Ingestion;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private void FlushAdds()
    {
        if (pendingAdd.Count > 0)
        {
            var ts = addTs ?? lastTs ?? Now();
            foreach (var e in pendingAdd)
            {
                if (Id(e.Get("buff_inst_id")) is not { } uid) continue;
                var target = Int(e.Get("target_inst_id")); var src = Int(e.Get("src_inst_id"));
                StartBuff(ts, ResolveBuff(e.Get("str_id"), e.Get("int_id")), uid, Name(target), Name(src), e.Get("assigned_items"), target, src, e);
            }
        }
        pendingAdd.Clear(); addTs = null;
    }
    private void FlushCreates()
    {
        if (pendingCreate.Count > 0)
        {
            var ts = createTs ?? lastTs ?? throw new InvalidDataException("Pending create action has no timestamp");
            foreach (var e in pendingCreate) CreateBuffs(e, Obj(e.Get("action")).Get("create_buff_action"), ts);
        }
        pendingCreate.Clear(); createTs = null;
    }
    private bool PreferBuff(string previous, string next)
    {
        if (previous == next) return false;
        if (Digits(previous) && identities?.Buffs.GetValueOrDefault(previous) is { Length: > 0 } known && known != next) return false;
        static bool Canonical(string text) => text.Length > 0 && text != "unknown_buff" && !Digits(text);
        if (Canonical(next) && !Canonical(previous)) return true;
        if (Canonical(previous) && !Canonical(next)) return false;
        if (next == "unknown_buff" && previous != "unknown_buff") return false;
        return true;
    }
    private static Dictionary<string, double> AssignedValues(EvidenceValue assigned)
    {
        if (assigned is EvidenceObject) return Blackboard(assigned);
        Dictionary<string, double> result = new(StringComparer.Ordinal);
        foreach (var row in Rows(assigned))
        {
            var key = Text(row.Get("target_key"), Text(row.Get("input_value_key"), Text(row.Get("targetKey"), Text(row.Get("inputValueKey")))));
            if (key.Length > 0 && Float(row.Get("numeric_value")) is { } value) result[key] = value;
        }
        return result;
    }
    private static HashSet<string> AssignedKeys(EvidenceValue assigned) => assigned is EvidenceObject obj
        ? Obj(obj.Get("blackboard")).Fields.Keys.Where(key => key.Length > 0).ToHashSet(StringComparer.Ordinal)
        : Rows(assigned).Select(row => Text(row.Get("target_key"), Text(row.Get("input_value_key"), Text(row.Get("targetKey"), Text(row.Get("inputValueKey")))))).Where(key => key.Length > 0).ToHashSet(StringComparer.Ordinal);
    private void StartBuff(long ts, string buff, BigInteger uid, string owner, string src, EvidenceValue assigned,
        BigInteger? targetId, BigInteger? srcId, EvidenceObject e, EvidenceObject? detail = null)
    {
        if (targetId is not null || srcId is not null) buffActors[uid] = (targetId, srcId);
        var previous = buffIds.GetValueOrDefault(uid) ?? "";
        if (previous.Length > 0 && previous != buff && !PreferBuff(previous, buff)) buff = previous;
        var values = AssignedValues(assigned); var keys = AssignedKeys(assigned);
        var unchanged = previous.Length > 0 && previous == buff;
        var previousValues = buffValues.GetValueOrDefault(uid) ?? new(StringComparer.Ordinal);
        var additional = values.Any(pair => !previousValues.TryGetValue(pair.Key, out var existing) || existing != pair.Value);
        if (unchanged)
        {
            var merged = new Dictionary<string, double>(previousValues, StringComparer.Ordinal);
            foreach (var pair in values) merged[pair.Key] = pair.Value;
            values = merged; keys.UnionWith(buffKeys.GetValueOrDefault(uid) ?? []);
        }
        buffIds[uid] = buff; buffValues[uid] = values; buffKeys[uid] = keys;
        if (!unchanged || additional)
        {
            if (startTs is not null && startTs != ts) FlushStarts(); startTs = ts;
            if (!pendingStarts.TryGetValue(uid, out var pending) || PreferBuff(pending.Buff, buff)) pendingStarts[uid] = (buff, owner, src, assigned, e);
        }
        var observation = Make(("schemaVersion", 1), ("buffUid", I(uid)), ("buffTemplate", buff),
            ("sourceActorId", srcId is null ? null : I(srcId)), ("targetActorId", targetId is null ? null : I(targetId)),
            ("sessionId", e.Get("session_id")), ("operationSeq", e.Get("seq_id")),
            ("operationOwnerId", e.Get("operation_owner_id") is EvidenceInteger or EvidenceText ? S(e.Get("operation_owner_id")) : e.Get("operation_owner_id")),
            ("operationGeneration", e.Get("generation")), ("generationScope", "operation_owner"), ("sourceEvent", e.Get("type")),
            ("buffNumId", detail?.Get("buff_num_id") ?? e.Get("int_id")), ("buffId", detail?.Get("buff_id") ?? e.Get("str_id")),
            ("buffTemplateId", e.Get("buff_template_id")), ("assignedItems", detail is not null ? detail.Get("assigned_items") : assigned is EvidenceArray ? assigned : null),
            ("isNewInstance", null), ("priorUidObserved", previous.Length > 0), ("observationKind", "creation_or_refresh"), ("enhanceMultiplier", null));
        if (detail is not null)
        {
            var fields = (Dictionary<string, EvidenceValue>)observation.Fields;
            fields["actionId"] = Obj(e.Get("action")).Get("action_id"); fields["triggerType"] = e.Get("trigger_type");
            fields["creationActionType"] = Obj(e.Get("action")).Get("action_type"); fields["creationActionRuntimeCase"] = e.Get("action_runtime_case");
        }
        if (eventOutput is not null) EmitStructured(ts, "buff_creation", BuffPacketWire.Data(observation), e);
        else Line(ts, "BUFF_CREATE_OBSERVED " + Json(observation, finite: true));
    }
    private void FlushStarts()
    {
        if (pendingStarts.Count == 0) { startTs = null; return; }
        var ts = startTs ?? throw new InvalidDataException("Pending Buff starts have no timestamp");
        foreach (var (uid, row) in pendingStarts)
        {
            var (owner, src) = buffActors.GetValueOrDefault(uid);
            buffSeq++;
            var pairs = Blackboard(row.Assigned);
            if (eventOutput is not null)
            {
                AppendStructured(ts, "buff_start", Make(("buff_seq", buffSeq), ("template", row.Buff == "unknown_buff" ? null : row.Buff),
                    ("buff_inst_id", uid), ("owner", row.Owner == "?" ? null : row.Owner), ("source", row.Source == "?" ? null : row.Source),
                    ("target_id", owner), ("source_actor_id", src)), row.Origin);
                if (pairs.Count > 0) AppendStructured(ts, "buff_blackboard", Make(("buff_inst_id", uid),
                    ("values", pairs.Select(pair => Make(("key", pair.Key), ("value", pair.Value))).ToArray())), row.Origin);
            }
            else
            {
                Append(ts, $"BUFF_START #{buffSeq} id=\"{row.Buff}\" uid={uid} owner={row.Owner} src={row.Source} ownerId={I(owner)} srcId={I(src)} dur=unknown lifeT=unknown passed=unknown enh=unknown");
                if (pairs.Count > 0) Append(ts, $"BB[{uid}]: " + string.Join(' ', pairs.Select(pair => pair.Key + "=" + General(pair.Value))));
            }
        }
        pendingStarts.Clear(); startTs = null;
    }
    private void Finish(long ts, BigInteger uid, EvidenceObject? origin = null)
    {
        buffSeq++;
        if (eventOutput is not null)
        {
            var template = buffIds.GetValueOrDefault(uid);
            var fields = Make(("buff_seq", buffSeq), ("template", template == "unknown_buff" ? null : template), ("buff_inst_id", uid)).Fields.ToDictionary();
            if (template == "unknown_buff") fields["template_status"] = new EvidenceText("unresolved");
            EmitStructured(ts, "buff_end", new(fields), origin ?? Make());
        }
        else Line(ts, $"BUFF_END #{buffSeq} id=\"{buffIds.GetValueOrDefault(uid) ?? ""}\" uid={uid}");
        buffIds.Remove(uid); buffActors.Remove(uid); buffValues.Remove(uid); buffKeys.Remove(uid);
    }
    private void FinishBuffs(EvidenceValue value, long ts, EvidenceObject? origin = null)
    {
        foreach (var detail in Rows(Obj(value).Get("finish_buffs"))) if (Id(detail.Get("buff_inst_id")) is { } uid) Finish(ts, uid, origin);
    }
    private void CreateBuffs(EvidenceObject e, EvidenceValue value, long ts)
    {
        if (value is not EvidenceObject create || create.Get("details") is not EvidenceArray details) return;
        var trigger = e.Get("trigger_type");
        if (trigger is EvidenceInteger { Value: var phase } && phase == 2) { FinishBuffs(Make(("finish_buffs", details)), ts, e); return; }
        if (trigger is not EvidenceInteger { Value.IsZero: true })
        {
            foreach (var row in details.Items.OfType<EvidenceObject>()) if (Id(row.Get("buff_inst_id")) is { } uid)
            {
                if (eventOutput is not null)
                {
                    var data = Make(("buff_inst_id", uid), ("trigger_type", trigger is EvidenceInteger ? trigger : EvidenceNull.Value),
                        ("action_id", Int(Obj(e.Get("action")).Get("action_id"))), ("target_id", Int(row.Get("target_id"))),
                        ("source_actor_id", Int(row.Get("source_id")))).Fields.ToDictionary();
                    if (e.Fields.TryGetValue("seq_id", out var seq)) data["operation_seq"] = seq;
                    EmitStructured(ts, "buff_unresolved", new(data), e);
                }
                else
                    Line(ts, $"BUFF_ACTION_UNRESOLVED uid={uid} seq={(e.Fields.ContainsKey("seq_id") ? S(e.Get("seq_id")) : "unknown")} triggerType={(trigger is EvidenceInteger ? S(trigger) : "unknown")} actionId={I(Int(Obj(e.Get("action")).Get("action_id")), "None")} ownerId={I(Int(row.Get("target_id")), "None")} srcId={I(Int(row.Get("source_id")), "None")}");
            }
            return;
        }
        foreach (var detail in details.Items.OfType<EvidenceObject>())
        {
            if (Id(detail.Get("buff_inst_id")) is not { } uid) continue;
            var buff = Template(detail.Get("buff_id"));
            if (buff is null && Int(detail.Get("buff_num_id")) is { } num) buff = ResolveBuff(EvidenceNull.Value, new EvidenceInteger(num));
            buff ??= buffIds.GetValueOrDefault(uid) is { } existing && existing != "unknown_buff" ? existing : "unknown_buff";
            Dictionary<string, EvidenceValue> blackboard = new(StringComparer.Ordinal);
            foreach (var row in Rows(detail.Get("assigned_items")))
            {
                var key = Text(row.Get("target_key"), Text(row.Get("input_value_key")));
                if (key.Length > 0 && Float(row.Get("numeric_value")) is { } number) blackboard[key] = Make(("float_value", number));
            }
            var target = Int(detail.Get("target_id")); var src = Int(detail.Get("source_id"));
            StartBuff(ts, buff, uid, Name(target), Name(src), Make(("blackboard", new EvidenceObject(blackboard))), target, src, e, detail);
            var origin = Make(("schemaVersion", 1), ("buffUid", I(uid)), ("buffTemplate", buff),
                ("sourceActorId", detail.Get("source_id") is EvidenceNull ? null : S(detail.Get("source_id"))),
                ("targetActorId", detail.Get("target_id") is EvidenceNull ? null : S(detail.Get("target_id"))),
                ("environmentType", e.Get("template_type")), ("ownerType", e.Get("owner_type")),
                ("environmentInstId", e.Get("inst_id") is EvidenceNull ? null : S(e.Get("inst_id"))),
                ("templateStrId", e.Get("template_str_id")), ("templateIntId", e.Get("template_int_id")),
                ("actionId", Obj(e.Get("action")).Get("action_id")), ("operationSeq", e.Get("seq_id")), ("triggerType", trigger));
            if (eventOutput is not null) EmitStructured(ts, "buff_origin", BuffPacketWire.Data(origin), e);
            else Line(ts, "BUFF_ORIGIN " + Json(origin));
        }
    }
    private void Enable(EvidenceObject e, long ts)
    {
        foreach (var (uid, enabled) in Obj(e.Get("states")).Fields)
        {
            var observation = Make(("schemaVersion", 1), ("buffUid", uid), ("enabled", enabled),
                ("ownerId", e.Get("owner_id") is EvidenceNull ? null : S(e.Get("owner_id"))), ("operationSeq", e.Get("seq_id")),
                ("clientTickMs", e.Get("client_tick_tms")), ("generation", e.Get("generation")));
            if (eventOutput is not null) EmitStructured(ts, "buff_enable", BuffPacketWire.Data(observation), e);
            else Line(ts, "BUFF_ENABLE " + Json(observation, ascii: true));
        }
    }
    private void Keyword(EvidenceObject e, long ts)
    {
        List<EvidenceObject> updates = []; List<string> errors = [];
        if (e.Get("modify") is not EvidenceArray) errors.Add("missing_keyword_modify_list");
        foreach (var value in Items(e.Get("modify")))
        {
            var row = Obj(value);
            var rate = row.Get("modify_value") is EvidenceInteger or EvidenceReal ? Float(row.Get("modify_value")) : null;
            if (value is not EvidenceObject || row.Get("config_index") is not EvidenceInteger index || index.Value < 0 || rate is null || !double.IsFinite(rate.Value))
            { errors.Add("invalid_keyword_modify_row"); continue; }
            updates.Add(Make(("configIndex", index), ("rateAfter", rate.Value)));
        }
        static object? StringIdentity(EvidenceValue value) => value is EvidenceInteger or EvidenceText ? S(value) : null;
        var observation = Make(("schemaVersion", 1), ("sessionId", e.Get("session_id")), ("ownerId", StringIdentity(e.Get("owner_id"))),
            ("generation", e.Get("generation")), ("operationSeq", e.Get("seq_id")), ("clientTickMs", StringIdentity(e.Get("client_tick_tms"))),
            ("buffUid", StringIdentity(e.Get("buff_inst_id"))), ("addedBuffNumId", e.Get("add_buff_num_id")), ("modify", updates), ("operationPayloadCase", e.Get("operation_payload_case")));
        if (Text(observation.Get("operationPayloadCase")) != "trigger_keyword_op_data") errors.Add("keyword_operation_presence_unverified");
        foreach (var field in new[] { "ownerId", "buffUid" })
        {
            var raw = observation.Get(field);
            if (!DecimalRange(raw, 1, BigInteger.One << 64) || S(raw).StartsWith('0')) errors.Add("invalid_" + field);
        }
        foreach (var field in new[] { "generation", "operationSeq", "addedBuffNumId" }) if (observation.Get(field) is not EvidenceInteger integer || integer.Value < 0) errors.Add("invalid_" + field);
        if (observation.Get("sessionId") is not EvidenceText { Value.Length: > 0 }) errors.Add("missing_sessionId");
        if (errors.Count > 0) ((Dictionary<string, EvidenceValue>)observation.Fields)["validationErrors"] = Value(errors);
        else if (updates.Count > 0)
        {
            var uid = Int(observation.Get("buffUid"))!.Value; var owner = Int(observation.Get("ownerId"))!.Value;
            var indices = updates.Select(row => Int(row.Get("configIndex"))!.Value).ToArray();
            var key = (S(observation.Get("sessionId")), S(observation.Get("ownerId")), S(observation.Get("buffUid")));
            var seq = Int(observation.Get("operationSeq"))!.Value;
            if (buffValues.TryGetValue(uid, out var values) && buffActors.GetValueOrDefault(uid).Owner == owner && indices.SequenceEqual(indices.Distinct().Order()))
            {
                var final = Float(updates[^1].Get("rateAfter"))!.Value;
                if (!keywordSerials.TryGetValue(key, out var previous) || seq > previous.Seq)
                { keywordSerials[key] = (seq, final); values["rate"] = final; if (!buffKeys.TryGetValue(uid, out var keys)) buffKeys[uid] = keys = []; keys.Add("rate"); }
                else if (seq == previous.Seq && previous.Rate != final) { keywordSerials[key] = (seq, null); values.Remove("rate"); }
            }
        }
        if (eventOutput is not null) EmitStructured(ts, "buff_keyword", BuffPacketWire.Data(observation), e);
        else Line(ts, (errors.Count > 0 ? "BUFF_KEYWORD_UPDATE_UNRESOLVED " : "BUFF_KEYWORD_UPDATE ") + Json(observation, finite: true));
    }
}
