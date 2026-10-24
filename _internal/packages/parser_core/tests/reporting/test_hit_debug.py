
from parser_core.hit_context import build_hit_context
from parser_core.hit_debug import parse_hit_debug_log_text

def test_hit_debug_uses_only_official_dungeon_context_for_stage_identity() -> None:
    hit = (
        '[10:00:00.500] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 '
        'skill="chr_0028_wulfa_normal_skill" hits=1 skillLv=12 templateIntId=2132 actionId=97 '
        'origTemplateIntId=2132 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin '
        'atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=-1.0000'
    )

    without_context = parse_hit_debug_log_text(hit, file_name="missing-stage.log")
    assert without_context["summary"]["boss_key"] == "eny_0051_rodin"
    assert without_context["summary"]["dungeon_key"] == "unknown_dungeon"
    assert without_context["summary"]["dungeon_identity_source"] == "missing_dungeon_context"

    with_context = parse_hit_debug_log_text(
        '\n'.join(
            [
                '[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower004_ex',
                hit,
            ]
        ),
        file_name="official-stage.log",
    )
    assert with_context["summary"]["boss_key"] == "eny_0051_rodin"
    assert with_context["summary"]["dungeon_key"] == "indie_battletower004_ex"
    assert with_context["summary"]["dungeon_context_id"] == "indie_battletower004_ex"
    assert with_context["summary"]["dungeon_identity_source"] == "dungeon_context"

def test_hit_context_uses_damage_school_for_spell_vulnerability() -> None:
    spell_vuln_window = {
        "start_ts_ms": 0,
        "end_ts_ms": 10_000,
        "event_key": "buff_common_pulse_pulse_conduct_triggered_do",
        "event_name": "导电 / 承伤易伤",
        "uid": "conduct",
        "source_character_key": "chr_0004_pelica",
        "source_character_name": "佩丽卡",
        "target_character_key": "eny_0051_rodin",
        "target_actor_id": "enemy-1",
        "target_character_name": "“碾骨之拳”罗丹",
        "zone_effects": [{"zone": "vuln_taken", "element": "spell", "rate": 0.12}],
    }
    base_hit = {
        "character_key": "chr_0028_wulfa",
        "target_enemy_key": "eny_0051_rodin",
        "target_actor_id": "enemy-1",
        "ts_ms": 1_000,
        "hit_value": 112,
        "skill_key": "chr_0028_wulfa_normal_skill",
        "baseline": {},
        "dpd_raw": None,
    }

    spell_school_context = build_hit_context(
        {**base_hit, "damage_element": "physical", "damage_school": "spell"},
        [spell_vuln_window],
    )
    physical_school_context = build_hit_context(
        {**base_hit, "damage_element": "natural", "damage_school": "physical"},
        [spell_vuln_window],
    )

    assert spell_school_context["external_sources"] == [
        {
            "character_key": "chr_0004_pelica",
            "character_name": "佩丽卡",
            "effect_count": 1,
            "rdps_credit": 12.0,
        }
    ]
    assert physical_school_context["external_sources"] == []
    assert physical_school_context["ignored_effects"][0]["reason"] == "damage_school_filtered"
    assert physical_school_context["ignored_effects"][0]["reason_group"] == "element_mismatch"
    assert physical_school_context["ignored_effects"][0]["effect_element"] == "spell"
    assert physical_school_context["ignored_effects"][0]["hit_damage_school"] == "physical"

def test_parse_hit_debug_log_text_caps_final_boss_overkill_damage() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=200 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #2 hit=500 cum=500 raw=500.00 pHP=5000 eHP=0 skill="chr_0004_pelica_attack1" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="sample.log")

    assert parsed["summary"]["total_damage"] == 300
    by_key = {participant["character_key"]: participant for participant in parsed["participants"]}
    assert by_key["chr_0027_tangtang"]["total_damage"] == 100
    assert by_key["chr_0004_pelica"]["total_damage"] == 200
    final_hit = parsed["hits"][-1]
    assert final_hit["hit_value"] == 200
    assert final_hit["raw_hit_value"] == 500
    assert final_hit["overkill_damage"] == 300

