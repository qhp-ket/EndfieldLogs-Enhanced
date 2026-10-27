"""Evaluate unresolved evidence and allocation readiness for one battle."""
from __future__ import annotations

from collections import Counter
from parser_core.constants import UNKNOWN_ENEMY_KEY
from parser_core.effects.lifecycle import _normalize_buff_duration_ms
from parser_core.effects.packet_mapping import _classify_packet_buff_record
from parser_core.effects.registry import _rdps_registry_known_non_rdps_entry
from parser_core.effects.registry import _rdps_registry_validation_error
from parser_core.effects.registry import _rdps_registry_verified_effect_entry
from parser_core.effects.specifications import _collect_zone_effects
from parser_core.effects.specifications import _extract_dynamic_effect_specs
from parser_core.effects.window_identity import _window_uid_aliases
from typing import Any


def _record_could_affect_external_rdps(record: dict[str, Any]) -> bool:
    source_key = str(record.get("source_character_key") or "")
    if not source_key.startswith("chr_"):
        return bool(record.get("target_enemy_key") or record.get("target_character_key"))
    target_enemy_key = str(record.get("target_enemy_key") or "")
    if target_enemy_key.startswith("eny_"):
        return True
    target_character_key = str(record.get("target_character_key") or "")
    return bool(target_character_key.startswith("chr_") and target_character_key != source_key)


def _record_overlaps_window(record: dict[str, Any], *, battle_start_ms: int, battle_end_ms: int) -> bool:
    start_ts_ms = int(record.get("ts_ms") or 0)
    if record.get('snapshot_end_ts_ms') is not None and int(record['snapshot_end_ts_ms']) < battle_start_ms:
        return False
    if record.get("end_ts_ms") is None and record.get("raw_duration_ms") is None:
        return start_ts_ms <= battle_end_ms
    duration_ms = _normalize_buff_duration_ms(
        start_ts_ms,
        event_key=record.get("event_key"),
        end_ts_ms=record.get("end_ts_ms"),
        raw_duration_ms=record.get("raw_duration_ms"),
        battle_end_ms=battle_end_ms,
    )
    end_ts_ms = start_ts_ms + duration_ms
    return end_ts_ms >= battle_start_ms and start_ts_ms <= battle_end_ms


def _known_non_rdps_buff_record(record: dict[str, Any]) -> bool:
    # A name, classifier label, or lack of decoded effects is not proof.
    return _rdps_registry_known_non_rdps_entry(record) is not None


