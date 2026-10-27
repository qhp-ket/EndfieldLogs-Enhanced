"""Battle-operation routing; the session retains ordered iteration."""
from endfield_pcap.service.session.operations.context import BattleOperation
from endfield_pcap.service.session.operations.skills import (
    skill_attach,
    skill_detach,
    skill_start_cast,
    skill_end_cast,
    trigger_action,
    enable_passive_skill,
)
from endfield_pcap.service.session.operations.buffs import (
    trigger_keyword,
    set_buff_enable_state,
    finish_buff,
    add_buff,
)
from endfield_pcap.service.session.operations.entities import (
    entity_die,
    entity_value_modify,
    modify_battle_state,
)
from endfield_pcap.service.session.operations.resources import (
    modify_poise_value,
    update_atb_info,
)

HANDLERS = {
    'BattleOpSkillAttach': skill_attach,
    'BattleOpSkillDetach': skill_detach,
    'BattleOpSkillStartCast': skill_start_cast,
    'BattleOpSkillEndCast': skill_end_cast,
    'BattleOpTriggerAction': trigger_action,
    'BattleOpTriggerKeyword': trigger_keyword,
    'BattleOpSetBuffEnableState': set_buff_enable_state,
    'BattleOpFinishBuff': finish_buff,
    'BattleOpAddBuff': add_buff,
    'BattleOpEnablePassiveSkill': enable_passive_skill,
    'BattleOpEntityDie': entity_die,
    'BattleOpEntityValueModify': entity_value_modify,
    'BattleOpModifyBattleState': modify_battle_state,
    'BattleOpModifyPoiseValue': modify_poise_value,
    'BattleOpUpdateAtbInfo': update_atb_info,
}