def test_parse_hit_debug_log_text_filters_effectless_wrapper_blackboard_values() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_spawnball" uid=1 owner=chr_0011_seraph src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[3]: atk_up=0.18 will_up=0.74 atk_scale=0.1",
            '[10:00:01.000] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0011_seraph_attack1" hits=1 src=chr_0011_seraph tgt=eny_0051_rodin atk=chr_0011_seraph seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="effectless-wrapper.log")

    row = next(row for row in parsed["buff_audit"] if row["event_key"] == "buff_chr_0011_seraph_spawnball")
    assert row["status"] == "filtered"
    assert "无可识别正数效果" in row["reasons"]
    hit = parsed["hits"][0]
    assert hit["zones"] == []

def test_parse_hit_debug_log_text_uses_raw_loadout_skill_ids_for_skill_evidence() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] LOADOUT slot=2 char=chr_0006_wolfgd weaponTemplate=wpn_pistol_0009 weaponLv=1 refine=0 break=0 equipSuit={} equips={} skillIntIds=[170,192]",
            "[10:00:01.000] ACTOR_MAP id=42 template=chr_0006_wolfgd source=launch_projectile skill=chr_0006_wolfgd_skill_192",
            '[10:00:01.120] HP_V2 #1 hit=370 cum=370 raw=370.42 pHP=5000 eHP=900000 skill="chr_0006_wolfgd_skill_192" hits=1 src=chr_0006_wolfgd tgt=eny_0051_rodin atk=chr_0006_wolfgd seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="raw-loadout-skill-evidence.log")
    mapping = parsed["hits"][0]["skill_mapping"]

    assert parsed["loadout"][0]["skill_int_ids"] == ["170", "192"]
    assert mapping["status"] == "mapped"
    assert mapping["canonical_skill_id"] == "chr_0006_wolfgd_ultimate_skill"
    assert mapping["evidence_kind"] == "canonical_parser_identity"
    assert "confidence" not in mapping
    assert mapping["candidates"] == []

def test_parse_hit_debug_log_text_uses_canonical_display_name_for_derived_skill() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=123 cum=123 raw=122.66 pHP=5000 eHP=900000 skill="chr_0025_ardelia_remain_loop_sheep" hits=1 src=chr_0025_ardelia tgt=eny_0051_rodin atk=chr_0025_ardelia seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="canonical-display-name.log")
    hit = parsed["hits"][0]

    assert hit["skill_key"] == "chr_0025_ardelia_remain_loop_sheep"
    assert hit["skill_name"] == "绵羊持续伤害"

