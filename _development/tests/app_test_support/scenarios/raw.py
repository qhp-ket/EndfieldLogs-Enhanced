
def raw_scene(timestamp=1_000_000):
    return {"type": "SC_SELF_SCENE_INFO", "timestamp_ms": timestamp, "char_list": [
        {"id": 1, "battle_inst_id": 1, "templateid": "chr_0004_pelica", "display_name": "佩丽卡", "squad_index": 0}]}

def raw_hit(timestamp, value):
    return {"type": "BattleOpTriggerAction", "timestamp_ms": timestamp,
        "owner_id": 1, "inst_id": 10, "template_type": "Skill", "template_int_id": 107,
        "action": {"action_type": "BattleActionDamage", "damage_action": {
            "attacker_id": 1, "details": [{"target_id": 99, "value": -value, "cur_hp": 10000-value, "is_crit": False}]}}}
