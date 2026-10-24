from parser_test_support.paths import INTERNAL
import json
import parser_core.battle_log_parser as parser
from parser_core.battle_log_parser import _canonical_num_table_skill_id, _collect_buff_labels, _collect_zone_effects, _effect_condition_failure, _is_arts_strength_damage_hit, _infer_skill_action_damage_element, _infer_skill_damage_element, _packet_mapping_stack_limit, _packet_numeric_effects, _rdps_registry_known_non_rdps_entry, _merge_loadout_snapshot, _parse_loadout_slot_snapshot, _parse_loadout_stats_snapshot, _repair_weapon_puton_loadout_groups, parse_raw_battle_log_text

def test_typed_empty_buff_root_is_exact_non_rdps_marker(monkeypatch) -> None:
    monkeypatch.setattr(
        parser,
        "_load_current_buff_roots",
        lambda: {
            "buff_test_marker": {
                "abilityEventAction": [], "buffEventAction": [],
                "attributeModifier": {"attributeModifiers": []},
                "damageModifier": [], "globalModifier": [], "healModifier": [],
            }
        },
    )
    record = {"event_key": "buff_test_marker", "raw_event_key": "buff_test_marker", "bb_keys": [], "bb_values": {}}
    entry = _rdps_registry_known_non_rdps_entry(record)
    assert entry is not None
    assert entry["proof_kind"] == "typed_root_structural"

def test_local_table_catalogs_cover_new_weapon_and_equipment() -> None:
    from parser_core.battle_log_parser import _load_equip_item_catalog, _load_weapon_catalog

    assert _load_weapon_catalog()["wpn_funnel_0019"]["weapon_name"] == "寒夜幽影"
    equip = _load_equip_item_catalog()["item_equip_t4_suit_spellburst_body_01"]
    assert equip["suit_name"] == "险关"
    assert equip["main_attr"]["value"] == 56
    assert _load_equip_item_catalog()["item_equip_t4_suit_usp02_body_03"]["suit_name"] == "长息"
    assert _load_equip_item_catalog()["item_equip_t4_suit_fire_natr01_hand_04"]["suit_name"] == "动火用"

def test_dynamic_blackboard_modify_events_are_preserved_as_observations() -> None:
    parsed = parse_raw_battle_log_text(
        "[10:00:00.100] BB_MODIFY_DYNAMIC seq=7 tick=11 inst=101 ownerId=202 "
        "owner=chr_0016_laevat skill=chr_0016_laevat_attack1 actionId=3 value=-3.6\n"
        "[10:00:00.200] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 "
        "eHP=900000 skill=chr_0016_laevat_attack1 hits=1 src=chr_0016_laevat "
        "tgt=eny_0051_rodin atk=chr_0016_laevat seg=0 shared=2 critFlag=0 critDmg=0.5000 "
        "dynBB=29:1,38:1 calcBB=2:duration_corrupt_final=7",
        include_rdps_debug=True,
    )
    assert parsed["dynamic_bb_events"] == [{
        "line_no": 1,
        "ts_ms": 36000100,
        "seq": 7,
        "tick": 11,
        "instance_id": "101",
        "owner_id": "202",
        "owner": "chr_0016_laevat",
        "skill_key": "chr_0016_laevat_attack1",
        "action_id": 3,
        "blackboard_key": None,
        "value": -3.6,
        "state_error": "missing_dynamic_identity",
    }]
    assert parsed["debug_hits"][0]["dynamic_bb_observations"] == []
    assert parsed["debug_hits"][0]["dynamic_bb_values"] == {29: 1.0, 38: 1.0}
    assert parsed["debug_hits"][0]["calc_bb_values"] == {2: {"duration_corrupt_final": 7.0}}
    assert parser._load_skill_item_metadata("chr_0016_laevat_ult_attack2")["dynamic_action_keys"][29] == "stopped1"

from parser_core.unified import rdps_totals_from_raw_report

def test_official_skilldata_catalog_resolves_only_direct_damage_templates() -> None:
    assert _infer_skill_damage_element("chr_0032_lizhiyan_attack1", "chr_0032_lizhiyan") == "natural"
    assert _infer_skill_damage_element("chr_0032_lizhiyan_attack1_projhit", "chr_0032_lizhiyan") == "natural"
    assert _infer_skill_action_damage_element("chr_0032_lizhiyan_normal_skill_abilityrange2", 17, 0) == "natural"
    assert _infer_skill_damage_element("chr_0035_liino_normal_skill_projhit", "chr_0035_liino") == "pulse"
    # Current official root has DamageAction 3: unit0 is Pulse/Hp, unit1
    # Pulse/Poise. Action2 has no direct DamageAction; no neighboring fallback.
    assert _infer_skill_action_damage_element("chr_0035_liino_normal_skill_projhit", 3, 0) == "pulse"
    assert _infer_skill_action_damage_element("chr_0035_liino_normal_skill_projhit", 2, 0) is None
    assert _infer_skill_action_damage_element("chr_0035_liino_normal_skill_projhit", 3, 1) is None
    assert _infer_skill_action_damage_element("chr_0035_liino_normal_skill_projhit", 3, 2) is None
    assert _infer_skill_damage_element("chr_0035_liino_unknown", "chr_0035_liino") is None
    assert _infer_skill_damage_element("chr_0035_liino_normal_skill", "chr_0035_liino") is None

def test_packaged_num_id_table_contains_pograni_fracture_alias() -> None:
    repo_root = INTERNAL
    table_path = repo_root / "data" / "local_tables" / "NumIdStrTable.json"
    payload = json.loads(table_path.read_text(encoding="utf-8"))

    assert payload["buff_id"]["dic"]["1211"] == "buff_physical_do_fracture"

def test_packaged_num_id_table_contains_typhoea_combo_debuff() -> None:
    repo_root = INTERNAL
    table_path = repo_root / "data" / "local_tables" / "NumIdStrTable.json"
    payload = json.loads(table_path.read_text(encoding="utf-8"))

    assert payload["buff_id"]["dic"]["3619"] == "buff_chr_0034_typhoea_combo_enemy_debuff"

def test_typhoea_condition_requires_observed_damage_decorate_mask() -> None:
    effect = {
        "condition": {
            'type': 'damage_decorate_mask', 'source': 'CheckDamageDecorateMask',
            'mask': 33554432, 'check': 'HasAll',
        }
    }

    assert _effect_condition_failure(
        effect,
        {"skill_key": "buff_common_natural_natural_triggered"},
    )['reason_group'] == 'condition_unobservable'
    assert _effect_condition_failure(effect, {'damage_decorate_mask': 33554432}) is None
    failure = _effect_condition_failure(effect, {'damage_decorate_mask': 128})
    assert failure['reason_group'] == 'condition_unsatisfied'

def test_current_typhoea_combo_debuff_exposes_exact_mask_condition() -> None:
    record = {
        "event_key": "buff_chr_0034_typhoea_combo_enemy_debuff",
        "raw_event_key": "3619",
        "source_character_key": "chr_0034_typhoea",
        "target_enemy_key": "eny_test",
        "bb_values": {"damage_up": 0.1, "slow_down": 0.4, "duration": 6},
        "bb_keys": ["damage_up", "slow_down", "duration"],
        "attr_mods": [],
    }

    effects = _collect_zone_effects(record)
    assert len(effects) == 1
    assert (effects[0]['zone'], effects[0]['rate'], effects[0]['bb_key']) == ('vuln_taken', 0.1, 'damage_up')
    assert effects[0]['rdps_whitelist_keys'] == ['buff_chr_0034_typhoea_combo_enemy_debuff']
    assert _effect_condition_failure(effects[0], {'damage_decorate_mask': 33554432}) is None
    assert _effect_condition_failure(effects[0], {'damage_decorate_mask': 128})['reason_group'] == 'condition_unsatisfied'

def test_legacy_registry_rows_require_current_typed_effects() -> None:
    rows = [
        {'event_key': 'buff_chr_0035_liino_spellenhance', 'source_character_key': 'chr_0035_liino', 'target_character_key': 'chr_0027_tangtang', 'bb_values': {'spellenhance_rate': 0.12}, 'bb_keys': ['spellenhance_rate'], 'attr_mods': []},
        {'event_key': 'buff_wpn_lance_0014_damageup', 'source_character_key': 'chr_0035_liino', 'target_character_key': 'chr_0027_tangtang', 'packet_mapping': {'weapon_id': 'wpn_lance_0014'}, 'bb_values': {'atk_up': 0.08}, 'bb_keys': ['atk_up'], 'attr_mods': []},
    ]
    liino, weapon = rows
    assert _collect_zone_effects(liino) == []
    assert not liino.get('rdps_unresolved_semantic_condition')
    assert _rdps_registry_known_non_rdps_entry(liino)['proof_kind'] == 'typed_root_structural'
    # The parent has no direct attribute modifier. Its current child UID
    # carries PulseEnhancedDmgIncrease; do not credit both parent and child.
    child = {'event_key': 'buff_common_affixes_enhance_pulse',
             'source_character_key': 'chr_0035_liino',
             'target_character_key': 'chr_0027_tangtang',
             'bb_values': {'rate': 0.12}, 'bb_keys': ['rate'], 'attr_mods': []}
    effects = _collect_zone_effects(child)
    assert [(e['zone'], e['element'], e['rate'], e['attr_type']) for e in effects] == [
        ('amp', 'pulse', 0.12, 66)]
    assert _collect_zone_effects(weapon) == [{
        'zone': 'atk', 'element': 'all', 'rate': 0.08, 'attr_type': 2,
        'bb_key': 'atk_up', 'semantic_source': 'typed_current_attributeModifier',
        'external_rdps_allowed': True, 'rdps_whitelist_keys': ['buff_wpn_lance_0014_damageup']}]