def test_parse_hit_debug_log_text_uses_human_name_for_yvonne_combo_runtime_damage() -> None:
    content = "\n".join(
        [
            '[10:00:00.200] HP_V2 #1 hit=1049 cum=1049 raw=1049.39 pHP=0 eHP=899000 skill="chr_0017_yvonne_skill_162" hits=1 skillLv=unknown templateIntId=162 actionId=14 origTemplateIntId=1187 damageUnitIndex=0 partInstId=unknown dynBB=unknown calcBB=unknown src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:00.400] HP_V2 #2 hit=2049 cum=2049 raw=2049.39 pHP=0 eHP=896951 skill="chr_0017_yvonne_skill_163" hits=1 skillLv=unknown templateIntId=163 actionId=9 origTemplateIntId=1187 damageUnitIndex=0 partInstId=unknown dynBB=unknown calcBB=unknown src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="yvonne-combo-runtime-damage.log")

    assert parsed["hits"][0]["skill_name"] == "伊冯连携 / 机器人持续伤害"
    assert parsed["hits"][1]["skill_name"] == "伊冯连携 / 机器人终结爆炸"

def test_parse_hit_debug_log_text_enriches_embedded_loadout_affixes() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0016_laevat_attack1" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "## ENDFIELD_RAW_LOG_INTEGRITY_BEGIN sep=0",
            "{",
            '  "meta": {',
            '    "loadout": [',
            "      {",
            '        "slot": 0,',
            '        "char_key": "chr_0016_laevat",',
            '        "char_name": "莱万汀",',
            '        "potential": 0,',
            '        "weapon_template": "wpn_sword_0006",',
            '        "weapon_level": 90,',
            '        "weapon_refine": 0,',
            '        "equips": [',
            "          {",
            '            "slot": 0,',
            '            "item_id": "item_equip_t4_suit_fire_natr01_hand_02",',
            '            "enhance_levels": [0, 0, 3],',
            '            "enhance_failed_times": -42040624',
            "          },",
            "          {",
            '            "slot": 1,',
            '            "item_id": "3",',
            '            "enhance_failed_times": -42242784',
            "          }",
            "        ]",
            "      }",
            "    ]",
            "  }",
            "}",
            "## ENDFIELD_RAW_LOG_INTEGRITY_END",
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="loadout-affixes.log")

    loadout = parsed["loadout"][0]
    assert loadout["weapon_base_atk"] == 510
    assert len(loadout["equips"]) == 1
    equip = loadout["equips"][0]
    assert equip["enhance_failed_times"] is None
    assert equip["piece_name"] == "动火用手甲"
    fire_attr = next(attr for attr in equip["affixes"] if attr["desc"] == "灼热和自然伤害提升")
    assert fire_attr["level"] == 3
    assert fire_attr["selected_value"] == 0.249167

def test_parse_hit_debug_log_text_does_not_double_count_seraph_heal_attack_wrapper() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_mainchr_heal" uid=10 owner=chr_0027_tangtang src=chr_0011_seraph ownerId=1001 srcId=2001 dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[4]: atk_scale=0.1 heal_value=316.8 potential_1=0 atk_up=0.18",
            '[10:00:00.240] HP_V2 #2 hit=811 cum=811 raw=811.29 pHP=6721 eHP=6885 skill="buff_chr_0011_seraph_mainchr_heal" hits=1 src=chr_0011_seraph tgt=chr_0027_tangtang atk=? seg=-1 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:00.240] ATTR_MOD buff="buff_wpn_funnel_0010_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.240] BUFF_START #3 id="buff_wpn_funnel_0010_atk_up" uid=20 owner=chr_0027_tangtang src=chr_0011_seraph ownerId=1001 srcId=2001 dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.240]   BB[2]: atk_up=0.18 duration=15",
            '[10:00:00.240] ATTR_MOD buff="buff_wpn_funnel_0010_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up"',
            '[10:00:00.240] BUFF_START #30 id="buff_wpn_funnel_0010_atk_up" uid=30 owner=chr_0011_seraph src=chr_0011_seraph ownerId=2001 srcId=2001 dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.240]   BB[2]: atk_up=0.18 duration=15",
            '[10:00:00.240] BUFF_START #4 id="buff_chr_0011_seraph_potential_1_atkup" uid=21 owner=chr_0027_tangtang src=chr_0011_seraph ownerId=1001 srcId=2001 dur=25.00 lifeT=25.00 passed=0.00 enh=1',
            "[10:00:00.240]   BB[1]: atk_up=0.18",
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"10","ownerId":"1001","enabled":true,"operationSeq":1}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"20","ownerId":"1001","enabled":true,"operationSeq":2}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"30","ownerId":"2001","enabled":true,"operationSeq":3}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"21","ownerId":"1001","enabled":true,"operationSeq":4}',
            '[10:00:01.000] HP_V2 #5 hit=1180 cum=1180 raw=1180.00 pHP=100 eHP=10000 skill="chr_0027_tangtang_attack1_projhit" actionId=0 damageUnitIndex=0 hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang atkId=1001 tgtId=3001 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="seraph-heal-atk-wrapper.log")
    hit = parsed["hits"][-1]
    atk_zone = next(zone for zone in hit["zones"] if zone["zone"] == "atk")
    seraph_attack_rows = [
        row for row in atk_zone["contributors"] if row["source_character_key"] == "chr_0011_seraph"
    ]
    wrapper_row = next(
        row
        for row in parsed["buff_audit"]
        if row["event_key"] == "buff_chr_0011_seraph_potential_1_atkup"
    )

    assert atk_zone["external_rate"] == 0.18
    assert [row["event_key"] for row in seraph_attack_rows] == ["buff_wpn_funnel_0010_atk_up"]
    assert wrapper_row["status"] == "filtered"
    assert wrapper_row["effect_summary"] == []

