"""Public upload-file entry points and compatibility exports."""
from __future__ import annotations

# Preserve direct package usage when only uploader_core was placed on sys.path.
from pathlib import Path
import sys
try:
    import parser_core
except ModuleNotFoundError:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "parser_core"
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            break

from uploader_core.payload.catalog import (
    _infer_weapon_level_from_base_atk,
    _load_equip_catalog,
    _load_weapon_catalog,
    _normalize_asset_url,
    _repo_root,
)
from uploader_core.payload.files import (
    _MANAGED_INCREMENTAL_TAIL_BYTES,
    _is_uploadable_battle_payload,
    _payload_fingerprint,
    _read_incremental_tail_text,
    build_battle_upload_payload_from_log,
    build_battle_upload_payloads_from_log,
)
from uploader_core.payload.loadout import (
    _ADMIN_CANONICAL_KEY,
    _ENDMIN_VARIANTS,
    _build_loadout_by_character_key,
    _is_character_key,
    _load_loadout_entries,
    _loadout_entries_with_fallback,
    _loadout_lookup_keys,
    _lookup_loadout_name,
    _lookup_loadout_payload,
    _merge_equip_entries,
    _merge_loadout_entry,
    _normalize_equip_entry,
    _normalize_loadout_entry,
    _normalize_payload_equip_slots,
    _resolve_loadout_character_key,
)
from uploader_core.payload.loadout_evidence import (
    _raw_loadout_entries_for_segment,
    _raw_text_loadout_entries,
    _raw_text_loadout_state,
    _sorted_loadout_entries,
)
from uploader_core.payload.projection import (
    _build_payload_from_segment,
    _camelize_state_key,
    _canonical_character_keys,
    _character_state_payload,
    _contract_tag_payload,
    _contract_tags_payload,
    _timeline_effect_payload,
)
from parser_core.battle_splitter.trace import (
    _DAY_MS,
    _GAME_TIMER_END_ELAPSED_RE,
    _IDLE_SPLIT_MS,
    _OFFICIAL_TIMER_END_ELAPSED_RE,
    _POST_TIMER_TAIL_MS,
    _TIMESTAMP_RE,
    _extend_timer_tail_end_line,
    _find_context_start_line,
    _find_line_index_for_abs,
    _find_loadout_context_start_line,
    _is_loadout_context_line,
    _merged_timer_start_records,
    _parse_game_timer_end_elapsed_ms,
    _parse_line_timestamp_ms,
    _parse_official_timer_end_elapsed_ms,
    _parse_timer_end_elapsed_ms,
    _split_trace_into_battles,
)


PAYLOAD_BUILDER_VERSION = "payload-builder-2026.10.15.1"


def payload_builder_diagnostics() -> dict[str, str]:
    from parser_core.constants import PARSER_VERSION, RULES_VERSION

    return {
        "payloadBuilderVersion": PAYLOAD_BUILDER_VERSION,
        "parserVersion": PARSER_VERSION,
        "rulesVersion": RULES_VERSION,
    }
