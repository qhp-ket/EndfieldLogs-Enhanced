using System.Numerics;

namespace EndfieldLogs.Runtime.Sessions;

public sealed partial class GameSessionBusiness
{
    private void DecodeOperations(ProtoMessage message, long timestampMs)
    {
        HashSet<BigInteger> clockTicks = [];
        foreach (var op in message.Child("client_data").Children("op_list"))
        {
            var kind = op.Enum("op_type");
            if (kind is null) continue;
            var sequence = op.Optional("seq_id");
            var tick = op.Optional("client_tick_tms");
            if (rotationClockTrace && tick is { Sign: > 0 } time && clockTicks.Add(time))
                Emit("GAME_CLOCK_TICK", timestampMs, new() { ["source"] = "CS_BATTLE_OP", ["tick_ms"] = time, ["seq_id"] = sequence });
            Dictionary<string, object?> Basic() => new() { ["seq_id"] = sequence, ["client_tick_tms"] = tick };
            Dictionary<string, object?> payload;
            ProtoMessage data;
            switch (kind)
            {
                case "BattleOpSkillAttach":
                    data = op.Child("skill_attach_op_data");
                    payload = Basic();
                    payload["src_inst_id"] = data.Optional("src_inst_id");
                    payload["skill_inst_id"] = data.Optional("skill_inst_id");
                    payload["skill_lv"] = data.Optional("skill_lv");
                    payload["skill_source"] = data.Enum("skill_source");
                    AddTemplate(payload, ProtoMessage.Template(data.Child("skill_id")));
                    break;
                case "BattleOpSkillDetach":
                case "BattleOpEnablePassiveSkill":
                    data = op.Child(kind == "BattleOpSkillDetach" ? "skill_detach_op_data" : "skill_enable_op_data");
                    payload = Basic(); payload["skill_inst_id"] = data.Optional("skill_inst_id");
                    break;
                case "BattleOpSkillStartCast":
                case "BattleOpSkillEndCast":
                    data = op.Child(kind == "BattleOpSkillStartCast" ? "skill_start_cast_op_data" : "skill_end_cast_op_data");
                    payload = Basic(); payload["owner_id"] = op.Optional("owner_id"); payload["skill_inst_id"] = data.Optional("inst_id");
                    break;
                case "BattleOpFinishBuff":
                    payload = Basic(); payload["buff_inst_id"] = op.Child("finish_buff_op_data").Optional("buff_inst_id");
                    break;
                case "BattleOpAddBuff":
                    data = op.Child("add_buff_op_data");
                    var buff = data.Child("buff_id");
                    var template = ProtoMessage.Template(buff);
                    payload = Basic();
                    payload["operation_owner_id"] = op.Text("owner_id"); payload["generation"] = op.Number("generation");
                    payload["int_id"] = template.Number; payload["buff_inst_id"] = data.Optional("buff_inst_id");
                    payload["src_inst_id"] = data.Optional("src_inst_id"); payload["target_inst_id"] = data.Optional("target_inst_id");
                    payload["assigned_items"] = data.Child("assigned_items").Payload();
                    if (buff.Value is not null) { payload["buff_template_id"] = buff.Payload(defaults: true); payload["buff_template_id_case"] = buff.Case("id_impl"); }
                    if (template.Text is not null) payload["str_id"] = template.Text;
                    break;
                case "BattleOpTriggerKeyword":
                    if (op.Case("op_data_impl") != "trigger_keyword_op_data") continue;
                    data = op.Child("trigger_keyword_op_data");
                    payload = new() { ["seq_id"] = op.Number("seq_id"), ["client_tick_tms"] = op.Number("client_tick_tms"),
                        ["owner_id"] = op.Text("owner_id"), ["generation"] = op.Number("generation"),
                        ["buff_inst_id"] = data.Text("buff_inst_id"), ["add_buff_num_id"] = data.Number("add_buff_num_id"),
                        ["modify"] = data.Children("modify").Select(row => new Dictionary<string, object?>
                            { ["config_index"] = row.Number("config_index"), ["modify_value"] = row.Real("modify_value") }).ToArray(),
                        ["operation_payload_case"] = op.Case("op_data_impl") };
                    break;
                case "BattleOpSetBuffEnableState":
                    data = op.Child("set_buff_enable_state_op_data");
                    payload = new() { ["seq_id"] = op.Number("seq_id"), ["client_tick_tms"] = op.Number("client_tick_tms"),
                        ["owner_id"] = op.Number("owner_id"), ["generation"] = op.Number("generation"),
                        ["states"] = data.Mapping("buff_inst_id_to_enable_state").ToDictionary(pair => pair.Key.ToString()!, pair => pair.Value) };
                    break;
                case "BattleOpEntityDie":
                    var entity = op.Child("entity_die_op_data").Optional("entity_inst_id");
                    payload = Basic(); payload["entity_inst_id"] = entity;
                    Emit(kind, timestampMs, payload);
                    if (MergeMultiPhaseEnemyBattles && MergedBattleActive && entity is { } id && TrackedEnemyInstanceIds.Contains(id))
                    {
                        var ended = Basic(); ended["is_in_battle"] = false;
                        Emit("BattleOpModifyBattleState", timestampMs, ended);
                        MergedBattleActive = false; TrackedEnemyInstanceIds.Clear();
                    }
                    continue;
                case "BattleOpModifyBattleState":
                    var active = op.Child("modify_battle_state_op_data").Boolean("is_in_battle");
                    if (MergeMultiPhaseEnemyBattles && TrackedEnemyTemplateId is not null)
                    {
                        if (active && !MergedBattleActive) MergedBattleActive = true;
                        else continue;
                    }
                    payload = Basic(); payload["is_in_battle"] = active;
                    Emit(kind, timestampMs, payload);
                    if (active) EmitBattleContext(timestampMs);
                    continue;
                case "BattleOpEntityValueModify":
                    data = op.Child("entity_value_modify_data");
                    var value = data.Child("value");
                    payload = Basic(); payload["owner_id"] = op.Optional("owner_id");
                    payload["entity_inst_id"] = data.Optional("entity_inst_id"); payload["scene_num_id"] = data.Optional("scene_num_id");
                    payload["source"] = data.Optional("source");
                    payload["hp"] = value.Value is null ? null : value.Real("hp");
                    payload["ultimatesp"] = value.Value is null ? null : value.Real("ultimatesp");
                    payload["delta_value"] = data.PresentFloat("delta_value");
                    AddTemplates(payload, data);
                    break;
                case "BattleOpModifyPoiseValue":
                    data = op.Child("modify_poise_value_op_data");
                    payload = Basic(); payload["owner_id"] = op.Optional("owner_id");
                    payload["modify_type"] = data.Enum("modify_type"); payload["owner_type"] = data.Enum("owner_type");
                    payload["value"] = data.Real("value"); payload["cur_poise_value"] = data.Real("cur_poise_value");
                    payload["attacker_inst_id"] = data.Optional("attacker_inst_id"); payload["action_id"] = data.Optional("action_id");
                    payload["battle_report_info"] = data.Child("battle_report_info").Payload();
                    AddTemplates(payload, data);
                    break;
                case "BattleOpUpdateAtbInfo":
                    data = op.Child("update_atb_info_op_data");
                    var atb = data.Child("atb_data");
                    var reason = atb.Enum("reason");
                    payload = Basic(); payload["owner_id"] = op.Optional("owner_id");
                    payload["atb_value"] = atb.Value is null ? null : atb.Real("atb_value");
                    payload["atb_recovery_speed"] = atb.PresentFloat("atb_recovery_speed") ?? (reason == "ChangeRecoverySpeed" ? 0.0 : null);
                    payload["reason"] = reason; payload["delta_value"] = data.PresentFloat("delta_value");
                    AddTemplates(payload, data);
                    break;
                case "BattleOpTriggerAction":
                    EmitTrigger(op, sequence, tick, timestampMs);
                    continue;
                default: continue;
            }
            Emit(kind, timestampMs, payload);
        }
    }