def test_parse_hit_debug_log_text_caps_weapon_buff_stack_limit() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_wpn_sword_0012_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up2"',
            '[10:00:00.000] BUFF_START #1 id="buff_wpn_sword_0012_atk_up" uid=1 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[4]: atk_up2=0.09 duration=20 max_stack=2",
            '[10:00:00.001] BUFF_START #101 id="buff_wpn_sword_0012_atk_up" uid=101 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.001] BB[101]: atk_up2=0.09 duration=20 max_stack=2',
            '[10:00:00.100] ATTR_MOD buff="buff_wpn_sword_0012_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up2"',
            '[10:00:00.100] BUFF_START #2 id="buff_wpn_sword_0012_atk_up" uid=2 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[4]: atk_up2=0.09 duration=20 max_stack=2",
            '[10:00:00.101] BUFF_START #102 id="buff_wpn_sword_0012_atk_up" uid=102 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.101] BB[102]: atk_up2=0.09 duration=20 max_stack=2',
            '[10:00:00.200] ATTR_MOD buff="buff_wpn_sword_0012_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up2"',
            '[10:00:00.200] BUFF_START #3 id="buff_wpn_sword_0012_atk_up" uid=3 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.200]   BB[4]: atk_up2=0.09 duration=20 max_stack=2",
            '[10:00:00.201] BUFF_START #103 id="buff_wpn_sword_0012_atk_up" uid=103 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.201] BB[103]: atk_up2=0.09 duration=20 max_stack=2',
            '[10:00:00.300] ATTR_MOD buff="buff_wpn_sword_0012_atk_up" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.0000 bbKey="atk_up2"',
            '[10:00:00.300] BUFF_START #4 id="buff_wpn_sword_0012_atk_up" uid=4 owner=chr_0016_laevat src=chr_0019_karin ownerId=1001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.300]   BB[4]: atk_up2=0.09 duration=20 max_stack=2",
            '[10:00:00.301] BUFF_START #104 id="buff_wpn_sword_0012_atk_up" uid=104 owner=chr_0019_karin src=chr_0019_karin ownerId=2001 srcId=2001 dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            '[10:00:00.301] BB[104]: atk_up2=0.09 duration=20 max_stack=2',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"1","ownerId":"1001","enabled":false,"operationSeq":1}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"2","ownerId":"1001","enabled":false,"operationSeq":2}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"3","ownerId":"1001","enabled":true,"operationSeq":3}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"4","ownerId":"1001","enabled":true,"operationSeq":4}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"101","ownerId":"2001","enabled":false,"operationSeq":5}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"102","ownerId":"2001","enabled":false,"operationSeq":6}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"103","ownerId":"2001","enabled":true,"operationSeq":7}',
            '[10:00:00.350] BUFF_ENABLE {"schemaVersion":1,"buffUid":"104","ownerId":"2001","enabled":true,"operationSeq":8}',
            '[10:00:00.400] HP_V2 #10 hit=1180 cum=1180 raw=1180.00 pHP=100 eHP=10000 skill="chr_0016_laevat_attack1" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat atkId=1001 tgtId=3001 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_hit_debug_log_text(content, file_name="weapon-stack-cap.log")
    hit = parsed["hits"][0]
    atk_zone = next(zone for zone in hit["zones"] if zone["zone"] == "atk")
    weapon_rows = [
        row
        for row in atk_zone["contributors"]
        if row["event_key"] == "buff_wpn_sword_0012_atk_up"
    ]

    assert atk_zone["external_rate"] == 0.18
    # The observed enable state selects these instances; UID order is not a FIFO proof.
    assert [row["uid"] for row in weapon_rows] == ["3", "4"]
    inactive = {row["uid"]: row for row in parsed["buff_audit"] if row["uid"] in {"1", "2"}}
    assert set(inactive) == {"1", "2"}
    for uid, row in inactive.items():
        assert row["enable_observations"][-1]["enabled"] is False
        assert row["raw_end_ts_ms"] is None
        assert row["raw_duration_ms"] == 20000
    assert inactive["1"]["start_ts_ms"] == 36000000
    assert inactive["2"]["start_ts_ms"] == 36000100