def test_arts_strength_damage_classifier_covers_all_physical_anomalies_but_not_no_guard() -> None:
    assert _is_arts_strength_damage_hit({"skill_key": "buff_physical_airborne"}) is False
    assert _is_arts_strength_damage_hit({"skill_key": "arbitrary_name", "arts_strength_damage_observed": True}) is True

def test_repair_weapon_puton_swaps_complete_weapon_state_and_propagates_to_battle() -> None:
    seraph = "chr_0011_seraph"
    lizhiyan = "chr_0032_lizhiyan"
    explosion = {
        "weapon_inst_id": "4633292003673374731",
        "weapon_template": "wpn_funnel_0008",
        "weapon_name": "爆破单元",
        "weapon_refine": 5,
        "weapon_refine_source": "source_skill",
        "gem_template": "gem_explosion",
        "weapon_source_skills": [{"skill_id": 2228, "level": 5, "potential_level": 5}],
        "weapon_refine_stats": [{"skill_id": 2228, "level": 5, "potential_level": 5}],
    }
    formation = {
        "weapon_inst_id": "4614961918380474406",
        "weapon_template": "wpn_funnel_0016",
        "weapon_name": "四二式·肃阵",
        "weapon_refine": 0,
        "weapon_refine_source": "source_skill",
        "gem_template": "gem_formation",
        "weapon_source_skills": [{"skill_id": 3629, "level": 0, "potential_level": 0}],
        "weapon_refine_stats": [{"skill_id": 3629, "level": 0, "potential_level": 0}],
    }

    initial_seraph = {"character_key": seraph, "potential": 5, "skill_int_ids": [101, 2228], **explosion}
    initial_lizhiyan = {"character_key": lizhiyan, "potential": 0, "skill_int_ids": [202, 3629], **formation}
    stale_receiver = {**initial_lizhiyan, **explosion, "potential": 0, "skill_int_ids": [202, 3629]}
    stale_receiver["weapon_source_skills"] = formation["weapon_source_skills"]
    stale_receiver["weapon_refine_stats"] = formation["weapon_refine_stats"]
    stale_swap_rows = {
        # This is the legacy client bug: both rows point to the receiver's new
        # instance, while each row still carries its old weapon source skill.
        seraph: dict(initial_seraph),
        lizhiyan: stale_receiver,
    }
    groups = [
        {"ts_ms": 1, "index": 1, "reason": "SC_SYNC_CHAR_BAG_INFO", "rows": {seraph: initial_seraph, lizhiyan: initial_lizhiyan}},
        {"ts_ms": 2, "index": 2, "reason": "SC_WEAPON_PUTON", "rows": stale_swap_rows},
        {"ts_ms": 3, "index": 3, "reason": "BATTLE_START", "rows": stale_swap_rows},
    ]

    repaired = _repair_weapon_puton_loadout_groups(groups, stale_swap_rows)
    battle_rows = groups[-1]["rows"]

    assert battle_rows[seraph]["weapon_inst_id"] == formation["weapon_inst_id"]
    assert battle_rows[seraph]["weapon_template"] == "wpn_funnel_0016"
    assert battle_rows[seraph]["gem_template"] == "gem_formation"
    assert battle_rows[seraph]["weapon_source_skills"][0] == {
        "skill_id": 3629,
        "level": 0,
        "potential_level": 5,
    }
    assert battle_rows[seraph]["skill_int_ids"] == [101, 3629]

    assert battle_rows[lizhiyan]["weapon_inst_id"] == explosion["weapon_inst_id"]
    assert battle_rows[lizhiyan]["weapon_template"] == "wpn_funnel_0008"
    assert battle_rows[lizhiyan]["gem_template"] == "gem_explosion"
    assert battle_rows[lizhiyan]["weapon_source_skills"][0] == {
        "skill_id": 2228,
        "level": 5,
        "potential_level": 0,
    }
    assert battle_rows[lizhiyan]["skill_int_ids"] == [202, 2228]
    assert repaired[seraph]["weapon_template"] == "wpn_funnel_0016"
    assert repaired[lizhiyan]["weapon_template"] == "wpn_funnel_0008"

def test_packet_mapping_effects_require_runtime_rate_value() -> None:
    record = {
        "event_key": "buff_test_static_rate",
        "raw_event_key": "999001",
        "packet_mapping": {
            "role": "effect",
            "effects": [{"zone": "atk", "element": "all", "bb_key": "atk_up", "rate": 0.5}],
        },
        "bb_values": {},
        "bb_keys": [],
    }

    assert _packet_numeric_effects(record) == []

def test_packet_mapping_stack_limit_prefers_runtime_max_stack() -> None:
    record = {
        "event_key": "buff_test_stack",
        "raw_event_key": "999002",
        "packet_mapping": {"role": "effect", "stack_limit": 5},
        "bb_values": {"max_stack": 2},
        "bb_keys": ["max_stack"],
    }

    assert _packet_mapping_stack_limit(record) == 2

def test_rdps_preflight_accepts_version_bound_typed_non_rdps_root() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.100] BUFF_START #1 id="buff_chr_0013_aglina_talent_0_effectbuff_Add" uid=1 owner=chr_0028_wulfa src=chr_0013_aglina dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: add=0.08",
            '[10:00:00.500] HP_V2 #2 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack1" actionId=6 damageUnitIndex=0 hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=1000 startMs=0 endMs=1000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="registry-non-rdps.log")
    preflight = parsed["rdps_preflight"]

    assert preflight["ok"] is True
    assert preflight["accepted_non_rdps_buff_count"] == 1
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is True

def test_rdps_preflight_blocks_unknown_external_buff_before_allocation() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.100] BUFF_START #1 id="buff_chr_9999_unknown_marker" uid=1 owner=chr_0028_wulfa src=chr_0013_aglina dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:00.500] HP_V2 #2 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack1" actionId=6 damageUnitIndex=0 hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=1000 startMs=0 endMs=1000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="unknown-external-preflight.log")
    preflight = parsed["rdps_preflight"]

    assert preflight["ok"] is False
    assert preflight["blocker_count"] == 1
    assert preflight["blockers"][0]["event_key"] == "buff_chr_9999_unknown_marker"
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

def test_verified_weapon_mapping_without_current_typed_effect_blocks_strict() -> None:
    content = "\n".join([
        '[10:00:00.100] BUFF_START #1 id="1699" uid=1 owner=chr_0004_pelica src=chr_0013_aglina dur=20.00 lifeT=20.00 passed=0.00 enh=1',
        '[10:00:00.500] HP_V2 #2 hit=114 cum=114 raw=114.00 packetFinalValue=114.0 pHP=5000 eHP=899886 skill="chr_0004_pelica_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
    ])
    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name='legacy-typed-effect-missing.log')
    assert parsed['rdps_preflight']['ok'] is False
    assert parsed['rdps_damage_basis']['rdps_strict_ok'] is False
    event = next(event for event in parsed['buff_events'] if event['uid'] == '1')
    assert event['zone_effects'] == []

def test_verified_weapon_mapping_without_runtime_value_blocks_strict() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] SQUAD size=2 members=[chr_0013_aglina chr_0004_pelica]",
            "[09:59:59.000] LOADOUT slot=0 char=chr_0013_aglina weaponTemplate=wpn_sword_0012 weaponLv=90 refine=5 break=0 attachedGem=0 equipInsts={} equips={} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0004_pelica weaponTemplate=wpn_funnel_0001 weaponLv=90 refine=5 break=0 attachedGem=0 equipInsts={} equips={} equipSuit={}",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.100] BUFF_START #1 id="1699" uid=1 owner=chr_0004_pelica src=chr_0013_aglina dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: atk_up=0.28 duration=20 max_stack=2",
            '[10:00:00.500] HP_V2 #2 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=899900 skill="chr_0004_pelica_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=1000 startMs=0 endMs=1000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="wpn-sword-0012-missing-runtime.log")

    assert parsed["rdps_preflight"]["ok"] is False
    assert parsed["rdps_preflight"]["blockers"][0]["event_key"] == "buff_wpn_sword_0012_atk_up"
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

def test_unresolved_formula_weapon_mapping_blocks_strict() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] SQUAD size=2 members=[chr_0013_aglina chr_0004_pelica]",
            "[09:59:59.000] LOADOUT slot=0 char=chr_0013_aglina weaponTemplate=wpn_sword_0013 weaponLv=90 refine=5 break=0 attachedGem=0 equipInsts={} equips={} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0004_pelica weaponTemplate=wpn_funnel_0001 weaponLv=90 refine=5 break=0 attachedGem=0 equipInsts={} equips={} equipSuit={}",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.100] BUFF_START #1 id="1812" uid=1 owner=chr_0004_pelica src=chr_0013_aglina dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: atk_up=0.28 atk_up_add=0.14 atk_up_mult=0.07 duration=20",
            '[10:00:00.500] HP_V2 #2 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=899900 skill="chr_0004_pelica_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=1000 startMs=0 endMs=1000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="wpn-sword-0013-unresolved.log")

    assert parsed["rdps_preflight"]["ok"] is False
    assert parsed["rdps_preflight"]["blockers"][0]["event_key"] == "buff_wpn_sword_0013_atk_up"
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