    private static void AddTemplate(Dictionary<string, object?> payload,
        (string? Type, BigInteger? Number, string? Text) template, string prefix = "")
    {
        payload[prefix + "template_type"] = template.Type;
        payload[prefix + "template_int_id"] = template.Number;
        if (template.Text is not null) payload[prefix + "template_str_id"] = template.Text;
    }

    private static void AddTemplates(Dictionary<string, object?> payload, ProtoMessage data)
    {
        AddTemplate(payload, ProtoMessage.Template(data.Child("template_id")));
        AddTemplate(payload, ProtoMessage.Template(data.Child("original_source_template_id")), "orig_");
    }

    private void EmitTrigger(ProtoMessage op, BigInteger? sequence, BigInteger? tick, long timestampMs)
    {
        var trigger = op.Child("trigger_action_op_data");
        var action = trigger.Child("action");
        var templateMessage = trigger.Child("template_id");
        var template = ProtoMessage.Template(templateMessage);
        Dictionary<string, object?> payload = new()
        {
            ["seq_id"] = sequence, ["client_tick_tms"] = tick, ["owner_id"] = trigger.Optional("owner_id") ?? op.Optional("owner_id"),
            ["operation_owner_id"] = op.Declares("owner_id") ? op.Text("owner_id") : null,
            ["trigger_owner_id"] = trigger.Declares("owner_id") ? trigger.Text("owner_id") : null,
            ["trigger_inst_id"] = trigger.Declares("inst_id") ? trigger.Text("inst_id") : null,
            ["generation"] = op.Declares("generation") ? op.Number("generation") : null,
            ["owner_type"] = trigger.Text("owner_type") is { Length: > 0 } ownerType ? ownerType : null,
            ["inst_id"] = trigger.Optional("inst_id"), ["trigger_type"] = trigger.Declares("trigger_type") ? trigger.Number("trigger_type") : null,
            ["template_type"] = template.Type, ["template_int_id"] = template.Number,
            ["action"] = action.Payload(defaults: true), ["action_serialization"] = "protobuf_json_implicit_defaults_v1",
        };
        if (templateMessage.Value is not null)
        {
            payload["template_id"] = templateMessage.Payload(defaults: true);
            payload["template_id_case"] = templateMessage.Case("id_impl");
        }
        if (action.Value is not null) payload["action_runtime_case"] = action.Case("inst_impl");
        if (op.Value is not null) payload["operation_payload_case"] = op.Case("op_data_impl");
        var presence = DamagePresence(action).ToArray();
        if (presence.Length > 0) payload["damage_detail_presence"] = presence;
        if (template.Text is not null) payload["template_str_id"] = template.Text;
        if (string.Equals(template.Type, "skill", StringComparison.OrdinalIgnoreCase)) payload["level"] = TriggerLevel(op, trigger, template, action);
        Emit("BattleOpTriggerAction", timestampMs, payload);
    }

