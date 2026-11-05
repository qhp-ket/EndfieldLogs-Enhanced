"""Observed damage calculations, packet attributes and modifier handle evidence."""
from __future__ import annotations

from parser_core.ingestion.fields import (
    _parse_baseline_line,
    _parse_dpd_raw_line,
    _parse_packet_attr_line,
    _parse_packet_modifier_line,
)
from parser_core.ingestion.state import IngestionState
from parser_core.reporting.poise import _parse_poise_damage_event
import json
import re
from copy import deepcopy


def observe_attribute_report(ingestion: IngestionState, seq: int, payload) -> None:
    hit = ingestion.hits_by_seq.get(seq)
    if hit is None:
        return
    try:
        if (type(payload.get('reportPresent')) is not bool
                or payload.get('packetSeq') not in (None, hit.get('packet_seq_id'))
                or payload.get('packetSessionId') not in (None, hit.get('packet_session_id'))):
            raise ValueError('attribute_report_context_mismatch')
        if ('packet_attribute_report_present' in hit
                and hit['packet_attribute_report_present'] != payload['reportPresent']):
            raise ValueError('conflicting_attribute_report_presence')
        if not hit.get('packet_attribute_report_unresolved'):
            hit['packet_attribute_report_present'] = payload['reportPresent']
    except (ValueError, TypeError, AttributeError):
        hit.pop('packet_attribute_report_present', None)
        hit['packet_attribute_report_unresolved'] = True


def observe_modifier_handles(ingestion: IngestionState, seq: int, payload, *, _owned=False) -> None:
    hit = ingestion.hits_by_seq.get(seq)
    if hit is None:
        return
    try:
        if (not isinstance(payload, dict)
                or any(not isinstance(payload.get(side), list) for side in ('attacker', 'defender'))
                or payload.get('packetSeq') not in (None, hit.get('packet_seq_id'))
                or payload.get('packetSessionId') not in (None, hit.get('packet_session_id'))):
            raise ValueError('modifier_handle_context_mismatch')
        handles = {side: [] for side in ('attacker', 'defender')}
        for side in handles:
            for item in payload[side]:
                if (not isinstance(item, dict) or type(item.get('index')) is not int
                        or item['index'] < 0 or type(item.get('buff_inst_id')) not in (int, str)
                        or not re.fullmatch(r'[1-9]\d*', str(item['buff_inst_id']))
                        or int(item['buff_inst_id']) >= 2**64):
                    raise ValueError('invalid_modifier_handle')
                handles[side].append({**(item if _owned else deepcopy(item)), 'buff_inst_id': str(item['buff_inst_id'])})
        if 'packet_modifier_handles' in hit and hit['packet_modifier_handles'] != handles:
            raise ValueError('conflicting_modifier_handles')
        if not hit.get('packet_modifier_handles_unresolved'):
            hit['packet_modifier_handles'] = handles
    except (ValueError, TypeError, KeyError):
        hit.pop('packet_modifier_handles', None)
        hit['packet_modifier_handles_unresolved'] = True


def observe_modifiers(ingestion: IngestionState, seq: int, attacker: list[str], defender: list[str], ts_ms: int) -> None:
    for uid in attacker + defender:
        if uid:
            ingestion.packet_modifier_last_seen_by_uid[str(uid)] = max(
                ingestion.packet_modifier_last_seen_by_uid.get(str(uid), ts_ms), ts_ms)
    hit = ingestion.hits_by_seq.get(seq)
    if hit is not None:
        hit['packet_modifier_seen'] = True
        hit['packet_modifier_uids'] = {'attacker': list(attacker), 'defender': list(defender)}


def observe_attributes(ingestion: IngestionState, seq: int, attacker: list[str], defender: list[str]) -> None:
    hit = ingestion.hits_by_seq.get(seq)
    if hit is None:
        return
    observed = {'attacker': list(attacker), 'defender': list(defender)}
    if hit.get('packet_attr_seen') and hit['packet_attr_details'] != observed:
        hit['packet_attr_conflict'] = True
        hit['packet_attribute_report_unresolved'] = True
        hit['rdps_unresolved_effect_conditions'] = True
    elif not hit.get('packet_attr_conflict'):
        hit['packet_attr_details'] = observed
    hit['packet_attr_seen'] = True


def observe_raw_damage(ingestion: IngestionState, seq: int, evidence) -> None:
    hit = ingestion.hits_by_seq.get(seq)
    if hit is not None:
        hit['dpd_raw'] = evidence


def observe_baseline(ingestion: IngestionState, seq: int, values) -> None:
    hit = ingestion.hits_by_seq.get(seq)
    if hit is not None:
        hit['baseline'] = values
        ingestion.baseline_by_character[str(hit.get('character_key') or '')] = values


def consume_packet_evidence(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    dpd_raw = _parse_dpd_raw_line(raw_line)
    if dpd_raw is not None:
        observe_raw_damage(ingestion, int(dpd_raw['seq']), {key: value for key, value in dpd_raw.items() if key != 'seq'})
        return True

    baseline = _parse_baseline_line(raw_line)
    if baseline is not None:
        seq, values = baseline
        observe_baseline(ingestion, seq, values)
        return True

    if ' PKT_ATTR_INFO #' in raw_line:
        info_match = re.search(r'\bPKT_ATTR_INFO #(\d+) (\{.*\})$', raw_line)
        if info_match:
            try:
                payload = json.loads(info_match.group(2))
            except ValueError:
                payload = None
            observe_attribute_report(ingestion, int(info_match.group(1)), payload)
        return True

    if ' PKT_MOD_DETAIL #' in raw_line:
        detail_match = re.search(r'\bPKT_MOD_DETAIL #(\d+) (\{.*\})$', raw_line)
        if detail_match:
            try:
                payload = json.loads(detail_match.group(2))
            except ValueError:
                payload = None
            observe_modifier_handles(ingestion, int(detail_match.group(1)), payload, _owned=True)
        return True

    packet_modifiers = _parse_packet_modifier_line(raw_line)
    if packet_modifiers is not None:
        seq, attacker_modifier_uids, defender_modifier_uids = packet_modifiers
        observe_modifiers(ingestion, seq, attacker_modifier_uids, defender_modifier_uids, ts_ms)
        return True

    packet_attrs = _parse_packet_attr_line(raw_line)
    if packet_attrs is not None:
        seq, attacker_attr_rows, defender_attr_rows = packet_attrs
        observe_attributes(ingestion, seq, attacker_attr_rows, defender_attr_rows)
        return True

    poise_damage_event = _parse_poise_damage_event(raw_line, ts_ms, line_no)
    if poise_damage_event is not None:
        ingestion.poise_damage_events.append(poise_damage_event)
        return True
    return False