def test_legacy_formula_buff_value_requires_current_typed_effect() -> None:
    content = "\n".join([
        '[10:00:00.100] BUFF_START #1 id="1812" uid=1 owner=chr_0004_pelica src=chr_0013_aglina dur=20.00 lifeT=20.00 passed=0.00 enh=1',
        '[10:00:00.100] BB[1]: atk_up=0.28 atk_up_add=0.14 atk_up_mult=0.07 consume_layer=2 duration=20',
        '[10:00:00.500] HP_V2 #2 hit=114 cum=114 raw=114.00 packetFinalValue=114.0 pHP=5000 eHP=899886 skill="chr_0004_pelica_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
    ])
    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name='legacy-formula-effect-missing.log')
    assert parsed['rdps_preflight']['ok'] is False
    assert parsed['rdps_damage_basis']['rdps_strict_ok'] is False
    event = next(event for event in parsed['buff_events'] if event['uid'] == '1')
    assert event['zone_effects'] == []

def test_merge_loadout_snapshot_merges_incremental_equips_by_slot() -> None:
    base = {
        "character_key": "chr_0017_yvonne",
        "equips": [
            {"slot": 0, "item_id": "old_hand"},
            {"slot": 1, "item_id": "old_body"},
            {"slot": 2, "item_id": "old_edc"},
            {"slot": 3, "item_id": "old_tail"},
        ],
    }
    update = {
        "character_key": "chr_0017_yvonne",
        "equips": [
            {"slot": 2, "item_id": "new_edc"},
        ],
    }

    merged = _merge_loadout_snapshot(base, update)

    assert [(item["slot"], item["item_id"]) for item in merged["equips"]] == [
        (0, "old_hand"),
        (1, "old_body"),
        (2, "new_edc"),
        (3, "old_tail"),
    ]

def test_partial_equipment_update_does_not_invent_another_slot_from_suit_count() -> None:
    base = _parse_loadout_slot_snapshot(
        "[10:00:00.000] LOADOUT slot=0 char=chr_0017_yvonne "
        "weaponTemplate=wpn_pistol_0010 weaponLv=0 refine=0 break=0 "
        "equips={[0]=item_equip_t4_suit_criti01_hand_03 "
        "[1]=item_equip_t4_suit_criti01_body_02 "
        "[2]=item_equip_t4_suit_criti01_edc_03} "
        "equipSuit={[suit_criti01]=3}"
    )
    update = _parse_loadout_slot_snapshot(
        "[10:00:01.000] LOADOUT slot=0 char=chr_0017_yvonne "
        "weaponTemplate=wpn_pistol_0010 weaponLv=0 refine=0 break=0 "
        "equips={[2]=item_equip_t4_suit_heal01_edc_03} "
        "equipSuit={[suit_criti01]=3}"
    )

    assert base is not None
    assert update is not None
    merged = _merge_loadout_snapshot(base, update)

    assert [(item["slot"], item["item_id"]) for item in merged["equips"]] == [
        (0, "item_equip_t4_suit_criti01_hand_03"),
        (1, "item_equip_t4_suit_criti01_body_02"),
        (2, "item_equip_t4_suit_heal01_edc_03"),
    ]

def test_ambiguous_third_skill_does_not_override_explicit_loadout_refine() -> None:
    slot = _parse_loadout_slot_snapshot(
        "[10:00:00.000] LOADOUT slot=3 char=chr_0011_seraph "
        "weaponTemplate=wpn_funnel_0008 weaponLv=0 refine=5 break=0 "
        "equips={} equipSuit={}"
    )
    stats = _parse_loadout_stats_snapshot(
        "[10:00:00.000] LOADOUT_STATS slot=3 char=chr_0011_seraph "
        "weaponTemplate=wpn_funnel_0008 weaponBaseAtk=490 weaponBaseAtkLv1=50 weaponBaseAtkMax=490 "
        "weaponRefineStats={1391:level=5:potentialLv=5:bb={mainattr=71};"
        "2253:level=9:potentialLv=5:bb={atk=0,physpell=78};"
        "2228:level=4:potentialLv=5:bb={duration=15,lv=4,second_attr_up=0.16,spell_damage_taken_up=0.144}} "
        "weaponSourceSkills={1391:level=5:potentialLv=5:bb={mainattr=71};"
        "2253:level=9:potentialLv=5:bb={atk=0,physpell=78};"
        "2228:level=4:potentialLv=5:bb={duration=15,lv=4,second_attr_up=0.16,spell_damage_taken_up=0.144}}"
    )

    assert slot is not None
    assert stats is not None
    assert stats["weapon_refine"] is None
    merged = _merge_loadout_snapshot(slot, stats)
    assert merged["weapon_refine"] == 5
    assert merged["weapon_refine_source"] == "loadout"
    assert _merge_loadout_snapshot(merged, slot)["weapon_refine"] == 5

def test_collect_buff_labels_distinguishes_fragile_from_vuln_taken() -> None:
    fragile_record = {
        "event_key": "buff_chr_0013_aglina_ultimate_spell_vulnerable",
        "source_character_key": "chr_0013_aglina",
        "target_enemy_key": "eny_0051_rodin",
        "bb_keys": ["rate"],
        "bb_values": {"rate": 0.33},
        "attr_mods": [{"attr_type": "85", "bb_key": "rate", "use_key": "1", "value": None}],
        "attr_types": ["85"],
    }
    vuln_record = {
        "event_key": "buff_common_pulse_pulse_conduct_triggered_do",
        "source_character_key": "chr_0004_pelica",
        "target_enemy_key": "eny_0051_rodin",
        "bb_keys": ["final_spell_resistance_decrease"],
        "bb_values": {"final_spell_resistance_decrease": 0.31},
        "attr_mods": [],
        "attr_types": [],
    }

    assert "脆弱" in _collect_buff_labels(fragile_record)
    assert "易伤" not in _collect_buff_labels(fragile_record)
    assert "承伤易伤" in _collect_buff_labels(vuln_record)

def test_collect_zone_effects_builds_check_hp_condition_from_semantics() -> None:
    record = {
        "event_key": "buff_chr_0005_chen_potential_1",
        "source_character_key": "chr_0005_chen",
        "target_character_key": "chr_0005_chen",
        "bb_keys": ["hp_remain", "extra_dmg"],
        "bb_values": {"hp_remain": 0.5, "extra_dmg": 0.2},
        "attr_mods": [],
    }

    effects = _collect_zone_effects(record)

    assert effects == [
        {
            "zone": "dmg_inc",
            "element": "all",
            "rate": 0.2,
            "condition": {
                "type": "target_hp_compare",
                "source": "CheckHp",
                "compare": "LT",
                "is_ratio": True,
                "threshold": 0.5,
                "threshold_key": "hp_remain",
                "subject_side": "defender",
            },
            "semantic_source": "typed_current_damageModifier",
            "bb_key": "extra_dmg",
            "recipient_side": "attacker",
            'external_rdps_allowed': False, 'rdps_whitelist_keys': [],
        }
    ]

def test_collect_zone_effects_builds_check_damage_type_condition_from_decoded_detail() -> None:
    record = {
        "event_key": "buff_chr_0011_seraph_talent_1_crystup",
        "source_character_key": "chr_0011_seraph",
        "target_enemy_key": "eny_0051_rodin",
        "bb_keys": ["cryst_up"],
        "bb_values": {"cryst_up": 0.3},
        "attr_mods": [],
    }

    effects = _collect_zone_effects(record)

    assert len(effects) == 1
    assert (effects[0]['zone'], effects[0]['element'], effects[0]['rate']) == ('vuln_taken', 'cryst', 0.3)
    assert effects[0]['rdps_whitelist_keys'] == ['buff_chr_0011_seraph_talent_1_crystup']
    assert _effect_condition_failure(effects[0], {'damage_element': 'cryst'}) is None
    assert _effect_condition_failure(effects[0], {'damage_element': 'fire'})['reason_group'] == 'condition_unsatisfied'

def test_parse_raw_battle_log_text_gates_check_hp_damage_scale() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0 official=1",
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0005_chen_potential_1" uid=1 owner=chr_0005_chen src=chr_0005_chen dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: hp_remain=0.5 extra_dmg=0.2",
            '[10:00:00.100] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900 skill="chr_0005_chen_attack1" hits=1 src=chr_0005_chen tgt=eny_0051_rodin atk=chr_0005_chen seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.200] HP_V2 #3 hit=500 cum=600 raw=500.00 pHP=5000 eHP=400 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.300] HP_V2 #4 hit=100 cum=700 raw=100.00 pHP=5000 eHP=300 skill="chr_0005_chen_attack1" hits=2 src=chr_0005_chen tgt=eny_0051_rodin atk=chr_0005_chen seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=2 source=ChallengeComplete elapsedMs=1000 startMs=0 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="check-hp-condition.log")
    chen_hits = [hit for hit in parsed["debug_hits"] if hit["character_key"] == "chr_0005_chen"]

    assert all("target_enemy_hp_ratio_before" not in hit for hit in chen_hits)
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False
    assert any(row["reason"] == "unresolved_effect_condition"
               for row in parsed["rdps_preflight"]["blockers"])

def test_parse_raw_battle_log_text_gates_check_damage_type_damage_scale() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0 official=1",
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_talent_1_crystup" uid=1 owner=eny_0051_rodin src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: duration=2 cryst_up=0.3",
            '[10:00:00.100] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900 skill="unknown_proc_damage" hits=1 src=chr_9999_dummy tgt=eny_0051_rodin atk=chr_9999_dummy seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.100] DPD_RAW #2 probe=2 calc=100.0000 atkScale=1.0000 blocked=0 damageType=0x2 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000]',
            '[10:00:00.200] HP_V2 #3 hit=130 cum=230 raw=130.00 pHP=5000 eHP=770 skill="unknown_proc_damage" hits=2 src=chr_9999_dummy tgt=eny_0051_rodin atk=chr_9999_dummy seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.200] DPD_RAW #3 probe=3 calc=130.0000 atkScale=1.0000 blocked=0 damageType=0x4 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.3000,1.0000,1.0000,1.0000,1.0000]',
            "[10:00:01.000] GAME_TIMER_END seq=2 source=ChallengeComplete elapsedMs=1000 startMs=0 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="check-damage-type-condition.log")
    debug_hits = parsed["debug_hits"]

    assert all(hit["damage_element"] is None for hit in debug_hits)
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False
    assert not any(zone.get("external_rate") for hit in debug_hits for zone in hit["zones"])