    private BigInteger? TriggerLevel(ProtoMessage op, ProtoMessage trigger,
        (string? Type, BigInteger? Number, string? Text) template, ProtoMessage action)
    {
        var key = TemplateKey(template);
        if (key is null) return null;
        var ids = new[] { action.Child("damage_action").Optional("attacker_id"), trigger.Optional("owner_id"), op.Optional("owner_id") }
            .Where(id => id is not null).Select(id => id!.Value).Distinct().ToArray();
        return ids.Length == 1 && skillLevels.TryGetValue(ids[0], out var levels) && levels.TryGetValue(key, out var level) ? level : null;
    }

    private static IEnumerable<Dictionary<string, object?>> DamagePresence(ProtoMessage action)
    {
        var index = 0;
        foreach (var detail in action.Child("damage_action").Children("details"))
        {
            var modifiers = detail.Child("modifier_args");
            var attacker = modifiers.Children("attacker_modifiers").ToArray();
            var defender = modifiers.Children("defender_modifiers").ToArray();
            yield return new() { ["detail_index"] = index++, ["has_battle_report_info"] = detail.Has("battle_report_info"),
                ["has_calculation_check_args"] = detail.Has("calculation_check_args"), ["has_calculate_damage_check_args"] = detail.Has("calculate_damage_check_args"),
                ["processor_debug_args_count"] = detail.Items("processor_debug_args").Count(),
                ["has_attacker_attr_modifier_debug_data"] = detail.Has("attacker_attr_modifier_debug_data"),
                ["has_defender_attr_modifier_debug_data"] = detail.Has("defender_attr_modifier_debug_data"),
                ["attacker_modifier_count"] = attacker.Length, ["defender_modifier_count"] = defender.Length,
                ["attacker_modifier_debug_handle_count"] = attacker.Count(row => row.Items("processor_debug_args").Any()),
                ["defender_modifier_debug_handle_count"] = defender.Count(row => row.Items("processor_debug_args").Any()),
                ["attacker_modifier_debug_arg_entry_count"] = attacker.Sum(row => row.Items("processor_debug_args").Count()),
                ["defender_modifier_debug_arg_entry_count"] = defender.Sum(row => row.Items("processor_debug_args").Count()) };
        }
    }
}