def _build_rdps_preflight(
    buff_starts: list[dict[str, Any]],
    buff_windows: list[dict[str, Any]],
    *,
    hits: list[dict[str, Any]] | None = None,
    unresolved_hits: list[dict[str, Any]] | None = None,
    unresolved_buff_actions: list[dict[str, Any]] | None = None,
    battle_start_ms: int,
    battle_end_ms: int,
    active_character_keys: set[str] | None = None,
    root_lookup_cache: dict | None = None,
) -> dict[str, Any]:
    included_uids: set[str] = set()
    for window in buff_windows:
        included_uids.update(_window_uid_aliases(window))
    blockers: list[dict[str, Any]] = []
    for row in unresolved_buff_actions or []:
        if row.get("uid_observation_only"):
            continue
        if _record_overlaps_window(row, battle_start_ms=battle_start_ms, battle_end_ms=battle_end_ms):
            blockers.append(dict(row))
    for window in buff_windows:
        if window.get("rdps_invalid_dynamic_evaluation"):
            blockers.append({"uid": window.get("uid"), "reason": "invalid_dynamic_evaluation"})
        if window.get('rdps_unresolved_stack_evidence'):
            blockers.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                             'reason': 'unresolved_stack_evidence'})
        if window.get('rdps_unresolved_enable_evidence'):
            blockers.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                             'reason': 'unobserved_initial_buff_enable_state'})
        if window.get('rdps_snapshot_order_unresolved'):
            blockers.append({'uid': window.get('uid'), 'reason': 'unresolved_buff_snapshot_order'})
    for row in unresolved_hits or []:
        if battle_start_ms <= int(row.get("ts_ms") or 0) <= battle_end_ms:
            blockers.append(dict(row))
    for hit in hits or []:
        missing = []
        dpd = hit.get('dpd_raw')
        if isinstance(dpd, dict) and any(
                value is None for side in ('atk_zones', 'def_zones') for value in dpd.get(side) or []):
            blockers.append({'seq': hit.get('seq'), 'reason': 'invalid_dpd_bucket_evidence'})
        if not hit.get("damage_element") or hit.get("damage_element_source") != "official_action_unit":
            missing.append("damage_action_unit")
        if not hit.get("damage_school"):
            missing.append("damage_school")
        if not hit.get("target_enemy_key") or hit.get("target_enemy_key") == UNKNOWN_ENEMY_KEY:
            missing.append("target_identity")
        if hit.get("packet_hit_value") is None:
            missing.append("packet_hp_loss")
        if missing:
            blockers.append({"seq": hit.get("seq"), "line_no": hit.get("line_no"),
                             "reason": "unresolved_hit_evidence", "missing": missing})
        if hit.get("rdps_unresolved_effect_conditions"):
            blockers.append({"seq": hit.get("seq"), "line_no": hit.get("line_no"),
                             "reason": "unresolved_effect_condition"})
        if hit.get('rdps_unresolved_whitelist_effect'):
            blockers.append({'seq': hit.get('seq'), 'reason': 'external_effect_not_whitelisted'})
        if hit.get('rdps_unresolved_static_multiplier_sources'):
            blockers.append({'seq': hit.get('seq'), 'reason': 'unresolved_static_multiplier_source',
                             'sources': hit['rdps_unresolved_static_multiplier_sources']})
        if hit.get("rdps_unresolved_target_binding"):
            blockers.append({"seq": hit.get("seq"), "reason": "unresolved_effect_target_instance"})
        if hit.get("rdps_unresolved_attacker_binding"):
            blockers.append({"seq": hit.get("seq"), "reason": "unresolved_attacker_stats_binding"})
        if hit.get("rdps_unresolved_dpd_residual"):
            blockers.append({
                "seq": hit.get("seq"),
                "line_no": hit.get("line_no"),
                "reason": "DPD residual has no authoritative attribution",
            })
    checked_external = 0
    accepted_effects = 0
    accepted_non_rdps = 0
    for record in buff_starts:
        if record.get("uid_observation_only"):
            continue
        if not _record_overlaps_window(record, battle_start_ms=battle_start_ms, battle_end_ms=battle_end_ms):
            continue
        proven_non_rdps = _rdps_registry_known_non_rdps_entry(record)
        if (isinstance(proven_non_rdps, dict)
                and proven_non_rdps.get("proof_kind") == "typed_root_structural"):
            record.pop("rdps_unresolved_semantic_condition", None)
            accepted_non_rdps += 1
            continue
        # The gate must evaluate semantics itself. UI label/window building
        # is not a prerequisite for detecting unresolved own multipliers.
        zone_effects = _collect_zone_effects(record, root_lookup_cache=root_lookup_cache)
        dynamic_effects = _extract_dynamic_effect_specs(record, root_lookup_cache=root_lookup_cache)
        if (record.get("end_ts_ms") is None and record.get("raw_duration_ms") is None
                and record.get('lifetime_mode') != 'Infinity'
                and _rdps_registry_verified_effect_entry(record, root_lookup_cache=root_lookup_cache) is not None):
            blockers.append({"uid": record.get("uid"), "event_key": record.get("event_key"),
                             "reason": "unresolved_buff_lifecycle"})
            continue
        if record.get("rdps_unresolved_semantic_condition"):
            blockers.append({"uid": record.get("uid"), "event_key": record.get("event_key"),
                             "reason": "unresolved_semantic_condition",
                             "condition_errors": record["rdps_unresolved_semantic_condition"]})
            continue
        if not _record_could_affect_external_rdps(record):
            continue
        source_key = str(record.get("source_character_key") or "")
        checked_external += 1
        uid = str(record.get("uid") or "")
        has_effect = bool(zone_effects or dynamic_effects)
        included = bool(uid and uid in included_uids)
        classification = _classify_packet_buff_record(record)
        verified_entry = _rdps_registry_verified_effect_entry(record, root_lookup_cache=root_lookup_cache)
        if verified_entry is not None:
            validation_error = _rdps_registry_validation_error(verified_entry, record)
            if validation_error is not None:
                blockers.append(
                    {
                        "uid": uid,
                        "event_key": record.get("event_key"),
                        "raw_event_key": record.get("raw_event_key"),
                        "source_character_key": record.get("source_character_key"),
                        "source_skill_key": record.get("source_skill_key"),
                        "source_skill_family_key": record.get("source_skill_family_key"),
                        "target_character_key": record.get("target_character_key"),
                        "target_enemy_key": record.get("target_enemy_key"),
                        "class": classification.get("class"),
                        "reason": validation_error.get("reason"),
                        "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                        "unknown_bb_keys": validation_error.get("unknown_bb_keys"),
                        "required_bb_keys": validation_error.get("required_bb_keys"),
                        "has_effect": has_effect,
                        "included_effect_window": included,
                        "packet_mapping_rejected": bool(record.get("packet_mapping_rejected")),
                    }
                )
                continue
            accepted_effects += 1
            continue
        if _known_non_rdps_buff_record(record):
            accepted_non_rdps += 1
            continue
        if included and has_effect:
            if verified_entry is None:
                blockers.append(
                    {
                        "uid": uid,
                        "event_key": record.get("event_key"),
                        "raw_event_key": record.get("raw_event_key"),
                        "source_character_key": record.get("source_character_key"),
                        "source_skill_key": record.get("source_skill_key"),
                        "source_skill_family_key": record.get("source_skill_family_key"),
                        "target_character_key": record.get("target_character_key"),
                        "target_enemy_key": record.get("target_enemy_key"),
                        "class": classification.get("class"),
                        "reason": "included external rDPS effect is not in rdps_semantics_registry.verified_effects",
                        "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                        "has_effect": has_effect,
                        "included_effect_window": included,
                        "packet_mapping_rejected": bool(record.get("packet_mapping_rejected")),
                    }
                )
                continue
            accepted_effects += 1
            continue
        if included and classification.get("class") == "effect":
            if verified_entry is None:
                blockers.append(
                    {
                        "uid": uid,
                        "event_key": record.get("event_key"),
                        "raw_event_key": record.get("raw_event_key"),
                        "source_character_key": record.get("source_character_key"),
                        "source_skill_key": record.get("source_skill_key"),
                        "source_skill_family_key": record.get("source_skill_family_key"),
                        "target_character_key": record.get("target_character_key"),
                        "target_enemy_key": record.get("target_enemy_key"),
                        "class": classification.get("class"),
                        "reason": "included external rDPS effect is not in rdps_semantics_registry.verified_effects",
                        "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                        "has_effect": has_effect,
                        "included_effect_window": included,
                        "packet_mapping_rejected": bool(record.get("packet_mapping_rejected")),
                    }
                )
                continue
            accepted_effects += 1
            continue
        blockers.append(
            {
                "uid": uid,
                "event_key": record.get("event_key"),
                "raw_event_key": record.get("raw_event_key"),
                "source_character_key": record.get("source_character_key"),
                "source_skill_key": record.get("source_skill_key"),
                "source_skill_family_key": record.get("source_skill_family_key"),
                "target_character_key": record.get("target_character_key"),
                "target_enemy_key": record.get("target_enemy_key"),
                "class": classification.get("class"),
                "reason": classification.get("reason"),
                "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                "has_effect": has_effect,
                "included_effect_window": included,
                "packet_mapping_rejected": bool(record.get("packet_mapping_rejected")),
            }
        )

    return {
        "mode": "pre_allocation_semantic_gate",
        "ok": not blockers,
        "checked_external_buff_count": checked_external,
        "accepted_effect_buff_count": accepted_effects,
        "accepted_non_rdps_buff_count": accepted_non_rdps,
        "blocker_count": len(blockers),
        "blocker_reason_counts": dict(Counter(str(row.get('reason') or 'unknown') for row in blockers)),
        # Keep the complete blocker list for audit and replay tooling. The
        # reason counts remain available for compact UI summaries, while
        # truncating here hid the concrete records needed to close a gate.
        "blockers": blockers,
    }