def test_parse_raw_battle_log_text_uses_dpd_damage_type_as_element_fallback() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0 official=1",
            '[10:00:00.000] BUFF_START #1 id="buff_fire_taken_probe" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: damage_taken_up_fire=0.2 duration=2",
            '[10:00:00.500] HP_V2 #2 hit=120 cum=120 raw=120.00 pHP=5000 eHP=900000 skill="unknown_proc_damage" hits=1 src=chr_9999_dummy tgt=eny_0051_rodin atk=chr_9999_dummy seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] DPD_RAW #2 probe=2 calc=120.0000 atkScale=1.0000 blocked=0 damageType=0x2 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.2000,1.0000,1.0000,1.0000,1.0000]',
            "[10:00:01.000] GAME_TIMER_END seq=2 source=ChallengeComplete elapsedMs=1000 startMs=0 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="dpd-damage-type-fallback.log")
    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    rdps_by_key = {
        contribution["character_key"]: contribution["value"]
        for contribution in damage_event["rdps_contributions"]
    }

    assert damage_event["damage_element"] is None
    assert rdps_by_key == {"chr_9999_dummy": 120.0}
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

def test_parse_raw_battle_log_text_prefers_game_timer_window() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] GAME_TIMER_START seq=1 source=ChallengeStart self=0000000000000000 msg=0000000000000000 startMs=123 expireMs=0 prepareSeconds=0",
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:10.000] HP_V2 #2 hit=200 cum=300 raw=200.00 pHP=5000 eHP=899800 skill="chr_0027_tangtang_attack1" hits=2 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:01:05.000] GAME_TIMER_END seq=1 source=ChallengeComplete self=0000000000000000 msg=0000000000000000 elapsedMs=66000 startMs=123 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-10-000",
    )

    assert parsed["battle"]["duration_ms"] == 66000
    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["timeline_zero_source"] == "game_timer_start"
    assert parsed["battle"]["timer_start_seen"] is True
    assert parsed["battle"]["timer_end_seen"] is True
    assert parsed["battle"]["timer_start_inferred"] is False
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 1000

def test_parse_raw_battle_log_text_ignores_synthetic_battle_state_timer() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=BattleOpModifyBattleState startMs=1 expireMs=0 official=0",
            '[10:00:01.000] SKILL_CAST_START seq=2 startMs=1000 inst=1 owner=chr_0027_tangtang skill=chr_0027_tangtang_skill_2038',
            '[10:00:02.000] HP_V2 #1 hit=50 cum=50 raw=50.00 pHP=5000 eHP=900000 skill="skill_793" hits=1 src=eny_0051_rodin tgt=chr_0004_pelica atk=eny_0051_rodin seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:04.000] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:09.000] HP_V2 #3 hit=150 cum=250 raw=150.00 pHP=5000 eHP=899750 skill="chr_0027_tangtang_attack1" hits=2 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:10.000] GAME_TIMER_END seq=1 source=BattleOpModifyBattleState elapsedMs=10000 startMs=1 expireMs=0 sane=1 official=0",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="synthetic-timer.log")

    assert parsed["battle"]["time_source"] == "party_action_window"
    assert parsed["battle"]["timeline_zero_source"] == "party_action_window"
    assert parsed["battle"]["timer_start_seen"] is False
    assert parsed["battle"]["timer_end_seen"] is False
    assert parsed["battle"]["duration_ms"] == 8000
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 3000

def test_parse_raw_battle_log_text_accepts_standard_packet_battle_state_timer() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:04.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:10.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=9000 startMs=1000 endMs=10000 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="packet-timer.log")

    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["duration_ms"] == 9000
    assert parsed["battle"]["timeline_zero_source"] == "game_timer_start"
    assert parsed["battle"]["timer_start_inferred"] is False
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 4000

def test_parse_raw_battle_log_text_uses_wall_elapsed_for_packet_battle_state_timer() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:09.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:12.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:13.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=9000 startMs=1000 endMs=10000 expireMs=0 sane=1 official=1 packetElapsedMs=9000 wallElapsedMs=13000",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="packet-wall-window.log")

    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["duration_ms"] == 13000
    assert parsed["battle"]["clear_flag"] is True
    assert parsed["battle"]["total_damage"] == 200
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[-1]["ts_ms_from_start"] == 12000

def test_parse_raw_battle_log_text_prefers_official_timer_pass_time() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard007_s challengeStartTs=1000 challengeExpireTs=61000",
            "[10:00:02.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:10.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:01:23.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:01:23.945] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard007_s isPass=1 passTime=83945",
            "[10:01:24.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=82000 startMs=1000 endMs=83000 expireMs=0 sane=1 official=1 packetElapsedMs=64000",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-timer.log")

    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["duration_ms"] == 83945
    assert parsed["battle"]["timeline_zero_source"] == "official_timer_start"
    assert parsed["battle"]["timer_start_seen"] is True
    assert parsed["battle"]["timer_end_seen"] is True
    assert parsed["battle"]["official_timer_start_seen"] is True
    assert parsed["battle"]["official_timer_end_seen"] is True
    assert parsed["battle"]["timer_start_inferred"] is False
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 10000

def test_parse_raw_battle_log_text_uses_official_timer_start_without_timer_end() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard007_s challengeStartTs=1000",
            '[10:00:05.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-start-only.log")

    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["timeline_zero_source"] == "official_timer_start"
    assert parsed["battle"]["duration_ms"] == 5000
    assert parsed["battle"]["timer_start_seen"] is True
    assert parsed["battle"]["timer_end_seen"] is False
    assert parsed["battle"]["official_timer_start_seen"] is True
    assert parsed["battle"]["official_timer_end_seen"] is False
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 5000

def test_packet_phase_end_without_official_completion_stays_unfinished() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard007_s challengeStartTs=1000",
            "[10:00:00.100] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:02.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:04.000] HP_V2 #2 hit=200 cum=300 raw=200.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:05.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=5000 startMs=1000 endMs=6000 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-start-game-end.log")

    assert parsed["battle"]["duration_ms"] == 4000
    assert parsed["battle"]["timer_start_seen"] is True
    assert parsed["battle"]["timer_end_seen"] is False
    assert parsed["battle"]["official_timer_start_seen"] is True
    assert parsed["battle"]["official_timer_end_seen"] is False
    assert parsed["battle"]["clear_flag"] is False

def test_parse_raw_battle_log_text_keeps_hits_until_official_timer_end_when_pass_time_is_shorter_than_wall_clock() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=dung02_bossrush02_03 challengeStartTs=1000",
            '[10:00:02.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0078_nefarp1 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:03.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=3000 startMs=0 endMs=3000 expireMs=0 sane=1 official=1",
            "[10:00:04.000] GAME_TIMER_START seq=2 source=PacketBattleState startMs=3000 expireMs=0 official=1",
            '[10:00:07.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=5000 eHP=300 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0079_nefarp2 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:09.000] HP_V2 #3 hit=300 cum=300 raw=300.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0079_nefarp2 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:10.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=dung02_bossrush02_03 isPass=1 passTime=8000",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-multiphase-wall-drift.log")

    assert parsed["battle"]["duration_ms"] == 8000
    assert parsed["battle"]["boss_key"] == "eny_0079_nefarp2"
    assert parsed["battle"]["clear_flag"] is True
    assert parsed["battle"]["total_damage"] == 600
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert [event["value"] for event in damage_events] == [100, 200, 300]

def test_parse_raw_battle_log_text_resolves_contingency_contract_context() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_contract001 source=SC_SELF_SCENE_INFO",
            "[10:00:00.500] CONTRACT_TAGS dungeonId=indie_contract001 source=SC_CONTINGENCY_CONTRACT_TAGS_SYNC tagIds=[100501,101301,102801,100201,102001,102101,900101,101001,100901,100601] score=10",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0090_wgabyss atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="contingency-contract-context.log")

    assert parsed["battle"]["dungeon_key"] == "indie_group_ccdg"
    assert parsed["battle"]["dungeon_name"] == "危机合约"
    assert parsed["battle"]["boss_key"] == "eny_0090_wgabyss"
    assert parsed["battle"]["boss_name"] == "破潮之像"
    assert parsed["battle"]["clear_flag"] is True
    assert parsed["battle"]["contract_tag_score"] == 10
    assert [tag["tag_id"] for tag in parsed["battle"]["contract_tags"]] == [
        100501,
        101301,
        102801,
        100201,
        102001,
        102101,
        900101,
        101001,
        100901,
        100601,
    ]
    assert parsed["battle"]["contract_tags"][0]["score"] == 1
    assert parsed["battle"]["contract_tags"][0]["icon"] == "icon_activity_contract_tag_207"

def test_parse_raw_battle_log_text_keeps_war_echo_highest_stage_identity() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower008_ex source=SC_SELF_SCENE_INFO",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0114_jzmking atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="war-echo-context.log")

    assert parsed["battle"]["dungeon_key"] == "indie_battletower008_ex"
    assert parsed["battle"]["dungeon_name"] == "战争简史·残酷"

