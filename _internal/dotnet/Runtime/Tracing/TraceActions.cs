using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private void Trigger(EvidenceObject e, EvidenceObject action, long ts)
    {
        var type = Text(action.Get("action_type"));
        if (BlackboardAction(e, action, type, ts)) return;
        if (type == "BattleActionLaunchProjectile" || action.Fields.ContainsKey("launch_projectile_action")) Launch(e, action.Get("launch_projectile_action"), ts);
        if (type == "BattleActionSpawnAbilityEntity" || action.Fields.ContainsKey("spawn_ability_entity_action")) Spawn(e, action.Get("spawn_ability_entity_action"), ts);
        if (type == "BattleActionDamage" || action.Fields.ContainsKey("damage_action")) Damage(e, action.Get("damage_action"), ts);
        if (type == "BattleActionFinishBuff" || action.Fields.ContainsKey("finish_buff_action")) FinishBuffs(action.Get("finish_buff_action"), ts, e);
    }
    private void Launch(EvidenceObject e, EvidenceValue value, long ts)
    {
        if (value is not EvidenceObject launch) return;
        var source = Id(launch.Get("source_id")) ?? Int(e.Get("owner_id"));
        var sourceName = source is { IsZero: false } sid ? names.GetValueOrDefault(sid) : null;
        var skill = ResolveSkill(e.Get("template_str_id"), e.Get("template_int_id"));
        var character = Character(skill) ?? (source is { IsZero: false } ? Character(sourceName) : null);
        if (character is null) return;
        if (source is { IsZero: false } id && names.TryAdd(id, character)) WriteActorMapping(ts, id, character, "launch_source", skill, e);
        foreach (var detail in Rows(launch.Get("details")))
        {
            var projectile = Id(detail.Get("client_projectile_id")) ?? Id(detail.Get("projectile_id")) ?? Id(detail.Get("inst_id"));
            var trigger = TriggerSkill(e);
            if (projectile is not null && trigger == "buff_chr_0036_jsspsi_xianjing_inkhurteffect" && EvidenceJson.PythonEquals(Obj(e.Get("action")).Get("action_id"), new EvidenceInteger(14)))
            {
                var observation = Make(("schema_version", 1), ("template_key", trigger), ("action_id", 14),
                    ("session_id", e.Get("session_id")), ("operation_seq", e.Get("seq_id")), ("client_tick_ms", e.Get("client_tick_tms")),
                    ("buff_uid", S(e.Get("inst_id"))), ("owner_id", S(e.Get("owner_id"))), ("source_actor_id", I(source, "None")), ("projectile_id", I(projectile)));
                if (eventOutput is not null) EmitStructured(ts, "ink_release", BlackboardWire.ReleaseData(observation), e);
                else Line(ts, "INK_RELEASE " + Json(observation, finite: true));
            }
            if (projectile is not null && names.TryAdd(projectile.Value, character)) WriteActorMapping(ts, projectile.Value, character, "launch_projectile", skill, e);
        }
    }
    private void Spawn(EvidenceObject e, EvidenceValue value, long ts)
    {
        if (value is not EvidenceObject spawn) return;
        var owner = Int(e.Get("owner_id"));
        foreach (var detail in Rows(spawn.Get("details")))
        {
            var source = Id(detail.Get("source_id")) ?? owner;
            if (eventOutput is not null)
            {
                EmitStructured(ts, "ability_spawn", StructuredEntity.SpawnData(e, detail,
                    new EvidenceInteger(Int(Obj(e.Get("action")).Get("action_id")) ?? 0), Name(owner), Name(source), TriggerSkill(e)), e);
                continue;
            }
            static string Vector(EvidenceValue vector) => string.Join(',', new[] { "x", "y", "z" }.Select(axis => Float(Obj(vector).Get(axis)) is { } number ? PythonDisplay.Float(number) : "unknown"));
            Line(ts, $"ABILITY_ENTITY_SPAWN seq={I(Int(e.Get("seq_id")) ?? 0)} tick={I(Int(e.Get("client_tick_tms")) ?? 0)} actionId={I(Int(Obj(e.Get("action")).Get("action_id")) ?? 0)} inst={I(Int(e.Get("inst_id")))} skill={TriggerSkill(e)} templateIntId={I(Int(e.Get("template_int_id")))} ownerId={I(owner)} owner={Name(owner)} sourceId={I(source)} source={Name(source)} entityId={I(Int(detail.Get("client_ability_entity_id")))} pos={Vector(detail.Get("init_pos"))} rot={Vector(detail.Get("rotation"))}");
        }
    }
    private void BlackboardLine(EvidenceObject e, long ts, string label, BigInteger action, string extra) => Line(ts,
        $"{label} seq={I(Int(e.Get("seq_id")) ?? 0)} tick={I(Int(e.Get("client_tick_tms")) ?? 0)} inst={I(Int(e.Get("inst_id")))} ownerId={I(Int(e.Get("owner_id")))} owner={Name(Int(e.Get("owner_id")))} packetSessionId={Text(e.Get("session_id"), "unknown")} skill={TriggerSkill(e)} actionId={action} {extra}");
    private static (EvidenceObject Identity, EvidenceObject Template, string? Case) DynamicIdentity(EvidenceObject e, EvidenceObject action, string type)
    {
        var template = Obj(e.Get("template_id"));
        var cases = new[] { "int_id", "str_id" }.Where(template.Fields.ContainsKey).ToArray(); var templateCase = cases.Length == 1 ? cases[0] : null;
        var identity = Make(("schemaVersion", 1), ("sessionId", e.Get("session_id")), ("operationSeq", e.Get("seq_id")),
            ("operationOwnerId", e.Get("operation_owner_id")), ("ownerType", e.Get("owner_type")), ("ownerId", e.Get("trigger_owner_id")),
            ("environmentInstId", e.Get("trigger_inst_id")), ("generation", e.Get("generation")),
            ("clientTickMs", e.Get("client_tick_tms") is EvidenceNull ? null : S(e.Get("client_tick_tms"))),
            ("templateType", template.Get("type")), ("templateIdCase", templateCase), ("templateIntId", template.Get("int_id")), ("templateStrId", template.Get("str_id")),
            ("actionId", action.Get("action_id")), ("triggerType", e.Get("trigger_type")),
            ("actionType", type == "BattleActionModifyDynamicBlackboard" ? 7 : type == "BattleActionRefreshBuffAttrModifierValue" ? 31 : 35),
            ("actionRuntimeCase", e.Get("action_runtime_case")), ("operationPayloadCase", e.Get("operation_payload_case")));
        var fields = (Dictionary<string, EvidenceValue>)identity.Fields;
        if (new[] { "operation_owner_id", "trigger_owner_id", "trigger_inst_id", "generation", "template_id" }.All(key => e.Get(key) is EvidenceNull))
            fields["eventContext"] = new EvidenceObject(new[] { "owner_id", "inst_id", "owner_type", "template_type", "template_int_id", "template_str_id", "seq_id" }.Where(e.Fields.ContainsKey).ToDictionary(key => key, e.Get, StringComparer.Ordinal));
        foreach (var key in new[] { "operationOwnerId", "ownerId", "environmentInstId" }) if (identity.Get(key) is EvidenceInteger or EvidenceText) fields[key] = new EvidenceText(S(identity.Get(key)));
        return (identity, template, templateCase);
    }
    private bool BlackboardAction(EvidenceObject e, EvidenceObject action, string type, long ts)
    {
        var inst = Id(e.Get("inst_id")); var actionId = Int(action.Get("action_id")) ?? 0;
        if (type is "BattleActionModifyDynamicBlackboard" or "BattleActionRefreshBuffAttrModifierValue" or "BattleActionReadSkillActionToBb")
        {
            var (identity, template, templateCase) = DynamicIdentity(e, action, type);
            var fields = (Dictionary<string, EvidenceValue>)identity.Fields;
            if (type is "BattleActionRefreshBuffAttrModifierValue" or "BattleActionReadSkillActionToBb")
            {
                var read = type == "BattleActionReadSkillActionToBb";
                var runtimeField = read ? "read_skill_setting_to_bb_action" : "refresh_buff_attr_modifier_value_action";
                var runtime = action.Get(runtimeField); List<string> errors = [];
                var runtimeFields = action.Fields.Keys.Where(key => key.EndsWith("_action", StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
                if (!runtimeFields.SetEquals([runtimeField]) || (read ? runtime is not EvidenceObject r || r.Get("runtime_details") is not EvidenceArray : runtime is not EvidenceObject { Fields.Count: 0 }))
                    errors.Add(read ? "invalid_skill_setting_runtime" : "invalid_refresh_runtime_oneof");
                if (Text(e.Get("action_runtime_case")) != runtimeField) errors.Add(read ? "skill_setting_runtime_presence_unverified" : "refresh_runtime_presence_unverified");
                if (Text(e.Get("operation_payload_case")) != "trigger_action_op_data") errors.Add("trigger_operation_presence_unverified");
                if (templateCase is null || Text(e.Get("template_id_case")) != templateCase) errors.Add("invalid_template_oneof");
                if (read) { fields["runtime"] = runtime; fields["actionSerialization"] = e.Get("action_serialization"); }
                else
                {
                    if (templateCase == "int_id" && template.Get("int_id") is not EvidenceInteger) errors.Add("invalid_template_int_id");
                    if (templateCase == "str_id" && template.Get("str_id") is not EvidenceText) errors.Add("invalid_template_str_id");
                    if (identity.Get("ownerType") is not (EvidenceInteger or EvidenceText) || S(identity.Get("ownerType")) is not ("0" or "1" or "2" or "3")) errors.Add("invalid_ownerType");
                    foreach (var key in new[] { "operationOwnerId", "ownerId", "environmentInstId" }) if (!DecimalRange(identity.Get(key), 0, BigInteger.One << 64)) errors.Add("invalid_" + key);
                    foreach (var key in new[] { "operationSeq", "generation", "actionId", "triggerType" }) if (identity.Get(key) is not EvidenceInteger) errors.Add("invalid_" + key);
                    if (!DecimalRange(e.Get("client_tick_tms"), -(BigInteger.One << 63), BigInteger.One << 63, signed: true)) errors.Add("invalid_clientTickMs");
                    if (identity.Get("sessionId") is not EvidenceText { Value.Length: > 0 }) errors.Add("missing_sessionId");
                }
                fields["buffUid"] = identity.Get("ownerType") is EvidenceInteger or EvidenceText && S(identity.Get("ownerType")) == "1"
                    && Text(template.Get("type")) == "Buff" && identity.Get("environmentInstId") is not EvidenceNull && S(identity.Get("environmentInstId")) != "0"
                    ? identity.Get("environmentInstId") : EvidenceNull.Value;
                if (errors.Count > 0) fields["validationErrors"] = Value(errors);
                var label = read ? "BB_READ_SKILL_SETTING" : "BUFF_ATTR_REFRESH";
                if (eventOutput is not null) EmitStructured(ts, read ? "blackboard_skill_setting" : "buff_attribute_refresh", BuffPacketWire.Data(identity), e);
                else Line(ts, label + (errors.Count > 0 ? "_UNRESOLVED " : " ") + Json(identity, finite: true));
                return true;
            }
            var dynamicFields = action.Fields.Keys.Where(key => key.EndsWith("_action", StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
            if (!dynamicFields.SetEquals(["modify_dynamic_blackboard_action"]) || e.Get("action_runtime_case") is not EvidenceNull && Text(e.Get("action_runtime_case")) != "modify_dynamic_blackboard_action") return true;
            var raw = Obj(action.Get("modify_dynamic_blackboard_action")).Get("client_value");
            if (inst is not null && raw is EvidenceInteger or EvidenceReal && Float(raw) is { } number && double.IsFinite(number))
            {
                if (!dynamicBb.TryGetValue(inst.Value, out var rows)) dynamicBb[inst.Value] = rows = [];
                rows.Add((actionId, number)); if (rows.Count > 8) rows.RemoveRange(0, rows.Count - 8);
                if (eventOutput is not null) EmitStructured(ts, "blackboard_dynamic", DynamicWire.Data(e, new EvidenceInteger(actionId), number, Name(Int(e.Get("owner_id"))), TriggerSkill(e), identity), e);
                else BlackboardLine(e, ts, "BB_MODIFY_DYNAMIC", actionId, "value=" + PythonDisplay.Float(number) + " identity=" + Json(identity, finite: true));
            }
        }
        if (type == "BattleActionSimpleCalcBb" && inst is not null && action.Get("simple_calc_bb_action") is EvidenceObject calc)
        {
            var key = Text(calc.Get("client_target_key")); var final = Float(calc.Get("client_final_value"));
            if (key.Length > 0 && final is not null)
            {
                if (!calcBb.TryGetValue(inst.Value, out var rows)) calcBb[inst.Value] = rows = [];
                rows.Add((actionId, key, final.Value)); if (rows.Count > 12) rows.RemoveRange(0, rows.Count - 12);
                if (eventOutput is not null)
                {
                    List<(string, EvidenceValue)> values = [("key", new EvidenceText(key)), ("final_value", new EvidenceReal(final.Value))];
                    if (Float(calc.Get("client_value_a")) is { } a) values.Add(("value_a", new EvidenceReal(a)));
                    if (Float(calc.Get("client_value_b")) is { } b) values.Add(("value_b", new EvidenceReal(b)));
                    EmitStructured(ts, "blackboard_calculation", BlackboardWire.Data(e, actionId, Name(Int(e.Get("owner_id"))), TriggerSkill(e), [.. values]), e);
                }
                else
                {
                    List<string> extra = ["key=" + key, "final=" + PythonDisplay.Float(final.Value)];
                    if (Float(calc.Get("client_value_a")) is { } a) extra.Add("valueA=" + PythonDisplay.Float(a));
                    if (Float(calc.Get("client_value_b")) is { } b) extra.Add("valueB=" + PythonDisplay.Float(b));
                    BlackboardLine(e, ts, "BB_SIMPLE_CALC", actionId, string.Join(' ', extra));
                }
            }
        }
        if ((type == "BattleActionMultiModifyBb" || action.Fields.ContainsKey("multi_modify_bb_action")) && action.Get("multi_modify_bb_action") is EvidenceObject modify)
        {
            var key = Text(modify.Get("key")); var number = Float(modify.Get("value"));
            if (key.Length > 0 || number is not null)
            {
                if (eventOutput is not null)
                {
                    List<(string, EvidenceValue)> values = [];
                    if (key.Length > 0) values.Add(("key", new EvidenceText(key)));
                    if (number is not null) values.Add(("value", new EvidenceReal(number.Value)));
                    EmitStructured(ts, "blackboard_modify", BlackboardWire.Data(e, actionId, Name(Int(e.Get("owner_id"))), TriggerSkill(e), [.. values]), e);
                }
                else
                {
                    List<string> extra = [];
                    if (key.Length > 0) extra.Add("key=" + key); if (number is not null) extra.Add("value=" + General(number));
                    BlackboardLine(e, ts, "BB_MULTI_MODIFY", actionId, string.Join(' ', extra));
                }
            }
        }
        if ((type == "BattleActionSetBlackboardFromPreset" || action.Fields.ContainsKey("set_blackboard_from_preset_action")) && action.Get("set_blackboard_from_preset_action") is EvidenceObject preset && Truth(preset.Get("modified_value")))
        {
            if (eventOutput is not null) EmitStructured(ts, "blackboard_preset", BlackboardWire.Data(e, actionId, Name(Int(e.Get("owner_id"))), TriggerSkill(e), ("modified_value", new EvidenceText(Text(preset.Get("modified_value"))))), e);
            else BlackboardLine(e, ts, "BB_SET_PRESET", actionId, "modifiedValue=" + Quote(Text(preset.Get("modified_value"))));
        }
        return false;
    }
}
