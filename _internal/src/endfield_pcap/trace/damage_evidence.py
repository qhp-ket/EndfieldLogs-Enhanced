"""Packet calculation tokens and per-hit evidence in canonical write order."""
from __future__ import annotations
import json
import re
from typing import TYPE_CHECKING, Any
from endfield_pcap.trace.formatting import _intish, _floatish, _trace_string, _modifier_uid_tokens, _attr_info_tokens
if TYPE_CHECKING:
    from endfield_pcap.trace.bridge import TraceBridge


def calculation_tokens(detail: dict[str, Any]) -> list[str]:
    calc_args = detail.get("calculate_damage_check_args")
    calc_tokens: list[str] = []
    if isinstance(calc_args, dict):
        calc_field_names = {
            "client_calc_result_value": "clientCalc",
            "client_final_damage_scale": "clientFinalScale",
            "client_attack_value": "clientAttack",
            "client_crit_add_scale": "clientCritAdd",
            "client_def_attr_defender_def": "clientDef",
            "client_def_resistance": "clientDefResistance",
            "client_dmg_type_resistance": "clientDmgTypeResistance",
            "client_defender_poise_factor": "clientPoiseFactor",
            "client_ignite_damage_scalar": "clientIgniteScalar",
            "client_final_value": "clientFinalValue",
            "client_weak_damage_scalar": "clientWeakScalar",
            "client_shelter_damage_scalar": "clientShelterScalar",
            "client_physical_infliction_damage_scalar": "clientPhysicalInflictionScalar",
        }
        for field_name, token_name in calc_field_names.items():
            value = _floatish(calc_args.get(field_name))
            if value is not None:
                calc_tokens.append(f"{token_name}={value:.6g}")
    return calc_tokens


def packet_identity_tokens(event: dict[str, Any]) -> list[str]:
    packet_identity_tokens = []
    if isinstance(event.get('session_id'), str) and event['session_id']:
        packet_identity_tokens.append('packetSessionId=' + _trace_string(event['session_id']))
    packet_owner = event.get('operation_owner_id')
    if (type(packet_owner) in (int, str) and re.fullmatch(r'[0-9]+', str(packet_owner))
            and 0 <= int(packet_owner) < 2**64):
        packet_identity_tokens.append('packetOwnerId=' + str(packet_owner))
    if type(event.get('generation')) is int and 0 <= event['generation'] < 2**32:
        packet_identity_tokens.append('packetGeneration=' + str(event['generation']))
    return packet_identity_tokens


def write_damage_evidence(bridge: TraceBridge, ts_ms: int, event: dict[str, Any],
                          detail: dict[str, Any], detail_presence: dict[str, Any]) -> None:
    modifier_args = detail.get("modifier_args") if isinstance(detail.get("modifier_args"), dict) else {}
    atk_mods = _modifier_uid_tokens(modifier_args, "attacker_modifiers")
    def_mods = _modifier_uid_tokens(modifier_args, "defender_modifiers")
    if atk_mods or def_mods:
        bridge._line(
            ts_ms,
            f"PKT_MOD #{bridge.hit_seq} atk=[{' '.join(atk_mods)}] def=[{' '.join(def_mods)}]",
        )
        # Keep each handle's processor index and debug arguments;
        # UID-only display tokens cannot identify the applied entry.
        bridge._line(ts_ms, f"PKT_MOD_DETAIL #{bridge.hit_seq} " + json.dumps({
            'attacker': modifier_args.get('attacker_modifiers') or [],
            'defender': modifier_args.get('defender_modifiers') or [],
            'packetSessionId': event.get('session_id'),
            'packetSeq': event.get('seq_id'),
            'damageUnitIndex': detail.get('damage_unit_index'),
            'partInstId': detail.get('part_inst_id'),
        }, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
    battle_report_info = detail.get("battle_report_info") if isinstance(detail.get("battle_report_info"), dict) else {}
    report_present = (detail_presence.get('has_battle_report_info')
                      if type(detail_presence.get('has_battle_report_info')) is bool
                      else True if isinstance(detail.get('battle_report_info'), dict) else None)
    if type(report_present) is bool:
        bridge._line(ts_ms, f"PKT_ATTR_INFO #{bridge.hit_seq} " + json.dumps({
            'reportPresent': report_present, 'packetSeq': event.get('seq_id'),
            'packetSessionId': event.get('session_id'),
        }, ensure_ascii=False, separators=(',', ':')))
    atk_attrs = _attr_info_tokens(battle_report_info, "attacker_attr_modify_info")
    def_attrs = _attr_info_tokens(battle_report_info, "defender_attr_modify_info")
    if atk_attrs or def_attrs:
        bridge._line(
            ts_ms,
            f"PKT_ATTR #{bridge.hit_seq} atk=[{' '.join(atk_attrs)}] def=[{' '.join(def_attrs)}]",
        )
    if detail_presence:
        has_calc_check = bool(detail_presence.get("has_calculation_check_args"))
        has_calc = bool(detail_presence.get("has_calculate_damage_check_args"))
        proc_count = int(_intish(detail_presence.get("processor_debug_args_count")) or 0)
        has_att_dbg = bool(detail_presence.get("has_attacker_attr_modifier_debug_data"))
        has_def_dbg = bool(detail_presence.get("has_defender_attr_modifier_debug_data"))
        atk_mod_dbg_handles = int(_intish(detail_presence.get("attacker_modifier_debug_handle_count")) or 0)
        def_mod_dbg_handles = int(_intish(detail_presence.get("defender_modifier_debug_handle_count")) or 0)
        atk_mod_dbg_args = int(_intish(detail_presence.get("attacker_modifier_debug_arg_entry_count")) or 0)
        def_mod_dbg_args = int(_intish(detail_presence.get("defender_modifier_debug_arg_entry_count")) or 0)
        if (
            has_calc_check
            or has_calc
            or proc_count
            or has_att_dbg
            or has_def_dbg
            or atk_mod_dbg_handles
            or def_mod_dbg_handles
            or atk_mod_dbg_args
            or def_mod_dbg_args
        ):
            bridge._line(
                ts_ms,
                (
                    f"PKT_DBG #{bridge.hit_seq} "
                    f"calcCheck={1 if has_calc_check else 0} "
                    f"calcArgs={1 if has_calc else 0} "
                    f"procArgs={proc_count} "
                    f"attDbg={1 if has_att_dbg else 0} "
                    f"defDbg={1 if has_def_dbg else 0} "
                    f"atkModDbgHandles={atk_mod_dbg_handles} "
                    f"defModDbgHandles={def_mod_dbg_handles} "
                    f"atkModDbgArgs={atk_mod_dbg_args} "
                    f"defModDbgArgs={def_mod_dbg_args}"
                ),
            )