def test_parse_raw_battle_log_text_keeps_war_echo_lower_difficulty_out_of_highest_board() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower008_s source=SC_SELF_SCENE_INFO",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0114_jzmking atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="war-echo-lower-context.log")

    assert parsed["battle"]["dungeon_key"] == "indie_battletower008_s"
    assert parsed["battle"]["dungeon_name"] == "战争简史·困难"

def test_parse_raw_battle_log_text_uses_selected_contract_tag_score_sum() -> None:
    content = "\n".join(
        [
            "[13:23:28.718] DUNGEON_CONTEXT dungeonId=indie_contract001 source=CS_ENTER_DUNGEON",
            "[13:23:26.638] CONTRACT_TAGS dungeonId=indie_contract001 source=CS_CONTINGENCY_CONTRACT_SET_TAGS tagIds=[102801,100201,102102]",
            "[13:26:40.542] CONTRACT_TAGS dungeonId=indie_contract001 source=SC_CONTINGENCY_CONTRACT_BATTLE_RESULT tagIds=[102801,100201,102102] score=4",
            "[13:26:40.542] CONTRACT_TAGS dungeonId=indie_contract001 source=SC_CONTINGENCY_CONTRACT_TAGS_SYNC tagIds=[102801,100201,102102] score=10",
            '[13:26:41.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0090_wgabyss atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="contingency-contract-score.log")

    assert parsed["battle"]["contract_tag_score"] == 4
    assert [(tag["tag_id"], tag["score"]) for tag in parsed["battle"]["contract_tags"]] == [
        (102801, 1),
        (100201, 1),
        (102102, 2),
    ]

def test_parse_raw_battle_log_text_recomputes_contract_score_from_current_catalog() -> None:
    content = "\n".join(
        [
            "[15:42:10.000] DUNGEON_CONTEXT dungeonId=indie_contract001 source=SC_SELF_SCENE_INFO",
            "[15:46:12.000] CONTRACT_TAGS dungeonId=indie_contract001 source=SC_CONTINGENCY_CONTRACT_TAGS_SYNC tagIds=[101101,102201,102302,100003,900101,101501] score=46",
            '[15:46:12.100] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0090_wgabyss atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="contingency-contract-catalog-score.log")

    assert parsed["battle"]["contract_tag_score"] == 10
    assert [(tag["tag_id"], tag["name"], tag["score"]) for tag in parsed["battle"]["contract_tags"]] == [
        (101101, "改写：愈合", 1),
        (102201, "环境：再构成", 2),
        (102302, "改写：奔腾", 2),
        (100003, "环境：过速", 3),
        (900101, "改写：活性", 1),
        (101501, "改写：遗毒", 1),
    ]

def test_parse_raw_battle_log_text_keeps_known_enemy_over_context_hint() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung02_bossrush02_03 source=SC_SELF_SCENE_INFO",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="known-boss-context.log")

    assert parsed["battle"]["boss_key"] == "eny_0051_rodin"
    assert parsed["battle"]["boss_key"] != "eny_0079_nefarp2"

def test_parse_raw_battle_log_text_uses_official_timer_game_id_before_enemy_guess() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard013_s challengeStartTs=1000 challengeExpireTs=61000",
            '[10:00:10.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0059_erhound atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:20.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0059_erhound atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:01:00.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard013_s isPass=1 passTime=60000",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-timer-game-id.log")

    assert parsed["battle"]["dungeon_key"] == "indie_hard013_s"
    assert parsed["battle"]["dungeon_name"] == "沉寂视界·苦难"
    assert parsed["battle"]["duration_ms"] == 60000

def test_parse_raw_battle_log_text_resolves_v1d3_hard_official_timer_game_id() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard018_s challengeStartTs=1000 challengeExpireTs=61000",
            '[10:00:10.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0082_hsbear_hdg018 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:20.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0082_hsbear_hdg018 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:40.440] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard018_s isPass=1 passTime=39440",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-timer-v1d3-hard.log")

    assert parsed["battle"]["dungeon_key"] == "indie_hard018_s"
    assert parsed["battle"]["dungeon_name"] == "忿鼓咆声·苦难"
    assert parsed["battle"]["boss_key"] == "eny_0082_hsbear_hdg018"
    assert parsed["battle"]["duration_ms"] == 39440

def test_parse_raw_battle_log_text_resolves_v1d3_normal_official_timer_game_id() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard018 challengeStartTs=1000 challengeExpireTs=61000",
            '[10:00:10.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0082_hsbear atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:40.440] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard018 isPass=1 passTime=39440",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="official-timer-v1d3-normal.log")

    assert parsed["battle"]["dungeon_key"] == "indie_hard018"
    assert parsed["battle"]["dungeon_name"] == "忿鼓咆声"

def test_parse_raw_battle_log_text_caps_final_boss_overkill_damage() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=200 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #2 hit=500 cum=500 raw=500.00 pHP=5000 eHP=0 skill="chr_0004_pelica_attack1" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content)

    assert parsed["battle"]["total_damage"] == 300
    assert parsed["battle"]["clear_flag"] is True
    by_key = {participant["character_key"]: participant for participant in parsed["participants"]}
    assert by_key["chr_0027_tangtang"]["total_damage"] == 100
    assert by_key["chr_0004_pelica"]["total_damage"] == 200
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[-1]["value"] == 200

def test_parse_raw_battle_log_text_groups_visual_multi_hit_for_participant_max_hit() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=100 expireMs=0",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0016_laevat_ult_attack4" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.080] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0016_laevat_ult_attack4" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] GAME_TIMER_END seq=1 source=OnSrvComplete self=0 elapsedMs=2000 startMs=100 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="visual-max-hit.log")
    participant = next(item for item in parsed["participants"] if item["character_key"] == "chr_0016_laevat")

    assert participant["max_hit"] == 200

def test_parse_raw_battle_log_text_ignores_hits_outside_game_timer_window() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #2 hit=2000 cum=2000 raw=2000.00 pHP=5000 eHP=898000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:10.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=100 expireMs=0",
            '[10:00:11.000] HP_V2 #3 hit=4000 cum=4000 raw=4000.00 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:13.000] HP_V2 #4 hit=5000 cum=5000 raw=5000.00 pHP=5000 eHP=895000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:15.000] GAME_TIMER_END seq=1 source=OnSrvComplete self=0 elapsedMs=5000 startMs=100 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content)

    assert parsed["battle"]["duration_ms"] == 5000
    assert parsed["battle"]["total_damage"] == 9000
    assert parsed["battle"]["total_dps"] == 1800.0
    assert parsed["participants"][0]["total_damage"] == 9000
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert [event["value"] for event in damage_events] == [4000, 5000]

def test_legacy_enemy_buff_without_current_typed_effect_stays_unknown_outside_window() -> None:
    content = "\n".join([
        '[10:00:01.000] BUFF_START #1 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=old owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
        '[10:00:10.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=100 expireMs=0',
        '[10:00:11.000] HP_V2 #2 hit=1000 cum=1000 raw=1000.00 pHP=5000 eHP=899000 skill="chr_0028_wulfa_attack1" actionId=0 damageUnitIndex=0 hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        '[10:00:12.000] BUFF_START #2 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=new owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
        '[10:00:13.000] HP_V2 #3 hit=1000 cum=2000 raw=1000.00 pHP=5000 eHP=898000 skill="chr_0028_wulfa_attack1" actionId=0 damageUnitIndex=0 hits=2 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        '[10:00:15.000] GAME_TIMER_END seq=1 source=OnSrvComplete self=0 elapsedMs=5000 startMs=100 expireMs=0 sane=1',
    ])
    parsed = parse_raw_battle_log_text(content)
    events = [event for event in parsed['buff_events'] if event['event_key'] == 'buff_chr_0013_aglina_ultimate_spell_vulnerable']
    assert len(events) == 2
    assert all(event['zone_effects'] == [] for event in events)
    assert parsed['rdps_damage_basis']['rdps_strict_ok'] is False

def test_parse_raw_battle_log_text_can_infer_timer_start_from_end_elapsed() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:01:06.000] GAME_TIMER_END seq=1 source=ChallengeComplete self=0 elapsedMs=66000 startMs=0 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content)

    assert parsed["battle"]["duration_ms"] == 66000
    assert parsed["battle"]["time_source"] == "game_timer"
    assert parsed["battle"]["timeline_zero_source"] == "timer_end_inferred"
    assert parsed["battle"]["timer_start_seen"] is False
    assert parsed["battle"]["timer_end_seen"] is True
    assert parsed["battle"]["official_timer_start_seen"] is False
    assert parsed["battle"]["official_timer_end_seen"] is False
    assert parsed["battle"]["timer_start_inferred"] is True
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["ts_ms_from_start"] == 0

def test_parse_raw_battle_log_text_builds_structured_payload() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] ATTR_MOD buff="buff_equipsuit_critsuitatk_01" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0500 bbKey="atk_up"',
            '[10:00:00.500] BUFF_START #2 id="buff_equipsuit_critsuitatk_01" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:00.500]   BB[4]: atk_up=0.05 =0 crit_up2=0.05 =0',
            '[10:00:00.600] ATTR_MOD buff="buff_common_dash" i=0 attrType=14 modType=0 formula=0 useKey=0 val=2.0000 bbKey=""',
            '[10:00:00.600] BUFF_START #3 id="buff_common_dash" uid=2 owner=chr_0027_tangtang src=chr_0027_tangtang dur=0.33 lifeT=0.33 passed=0.00 enh=1',
            '[10:00:00.600]   BB[2]: dodgeSkillId=0 common_character_perfect_dodge=0',
            '[10:00:01.000] HP_V2 #3 hit=250 cum=350 raw=250.00 pHP=5000 eHP=899750 skill="chr_0027_tangtang_attack1" hits=2 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:01.750] BUFF_END #4 id="buff_equipsuit_critsuitatk_01" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=5.00 lifeT=3.75 passed=1.25 enh=1',
            '[10:00:02.000] HP_V2 #4 hit=300 cum=300 raw=300.00 pHP=4800 eHP=899450 skill="chr_0004_pelica_attack1" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="sample.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    assert parsed["battle"]["boss_key"] == "eny_0051_rodin"
    assert parsed["battle"]["boss_name"] == "“碾骨之拳”罗丹"
    assert parsed["battle"]["dungeon_key"] == "unknown_dungeon"
    assert parsed["battle"]["dungeon_name"] == "未知副本"
    assert parsed["battle"]["dungeon_context_id"] is None
    assert parsed["battle"]["dungeon_identity_source"] == "missing_dungeon_context"
    assert parsed["battle"]["duration_ms"] == 2000
    assert parsed["battle"]["total_damage"] == 650
    assert parsed["battle"]["source_file_name"] == "sample.log"

    roster_names = [entry["character_name"] for entry in parsed["battle"]["roster"]]
    assert roster_names == ["汤汤", "佩丽卡"]

    assert parsed["participants"][0]["character_name"] == "汤汤"
    assert parsed["participants"][0]["total_damage"] == 350
    assert parsed["participants"][0]["crit_rate"] == 0.5
    assert parsed["participants"][0]["rdps"] == parsed["participants"][0]["dps"]

    buff_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]
    assert len(buff_events) == 1
    assert buff_events[0]["event_key"] == "buff_equipsuit_critsuitatk_01"
    assert buff_events[0]["event_name"] == "攻击提升 / 暴击"
    assert buff_events[0]["duration_ms"] == 1250
    assert buff_events[0]["target_player_key"] == "chr_0027_tangtang"
    assert buff_events[0]["target_enemy_key"] is None

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["event_name"] == "崩你脑壳！"
    assert damage_events[0]["event_group_key"] is not None
    assert damage_events[0]["event_group_key"] == damage_events[1]["event_group_key"]
    assert damage_events[2]["event_group_key"] != damage_events[0]["event_group_key"]
    assert damage_events[0]["rdps_contributions"] == [
        {
            "character_key": "chr_0027_tangtang",
            "character_name": "汤汤",
            "value": 100.0,
        }
    ]

    skill_stats = parsed["role_skill_stats"]
    tangtang_stats = [item for item in skill_stats if item["character_key"] == "chr_0027_tangtang"]
    assert tangtang_stats[0]["cast_count"] == 1
    assert tangtang_stats[0]["total_damage"] == 350
    assert tangtang_stats[0]["skill_name"] == "崩你脑壳！"

def test_parse_raw_battle_log_text_uses_packet_dungeon_context_for_high_difficulty_stage() -> None:
    for stage, name in [('indie_hard008_s', '怨憎雾海·苦难'), ('indie_hard026_s', '兽影生杀·苦难'), ('indie_hard026', '兽影生杀'), ('indie_hard027_s', '暗曜白霆·苦难'), ('indie_hard027', '暗曜白霆'), ('indie_hard028_s', '沛然轰鸣·苦难'), ('indie_hard028', '沛然轰鸣'), ('indie_hard029_s', '三角定位·苦难'), ('indie_hard029', '三角定位')]:
        content = "\n".join(
            [
                f"[10:00:00.000] DUNGEON_CONTEXT dungeonId={stage} source=SC_SELF_SCENE_INFO scene=210 isReward=1 isCalc=0 isPass=0",
                '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=733631 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0085_hsrogue_hard atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            ]
        )

        parsed = parse_raw_battle_log_text(content)

        assert parsed["battle"]["dungeon_key"] == stage
        assert parsed["battle"]["dungeon_name"] == name
        assert parsed["battle"]["dungeon_context_id"] == stage
        assert parsed["battle"]["dungeon_identity_source"] == "dungeon_context"

def test_parse_raw_battle_log_text_uses_official_game_id_even_when_boss_belongs_elsewhere() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower004_ex challengeStartTs=1000",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content)

    assert parsed["battle"]["dungeon_key"] == "indie_battletower004_ex"
    assert parsed["battle"]["dungeon_name"] == "斧柄纪年·残酷"
    assert parsed["battle"]["dungeon_context_id"] == "indie_battletower004_ex"
    assert parsed["battle"]["dungeon_identity_source"] == "dungeon_context"
    assert parsed["battle"]["boss_key"] == "eny_0051_rodin"

def test_parse_raw_battle_log_text_exposes_official_stage_before_first_hit() -> None:
    parsed = parse_raw_battle_log_text(
        "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower004_ex source=SC_SELF_SCENE_INFO"
    )

    assert parsed["battle"]["dungeon_key"] == "indie_battletower004_ex"
    assert parsed["battle"]["dungeon_name"] == "斧柄纪年·残酷"
    assert parsed["battle"]["boss_key"] == "unknown_boss"
    assert parsed["participants"] == []

def test_parse_raw_battle_log_text_uses_generated_activity_child_name() -> None:
    parsed = parse_raw_battle_log_text(
        "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_takestwo007 source=SC_SELF_SCENE_INFO"
    )

    assert parsed["battle"]["dungeon_key"] == "dung01_takestwo007"
    assert parsed["battle"]["dungeon_name"] == "什么！还有动物！"
    assert parsed["battle"]["dungeon_context_id"] == "dung01_takestwo007"
    assert parsed["participants"] == []

def test_parse_raw_battle_log_text_does_not_guess_dungeon_for_unmapped_official_id() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung_future_unmapped source=SC_SELF_SCENE_INFO",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content)

    assert parsed["battle"]["dungeon_key"] == "unknown_dungeon"
    assert parsed["battle"]["dungeon_name"] == "未知副本"
    assert parsed["battle"]["dungeon_context_id"] == "dung_future_unmapped"
    assert parsed["battle"]["dungeon_identity_source"] == "unmapped_dungeon_context"
    assert parsed["battle"]["boss_key"] == "eny_0051_rodin"

def test_parse_raw_battle_log_text_filters_effectless_wrapper_blackboard_values() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_spawnball" uid=1 owner=chr_0011_seraph src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[3]: atk_up=0.18 will_up=0.74 atk_scale=0.1',
            '[10:00:01.000] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0011_seraph_attack1" hits=1 src=chr_0011_seraph tgt=eny_0051_rodin atk=chr_0011_seraph seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="effectless-wrapper.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    assert [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"] == []

def test_parse_raw_battle_log_text_filters_registry_verified_character_wrappers() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0004_pelica_potential_3" uid=1 owner=chr_0004_pelica src=chr_0004_pelica dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: atk_up=0.2 atk_duration=5 max_stack=1",
            '[10:00:00.100] BUFF_START #2 id="buff_chr_0027_tangtang_passive_0" uid=2 owner=chr_0027_tangtang src=chr_0027_tangtang dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[2]: rate_spellvulnerable=0.1 rate_spellvulnerable_02=0.05 duration_spellvulnerable=5",
            '[10:00:01.000] HP_V2 #3 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0004_pelica_attack1" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="registry-character-wrapper.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    by_key = {event["event_key"]: event for event in parsed["buff_events"]}
    assert by_key["buff_chr_0004_pelica_potential_3"]["zone_effects"] == []
    assert by_key["buff_chr_0027_tangtang_passive_0"]["zone_effects"] == []
    assert [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"] == []

def test_parse_raw_battle_log_text_keeps_registry_leaf_character_effect() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0004_pelica_potential_3_atkup" uid=1 owner=chr_0004_pelica src=chr_0004_pelica dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: atk_up=0.2 atk_duration=5",
            '[10:00:01.000] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0004_pelica_attack1" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="registry-character-leaf.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    buff_event = next(event for event in parsed["buff_events"] if event["event_key"] == "buff_chr_0004_pelica_potential_3_atkup")
    assert buff_event["zone_effects"] == [{
        "zone": "atk", "element": "all", "rate": 0.2,
        "attr_type": 2, "bb_key": "atk_up",
        "semantic_source": "typed_current_attributeModifier",
        "external_rdps_allowed": False, "rdps_whitelist_keys": [],
    }]

def test_parse_raw_battle_log_text_ignores_non_enemy_hp_changes() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] HP_V2 #2 hit=9999 cum=9999 raw=9999.00 pHP=4500 eHP=5000 skill="buff_chr_0023_antal_talent_1_heal_trigger" hits=1 src=chr_0023_antal tgt=chr_0027_tangtang atk=? seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=200 cum=300 raw=200.00 pHP=5000 eHP=899800 skill="chr_0027_tangtang_attack2" hits=2 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="non-enemy-hp-change.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    assert parsed["battle"]["total_damage"] == 300
    assert [entry["character_key"] for entry in parsed["participants"]] == ["chr_0027_tangtang"]
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert len(damage_events) == 2
    assert {event["target_character_key"] for event in damage_events} == {"eny_0051_rodin"}

def test_parse_raw_battle_log_text_allocates_external_rdps_to_support() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_pelica_team_atk" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.5000 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_pelica_team_atk" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: atk_up=0.5 =0',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="support.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert set(participants) == {"chr_0027_tangtang"}
    assert participants["chr_0027_tangtang"]["dps"] == 150.0
    assert participants["chr_0027_tangtang"]["rdps"] == 150.0
    assert "chr_0004_pelica" not in participants

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["rdps_contributions"] == [{"character_key": "chr_0027_tangtang", "character_name": "汤汤", "value": 150.0}]

def test_parse_raw_battle_log_text_reports_packet_grounded_rdps_basis() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            '[10:00:00.000] ATTR_MOD buff="buff_pelica_team_atk" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.2500 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_pelica_team_atk" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=3.00 lifeT=3.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: atk_up=0.25',
            '[10:00:00.500] HP_V2 #2 hit=100 cum=100 raw=99.50 packetFinalValue=99.5001 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:03.000] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=3000 startMs=0 endMs=3000 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="packet-grounded-rdps.log")

    basis = parsed["rdps_damage_basis"]
    assert basis["mode"] == "packet_hp_loss"
    assert basis["hit_count"] == 1
    assert basis["packet_grounded_hit_count"] == 1
    assert basis["packet_final_value_count"] == 1
    assert basis["formula_grounded_hit_count"] == 0
    assert basis["rdps_conservation_ok"] is True
    assert basis["total_damage"] == 100
    assert basis["total_packet_final_value"] == 99.5001

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["total_rd"] == 100.0
    assert "chr_0004_pelica" not in participants
    assert rdps_totals_from_raw_report(parsed) == {
        "chr_0027_tangtang": 100.0,
    }

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["value"] == 100
    assert damage_event["value_source"] == "packet_hit"
    assert damage_event["packet_hit_value"] == 100
    assert damage_event["packet_raw_value"] == 99.5
    assert damage_event["packet_final_value"] == 99.5001
    assert damage_event["rdps_basis_value"] == 100

def test_parse_raw_battle_log_text_uses_baseline_self_side_when_allocating_rdps() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_spell_up_demo" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: dmg_up=0.25",
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:00.500] BASELINE #2 17=0.2500",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="baseline-self-side-rdps.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["rdps"] == 150.0
    assert "chr_0004_pelica" not in participants

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["rdps_contributions"] == [{"character_key": "chr_0027_tangtang", "character_name": "汤汤", "value": 150.0}]

def test_parse_raw_battle_log_text_calibrates_external_rdps_with_dpd_bucket() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_spell_up_demo" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: dmg_up=0.25",
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] DPD_RAW #2 probe=2 calc=150.0000 atkScale=1.0000 blocked=0 damageType=0x0 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.5000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000]',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="dpd-calibrated-rdps.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["rdps"] == 150.0
    assert "chr_0004_pelica" not in participants

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["rdps_contributions"] == [{"character_key": "chr_0027_tangtang", "character_name": "汤汤", "value": 150.0}]

def test_parse_raw_battle_log_text_rejects_unlisted_weapon_stack_credit() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_sword_0018_atk_up" uid=1 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[4]: atk_up=0.09 duration=20 max_stack=4",
            '[10:00:00.001] BUFF_START #101 id="buff_wpn_sword_0018_atk_up" uid=101 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.001] BB[101]: atk_up=0.09 duration=20 max_stack=4',
            '[10:00:00.100] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.100] BUFF_START #2 id="buff_wpn_sword_0018_atk_up" uid=2 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[4]: atk_up=0.09 duration=20 max_stack=4",
            '[10:00:00.101] BUFF_START #102 id="buff_wpn_sword_0018_atk_up" uid=102 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.101] BB[102]: atk_up=0.09 duration=20 max_stack=4',
            '[10:00:00.200] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.200] BUFF_START #3 id="buff_wpn_sword_0018_atk_up" uid=3 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.200]   BB[4]: atk_up=0.09 duration=20 max_stack=4",
            '[10:00:00.201] BUFF_START #103 id="buff_wpn_sword_0018_atk_up" uid=103 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.201] BB[103]: atk_up=0.09 duration=20 max_stack=4',
            '[10:00:00.300] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.300] BUFF_START #4 id="buff_wpn_sword_0018_atk_up" uid=4 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.300]   BB[4]: atk_up=0.09 duration=20 max_stack=4",
            '[10:00:00.301] BUFF_START #104 id="buff_wpn_sword_0018_atk_up" uid=104 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.301] BB[104]: atk_up=0.09 duration=20 max_stack=4',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"1","ownerId":"1001","enabled":true,"operationSeq":1}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"2","ownerId":"1001","enabled":true,"operationSeq":2}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"3","ownerId":"1001","enabled":true,"operationSeq":3}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"4","ownerId":"1001","enabled":true,"operationSeq":4}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"101","ownerId":"2001","enabled":true,"operationSeq":5}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"102","ownerId":"2001","enabled":true,"operationSeq":6}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"103","ownerId":"2001","enabled":true,"operationSeq":7}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"104","ownerId":"2001","enabled":true,"operationSeq":8}',
            '[10:00:00.400] HP_V2 #10 hit=1180 cum=1180 raw=1180.00 pHP=100 eHP=10000 skill="chr_0016_laevat_attack1" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat atkId=1001 tgtId=3001 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="weapon-stack-cap-rdps.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    # This weapon effect is absent from the active whitelist. A decoded
    # attribute and repeated instances cannot authorize external credit.
    assert participants["chr_0016_laevat"]["rdps"] == 1180
    assert participants.get("chr_0019_karin", {}).get("rdps", 0) == 0
    assert parsed['rdps_damage_basis']['rdps_strict_ok'] is False
    # This synthetic observation declares a complete four-stack cap; only
    # whitelist rejection should block credit, not missing stack evidence.
    assert not any(row['reason'] == 'unresolved_stack_evidence'
                   for row in parsed['rdps_preflight']['blockers'])
    assert any(row['reason'] == 'external_effect_not_whitelisted'
               for row in parsed['rdps_preflight']['blockers'])
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

def test_parse_raw_battle_log_text_does_not_map_enemy_phase_alias_to_dungeon() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0079_nefarp2 atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="nef-phase-alias.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    assert parsed["battle"]["boss_key"] == "eny_0079_nefarp2"
    assert parsed["battle"]["boss_name"] == "聂菲斯，“征服者”"
    assert parsed["battle"]["dungeon_key"] == "unknown_dungeon"
    assert parsed["battle"]["dungeon_name"] == "未知副本"
    assert parsed["battle"]["dungeon_context_id"] is None
    assert parsed["battle"]["dungeon_identity_source"] == "missing_dungeon_context"

def test_parse_raw_battle_log_text_maps_cryst_amp_attr_type_to_support_rdps() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_common_affixes_enhance_crystal" i=0 attrType=67 modType=0 formula=5 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_enhance_crystal" uid=1 owner=chr_0026_lastrite src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: rate=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="cryst-amp.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0026_lastrite"]["dps"] == 150.0
    assert participants["chr_0026_lastrite"]["rdps"] == 150.0
    assert "chr_0011_seraph" not in participants

def test_parse_raw_battle_log_text_prefers_final_modifier_key_over_base_key() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] DMG_MOD buff="buff_common_pulse_pulse_conduct_triggered_do" d=0 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="final_spell_resistance_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_pulse_pulse_conduct_triggered_do" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[3]: spell_resistance_decrease=0.1816 duration=2 final_spell_resistance_decrease=0.2415",
            '[10:00:00.500] HP_V2 #2 hit=124 cum=124 raw=124.15 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    labels = _collect_buff_labels(
        {
            "event_key": "buff_common_pulse_pulse_conduct_triggered_do",
            "target_enemy_key": "eny_0051_rodin",
            "source_character_key": "chr_0004_pelica",
            "bb_values": {
                "spell_resistance_decrease": 0.1816,
                "final_spell_resistance_decrease": 0.2415,
                "duration": 2.0,
            },
            "bb_keys": [
                "spell_resistance_decrease",
                "final_spell_resistance_decrease",
                "duration",
            ],
            "attr_mods": [],
            "attr_types": [],
        }
    )

    assert "导电" in labels

def test_parse_raw_battle_log_text_labels_frozen_status_even_without_rdps_effect() -> None:
    labels = _collect_buff_labels(
        {
            "event_key": "buff_common_enemy_spell_status_frozen",
            "target_enemy_key": "eny_0051_rodin",
            "source_character_key": "chr_0027_tangtang",
            "bb_values": {},
            "bb_keys": [],
            "attr_mods": [],
            "attr_types": [],
        }
    )

    assert labels == ["冻结"]

def test_collect_zone_effects_ignores_atk02_aura_detect_marker() -> None:
    record = {
        "event_key": "buff_equipsuit_atk_02_aruadetect",
        "source_character_key": "chr_0005_chen",
        "target_character_key": "chr_0003_endminf",
        "target_enemy_key": None,
        "bb_values": {"atk_up": 0.1, "dmg_up": 0.2, "max_stack": 3},
        "bb_keys": ["atk_up", "dmg_up", "max_stack"],
        "attr_mods": [],
        "attr_types": [],
    }

    assert _collect_buff_labels(record) == []
    assert _collect_zone_effects(record) == []

def test_parse_raw_battle_log_text_does_not_credit_atk02_detect_marker_to_wearer() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] LOADOUT slot=1 char=chr_0005_chen weaponTemplate=wpn_sword_0017 weaponLv=0 refine=3 break=0 equips={} equipSuit={[suit_atk02]=3}",
            "[09:59:59.000] LOADOUT slot=2 char=chr_0003_endminf weaponTemplate=wpn_sword_0021 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            '[10:00:00.000] BUFF_START #1 id="1397" uid=1 owner=chr_0003_endminf src=chr_0005_chen dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: atk_up=0.1 dmg_up=0.2 max_stack=3",
            '[10:00:01.000] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0003_endminf_attack1" hits=1 src=chr_0003_endminf tgt=eny_0051_rodin atk=chr_0003_endminf seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="atk02-detect-marker.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0003_endminf"]["total_rd"] == 100
    assert "chr_0005_chen" not in participants
    assert not [
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and event["event_key"] == "buff_equipsuit_atk_02_aruadetect"
    ]

def test_parse_raw_battle_log_text_ignores_legacy_false_fracture_projection() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart self=0000000000000000 msg=0000000000000000 startMs=0 expireMs=0 prepareSeconds=0",
            '[10:00:00.000] BUFF_START #1 id="933" uid=1 owner=eny_0051_rodin src=chr_0029_pograni dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: duration=5 physical_res_down=0.2",
            '[10:00:01.000] HP_V2 #2 hit=120 cum=120 raw=120.00 pHP=5000 eHP=899880 skill="chr_0003_endminf_attack1" hits=1 src=chr_0003_endminf tgt=eny_0051_rodin atk=chr_0003_endminf seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] GAME_TIMER_END seq=1 source=ChallengeComplete self=0000000000000000 msg=0000000000000000 elapsedMs=2000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="pograni-fracture-buff-axis.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    assert not [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0003_endminf", "character_name": "管理员", "value": 120.0},
    ]

def test_parse_raw_battle_log_text_uses_owner_for_self_attached_weapon_buffs() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_wpn_funnel_0010_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_funnel_0010_atk_up" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: atk_up=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="weapon-self-owner.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 150.0
    assert participants["chr_0027_tangtang"]["rdps"] == 150.0
    assert participants.get("chr_0011_seraph") is None

def test_parse_raw_battle_log_text_does_not_credit_replicated_unlisted_weapon_effect() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_sword_0018_atk_up" uid=1 owner=chr_0019_karin src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: atk_up=0.09 =0 duration=2',
            '[10:00:00.001] ATTR_MOD buff="buff_wpn_sword_0018_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.001] BUFF_START #2 id="buff_wpn_sword_0018_atk_up" uid=2 owner=chr_0027_tangtang src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.001]   BB[2]: atk_up=0.09 =0 duration=2',
            '[10:00:00.500] HP_V2 #3 hit=109 cum=109 raw=109.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="weapon-team-source.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 109.0
    assert participants["chr_0027_tangtang"]["rdps"] == 109.0
    assert participants.get("chr_0019_karin", {}).get("rdps", 0) == 0.0
    assert any(row['reason'] == 'external_effect_not_whitelisted'
               for row in parsed['rdps_preflight']['blockers'])

def test_parse_raw_battle_log_text_filters_enhance_default_child_by_element() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_enhance_spell_default_child" uid=1 owner=chr_0015_lifeng src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: rate=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0015_lifeng_attack1" hits=1 src=chr_0015_lifeng tgt=eny_0051_rodin atk=chr_0015_lifeng seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="enhance-default-child-element.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0015_lifeng"]["dps"] == 150.0
    assert participants["chr_0015_lifeng"]["rdps"] == 150.0
    assert "chr_0011_seraph" not in participants or participants["chr_0011_seraph"]["rdps"] == 0.0

def test_parse_raw_battle_log_text_does_not_treat_seraph_ultimate_wrapper_as_attack_buff() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_atk_buff" uid=1 owner=chr_0027_tangtang src=chr_0011_seraph dur=12.00 lifeT=12.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[6]: atk_up=0.242 =0 duration=12 =0 wisd_up=0.000308 =0",
            '[10:00:00.000] ATTR_MOD buff="buff_common_affixes_enhance_crystal" i=0 attrType=67 modType=0 formula=5 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #2 id="buff_common_affixes_enhance_crystal" uid=2 owner=chr_0027_tangtang src=chr_0011_seraph dur=12.00 lifeT=12.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[3]: rate=0.5 =0 duration=12",
            '[10:00:00.500] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="seraph-ultimate-wrapper.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    buff_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]
    assert [event["event_key"] for event in buff_events] == ["buff_common_affixes_enhance_crystal"]
    assert buff_events[0]["event_name"] == "增幅"

def test_parse_raw_battle_log_text_spell_vuln_does_not_apply_to_physical_school_natural_hit() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_funnel_0008_magic_damage_taken_up" uid=1 owner=eny_0051_rodin src=chr_0023_antal dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[3]: spell_damage_taken_up=0.198 duration=15 lv=7',
            '[10:00:00.500] HP_V2 #2 hit=123 cum=123 raw=122.66 pHP=5000 eHP=900000 skill="chr_0025_ardelia_remain_loop_sheep" hits=1 src=chr_0025_ardelia tgt=eny_0051_rodin atk=chr_0025_ardelia seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] PKT_MOD #2 atk=[] def=[1]',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="spell-vuln-school-filter.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contribs = {item["character_key"]: item["value"] for item in damage_event["rdps_contributions"]}
    assert contribs == {"chr_0025_ardelia": 123.0}

def test_parse_raw_battle_log_text_does_not_treat_internal_cryst_trigger_numeric_buff_as_external_damage_buff() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_enemy_spell_cryst_triggered_fx" uid=1 owner=eny_0051_rodin src=chr_0027_tangtang dur=6.00 lifeT=6.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[4]: count=1 consumed_layer=1 atk_scale=1.6 shatter_dmg=2.4 frozen_duration=6',
            '[10:00:00.000] BUFF_START #2 id="225" uid=2 owner=eny_0051_rodin src=chr_0027_tangtang dur=6.00 lifeT=6.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[6]: duration=6 phy_dmg_up=0.2 final_phy_dmg_up=0.2 count=1 atk_scale=1.6 shatter_dmg=2.4 consumed_layer=1',
            '[10:00:00.050] HP_V2 #3 hit=15418 cum=15418 raw=15418.35 pHP=0 eHP=1358508 skill="chr_0027_tangtang_skill_225" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="tangtang-internal-trigger.log",
        first_hit_hint="10-00-00-050",
        last_hit_hint="10-00-00-050",
    )

    buff_record = next(event for event in parsed["buff_events"] if event["event_key"] == "225")
    assert buff_record["zone_effects"] == []
    assert buff_record["packet_classification"]["class"] == "utility_or_marker"

    timeline_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]
    assert all(event["event_key"] != "225" for event in timeline_events)

def test_parse_raw_battle_log_text_does_not_promote_enemy_side_buff_id_prefix_into_party_source() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0021_whiten_combo_skill_physical_vulnerable" uid=1 owner=eny_0051_rodin src=eny_0051_rodin dur=3.00 lifeT=3.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: rate=0.28',
            '[10:00:00.500] HP_V2 #2 hit=1000 cum=1000 raw=1000.00 pHP=5000 eHP=899000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="enemy-side-buff-prefix.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert "chr_0021_whiten" not in participants

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contrib_keys = {item["character_key"] for item in damage_event["rdps_contributions"]}
    assert "chr_0021_whiten" not in contrib_keys

def test_parse_raw_battle_log_text_does_not_credit_speedup_or_slow_as_rdps_damage_gain() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_wpn_funnel_0005_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_funnel_0005_atk_up" uid=1 owner=chr_0028_wulfa src=chr_0004_pelica dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: atk_up=0.224 duration=20',
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0027_tangtang_comboskill_waterbuff" uid=2 owner=chr_0028_wulfa src=chr_0027_tangtang dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: duration_waterbuff=20 ratio_speed=0.2',
            '[10:00:00.000] BUFF_START #3 id="buff_chr_0027_tangtang_comboskill_waterdebuff" uid=3 owner=eny_0051_rodin src=chr_0027_tangtang dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: duration_waterdebuff=20 ratio_speedreduction=0.6',
            '[10:00:00.500] HP_V2 #4 hit=1224 cum=1224 raw=1224.00 pHP=5000 eHP=898776 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="speedup-slow-not-rdps.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contribs = {item["character_key"]: item["value"] for item in damage_event["rdps_contributions"]}
    assert "chr_0027_tangtang" not in contribs
    assert abs(sum(contribs.values()) - 1224.0) < 0.001

def test_parse_raw_battle_log_text_uses_canonical_display_name_for_derived_skill() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=123 cum=123 raw=122.66 pHP=5000 eHP=900000 skill="chr_0025_ardelia_remain_loop_sheep" hits=1 src=chr_0025_ardelia tgt=eny_0051_rodin atk=chr_0025_ardelia seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="canonical-display-name.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-00-000",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["event_key"] == "chr_0025_ardelia_remain_loop_sheep"
    assert damage_event["event_name"] == "绵羊持续伤害"

def test_canonical_num_table_skill_id_rejects_enemy_static_skill_for_player_runtime_id() -> None:
    assert _canonical_num_table_skill_id("chr_0015_lifeng_skill_1817", "chr_0015_lifeng") is None

def test_parse_raw_battle_log_text_marks_damage_events_with_real_cast_start() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            "[10:00:00.000] SKILL_CAST_START seq=2 startMs=0 inst=cast1 owner=chr_0028_wulfa skill=chr_0028_wulfa_normal_skill skillSource=unknown",
            '[10:00:00.500] HP_V2 #1 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=900000 skill="chr_0028_wulfa_normal_skill" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.400] SKILL_CAST_START seq=3 startMs=1400 inst=proj1 owner=chr_0028_wulfa skill=chr_0028_wulfa_normal_skill_projhit5 skillSource=Summon",
            '[10:00:01.500] HP_V2 #2 hit=200 cum=300 raw=200.00 packetFinalValue=200.0 pHP=5000 eHP=899700 skill="chr_0028_wulfa_normal_skill" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=2000 startMs=0 endMs=2000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="cast-start-damage.log")
    skill_events = [
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "skill" and event["event_key"] == "chr_0028_wulfa_normal_skill"
    ]

    assert [event["ts_ms_from_start"] for event in skill_events] == [500, 1500]
    assert [event["actual_start_ms_from_start"] for event in skill_events] == [0, 0]
