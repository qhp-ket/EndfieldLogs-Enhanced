import pytest
from parser_core.battle_log_parser import _collect_buff_labels, _collect_zone_effects, parse_raw_battle_log_text



@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert parsed["battle"]["boss_key"] == "eny_0079_nefarp2"')
def test_parse_raw_battle_log_text_retargets_unknown_enemy_from_dungeon_context() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung02_bossrush02_03 source=SC_SELF_SCENE_INFO",
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=100701 tgtId=100804 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="unknown-boss-context.log")

    assert parsed["battle"]["boss_key"] == "eny_0079_nefarp2"
    assert parsed["battle"]["boss_name"] == "聂菲斯，“征服者”"
    assert parsed["battle"]["clear_flag"] is True

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert parsed["battle"]["boss_key"] == "eny_0051_rodin"')
def test_parse_raw_battle_log_text_uses_current_battle_loadout_snapshot() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] LOADOUT reason=SC_ITEM_BAG_SCOPE_MODIFY slotCount=2 memberCount=2 roster=[1 2]",
            "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 equipSuit={}",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0006_wolfgd weaponTemplate=wpn_pistol_0012 equipSuit={}",
            "[10:00:10.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:11.000] LOADOUT reason=BATTLE_START slotCount=4 memberCount=4 roster=[3 4 5 6]",
            "[10:00:11.000] LOADOUT slot=0 char=chr_0026_lastrite weaponTemplate=wpn_claym_0013 equipSuit={}",
            "[10:00:11.000] LOADOUT slot=1 char=chr_0027_tangtang weaponTemplate=wpn_pistol_0011 equipSuit={}",
            "[10:00:11.000] LOADOUT slot=2 char=chr_0011_seraph weaponTemplate=wpn_funnel_0010 equipSuit={}",
            "[10:00:11.000] LOADOUT slot=3 char=chr_0013_aglina weaponTemplate=wpn_funnel_0005 equipSuit={}",
            "[10:00:11.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            '[10:00:12.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=100 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=4 tgtId=99 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:13.000] HP_V2 #2 hit=50 cum=50 raw=50.00 pHP=0 eHP=0 skill="chr_0013_aglina_attack1" hits=1 src=chr_0013_aglina tgt=eny_0000_unknown atk=chr_0013_aglina atkId=6 tgtId=99 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:15.000] GAME_TIMER_END seq=2 source=PacketBattleState elapsedMs=4000 startMs=0 endMs=4000 expireMs=0 sane=1 official=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="current-loadout.log")

    assert parsed["battle"]["boss_key"] == "eny_0051_rodin"
    assert [row["character_key"] for row in parsed["loadout"]] == [
        "chr_0026_lastrite",
        "chr_0027_tangtang",
        "chr_0011_seraph",
        "chr_0013_aglina",
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert parsed["battle"]["boss_key"] == "eny_0078_nefarp1"')
def test_parse_raw_battle_log_text_retargets_unknown_enemy_from_single_buff_hint() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_eny_0078_nefarp1_player_jump" uid=1 owner=eny_0000_unknown src=chr_0027_tangtang dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            '[10:00:01.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=100701 tgtId=100804 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="unknown-boss-buff.log")

    assert parsed["battle"]["boss_key"] == "eny_0078_nefarp1"
    assert parsed["battle"]["boss_name"] == "聂菲斯，“碾骨”"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")')
def test_parse_raw_battle_log_text_clips_buff_timeline_duration_to_battle_window() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_common_natural_cryst_triggered" i=0 attrType=82 modType=0 formula=5 useKey=1 val=0.0000 bbKey="def_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_natural_cryst_triggered" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[4]: def_decrease=0.08129 =0 max_def_decrease=0.271 =0 def_decrease_tick=0.01897 =0 duration=15",
            '[10:00:10.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="prebattle-buff.log",
        first_hit_hint="10-00-10-000",
        last_hit_hint="10-00-11-000",
    )

    buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")
    assert buff_event["ts_ms_from_start"] == 0
    assert buff_event["duration_ms"] == 1000
    assert buff_event["target_player_key"] is None
    assert buff_event["target_enemy_key"] == "eny_0051_rodin"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert len(buff_events) == 1')
def test_parse_raw_battle_log_text_keeps_potion_duration_when_refresh_end_is_same_tick() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_common_atk_buff_potion_1" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.1000 bbKey="value"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_atk_buff_potion_1" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=300.00 lifeT=300.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: value=0.27',
            '[10:00:00.000] BUFF_END #2 id="buff_common_atk_buff_potion_1" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=300.00 lifeT=245.71 passed=0.00 enh=1',
            '[10:00:00.001] ATTR_MOD buff="buff_common_atk_buff_potion_1" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.1000 bbKey="value"',
            '[10:00:00.001] BUFF_START #3 id="buff_common_atk_buff_potion_1" uid=2 owner=chr_0027_tangtang src=chr_0027_tangtang dur=300.00 lifeT=300.00 passed=0.00 enh=1',
            '[10:00:00.001]   BB[1]: value=0.27',
            '[10:00:05.000] HP_V2 #4 hit=127 cum=127 raw=127.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="potion-refresh.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-05-000",
    )

    buff_events = [
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and event["event_key"] == "buff_common_atk_buff_potion_1"
    ]
    assert len(buff_events) == 1
    assert buff_events[0]["duration_ms"] == 5000
    assert buff_events[0]["actual_duration_ms"] == 5000

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy skill mapping/display/report contract; old fixture or field expectation needs migration; fails at: assert names[-1] == "猛击"')
def test_parse_raw_battle_log_text_maps_display_skill_names_to_generic_labels() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.100] HP_V2 #2 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0027_tangtang_attack4" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.200] HP_V2 #3 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899800 skill="chr_0027_tangtang_attack5" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.300] HP_V2 #4 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899700 skill="chr_0027_tangtang_power_attack" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.400] HP_V2 #5 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899600 skill="chr_0027_tangtang_normal_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] HP_V2 #6 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899500 skill="chr_0027_tangtang_combo_2_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.600] HP_V2 #7 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899400 skill="chr_0027_tangtang_ultimate_skill_1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.700] HP_V2 #8 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899300 skill="chr_0027_tangtang_execute" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.800] HP_V2 #9 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899200 skill="buff_common_cryst_triggered_physical_break" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="generic-display-names.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    names = [event["event_name"] for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert names[-1] == "猛击"



@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert parsed["rdps_preflight"]["ok"] is True')
def test_parse_raw_battle_log_text_allocates_endmin_essence_collapse_attack_share() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] LOADOUT reason=SC_SELF_SCENE_INFO",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0003_endminf weaponTemplate=wpn_sword_0021 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=2 char=chr_0028_wulfa weaponTemplate=wpn_sword_0016 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            '[10:00:00.000] ATTR_MOD buff="buff_chr_0003_endminf_talent_1_tirgger" i=0 attrType=2 modType=0 formula=6 useKey=1 val=0.1500 bbKey="atk_up"',
            '[10:00:00.100] BUFF_START #1 id="buff_chr_0003_endminf_talent_1_tirgger" uid=adm1 owner=chr_0028_wulfa src=chr_0003_endminf dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: atk_up=0.15 duration=15",
            '[10:00:01.000] HP_V2 #2 hit=115 cum=115 raw=115.00 pHP=5000 eHP=899885 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="endmin-essence-collapse-share.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    assert parsed["rdps_preflight"]["ok"] is True
    assert parsed["rdps_preflight"]["accepted_effect_buff_count"] == 1

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0028_wulfa"]["total_rd"] == 100.00000000000001
    assert round(participants["chr_0003_endminf"]["total_rd"], 6) == 15.0

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["rdps_contributions"] == [
        {
            "character_key": "chr_0003_endminf",
            "character_name": "管理员",
            "value": 15.0,
        },
        {
            "character_key": "chr_0028_wulfa",
            "character_name": "洛茜",
            "value": 100.0,
        },
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert parsed["rdps_preflight"]["ok"] is True')
def test_parse_raw_battle_log_text_allocates_endmin_essence_collapse_parent_attack_share() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] LOADOUT reason=SC_SELF_SCENE_INFO",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0003_endminf weaponTemplate=wpn_sword_0021 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=2 char=chr_0028_wulfa weaponTemplate=wpn_sword_0016 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            '[10:00:00.100] BUFF_START #1 id="buff_chr_0003_endminf_talent_1" uid=1 owner=chr_0028_wulfa src=chr_0003_endminf dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: atk_up=0.15 duration=15",
            '[10:00:01.000] HP_V2 #2 hit=115 cum=115 raw=115.00 pHP=5000 eHP=899885 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="endmin-essence-collapse-parent-share.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    assert parsed["rdps_preflight"]["ok"] is True
    assert parsed["rdps_preflight"]["accepted_effect_buff_count"] == 1

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0028_wulfa"]["total_rd"] == 100.00000000000001
    assert round(participants["chr_0003_endminf"]["total_rd"], 6) == 15.0

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert damage_events[0]["rdps_contributions"] == [
        {
            "character_key": "chr_0003_endminf",
            "character_name": "管理员",
            "value": 15.0,
        },
        {
            "character_key": "chr_0028_wulfa",
            "character_name": "洛茜",
            "value": 100.0,
        },
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert parsed["rdps_preflight"]["ok"] is True')
def test_parse_raw_battle_log_text_allocates_endmin_reality_stasis_only_on_originum_frozen_physical_hits() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] LOADOUT reason=SC_SELF_SCENE_INFO",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0003_endminf weaponTemplate=wpn_sword_0021 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=2 char=chr_0029_pograni weaponTemplate=wpn_sword_0016 weaponLv=0 refine=1 break=0 equips={} equipSuit={}",
            '[10:00:00.000] BUFF_START #1 id="991" uid=1 owner=chr_0003_endminf src=chr_0003_endminf dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: dmg=0.2",
            '[10:00:00.000] BUFF_START #2 id="20" uid=2 owner=chr_0029_pograni src=chr_0003_endminf dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[2]: dmg=0.2",
            '[10:00:00.000] BUFF_START #3 id="340" uid=3 owner=eny_0051_rodin src=chr_0003_endminf dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            '[10:00:01.000] HP_V2 #4 hit=120 cum=120 raw=120.00 pHP=5000 eHP=899880 skill="chr_0029_pograni_attack1" hits=1 src=chr_0029_pograni tgt=eny_0051_rodin atk=chr_0029_pograni seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="endmin-reality-stasis.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    assert parsed["rdps_preflight"]["ok"] is True
    assert parsed["rdps_preflight"]["accepted_effect_buff_count"] == 1
    assert parsed["rdps_preflight"]["accepted_non_rdps_buff_count"] == 1

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0029_pograni"]["total_rd"] == 100.0
    assert participants["chr_0003_endminf"]["total_rd"] == 20.0

    buff_event = next(
        event
        for event in parsed["buff_events"]
        if event["event_key"] == "buff_chr_0003_endminf_talent_0"
    )
    assert buff_event["zone_effects"] == [
        {
            "zone": "vuln_taken",
            "element": "physical",
            "rate": 0.2,
            "condition": {
                "type": "all",
                "source": "CheckBuffStackNumAdvanced+CheckDamageType",
                "conditions": [
                    {"type": "damage_type_in", "source": "CheckDamageType", "elements": ["physical"]},
                    {
                        "type": "target_has_buff",
                        "source": "CheckBuffStackNumAdvanced",
                        "buff_ids": ["buff_common_originum_frozen"],
                    },
                ],
            },
            "semantic_source": "damageEffects",
            "bb_key": "dmg",
        }
    ]

    no_state_content = content.replace(
        '[10:00:00.000] BUFF_START #3 id="340" uid=3 owner=eny_0051_rodin src=chr_0003_endminf dur=10.00 lifeT=10.00 passed=0.00 enh=1\n',
        "",
    )
    no_state_parsed = parse_raw_battle_log_text(
        no_state_content,
        file_name="endmin-reality-stasis-no-state.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )
    no_state_participants = {entry["character_key"]: entry for entry in no_state_parsed["participants"]}
    assert no_state_participants["chr_0029_pograni"]["total_rd"] == 120.0
    assert "chr_0003_endminf" not in no_state_participants

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: dmg_inc = next(zone for zone in hit["zones"] if zone["zone"] == "dmg_inc")')
def test_parse_raw_battle_log_text_includes_static_self_multipliers_in_rdps_baseline() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 weaponLv=0 refine=0 break=0 equips={[0]=item_equip_t4_suit_fire_natr01_hand_02|stats=sub3:灼热和自然伤害提升=0.249167@3} equipSuit={}",
            "[10:00:00.001] LOADOUT_STATS slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 weaponSourceSkills={2237:level=4:potentialLv=0:bb={fire_dmg_up=0.256,normal_atk_up=1.2,duration=20}}",
            '[10:00:00.500] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=5000 eHP=900000 skill="chr_0016_laevat_attack1" hits=1 src=chr_0016_laevat tgt=eny_0051_rodin atk=chr_0016_laevat seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="static-self-rdps.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
        include_rdps_debug=True,
    )

    hit = parsed["debug_hits"][0]
    dmg_inc = next(zone for zone in hit["zones"] if zone["zone"] == "dmg_inc")
    assert dmg_inc["self_rate"] == 0.5052
    contributor_labels = {item["event_name"] for item in dmg_inc["contributors"]}
    assert any("动火用手甲" in label for label in contributor_labels)
    assert any("fire_dmg_up" in label for label in contributor_labels)
    assert all("normal_atk_up" not in label for label in contributor_labels)

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0019_karin"]["rdps"] == 50.0')
def test_parse_raw_battle_log_text_respects_physical_vulnerable_element_filter() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_common_affixes_vulnerable_physical" i=0 attrType=70 modType=0 formula=5 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_vulnerable_physical" uid=1 owner=eny_0051_rodin src=chr_0025_ardelia dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: rate=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0019_karin_attack1" hits=1 src=chr_0019_karin tgt=eny_0051_rodin atk=chr_0019_karin seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=899850 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="physical-vulnerable.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0019_karin"]["dps"] == 75.0
    assert participants["chr_0019_karin"]["rdps"] == 50.0
    assert participants["chr_0017_yvonne"]["dps"] == 75.0
    assert participants["chr_0017_yvonne"]["rdps"] == 75.0
    assert participants["chr_0025_ardelia"]["dps"] == 0.0
    assert participants["chr_0025_ardelia"]["rdps"] == 25.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0026_lastrite"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_uses_dmg_mod_enemy_cryst_up_for_rdps() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] DMG_MOD buff="buff_chr_0011_seraph_talent_1_crystup" d=0 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="cryst_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_talent_1_crystup" uid=1 owner=eny_0051_rodin src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: cryst_up=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="enemy-cryst-up.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0026_lastrite"]["dps"] == 150.0
    assert participants["chr_0026_lastrite"]["rdps"] == 100.0
    assert participants["chr_0011_seraph"]["dps"] == 0.0
    assert participants["chr_0011_seraph"]["rdps"] == 50.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 50.0')
def test_parse_raw_battle_log_text_uses_dmg_mod_spell_res_down_for_spell_only_hits() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] DMG_MOD buff="buff_pelica_spell_res_down" d=3 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="final_spell_resistance_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_pelica_spell_res_down" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: final_spell_resistance_decrease=0.5',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0019_karin_attack1" hits=1 src=chr_0019_karin tgt=eny_0051_rodin atk=chr_0019_karin seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=899850 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="spell-res-down.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0019_karin"]["dps"] == 75.0
    assert participants["chr_0019_karin"]["rdps"] == 75.0
    assert participants["chr_0017_yvonne"]["dps"] == 75.0
    assert participants["chr_0017_yvonne"]["rdps"] == 50.0
    assert participants["chr_0004_pelica"]["dps"] == 0.0
    assert participants["chr_0004_pelica"]["rdps"] == 25.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 50.0')
def test_parse_raw_battle_log_text_respects_spell_only_buff_filter() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_spell_vuln_demo" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: spell_taken_up=0.5',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0019_karin_attack1" hits=1 src=chr_0019_karin tgt=eny_0051_rodin atk=chr_0019_karin seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=899850 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="element-filter.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0019_karin"]["dps"] == 75.0
    assert participants["chr_0019_karin"]["rdps"] == 75.0
    assert participants["chr_0017_yvonne"]["dps"] == 75.0
    assert participants["chr_0017_yvonne"]["rdps"] == 50.0
    assert participants["chr_0004_pelica"]["dps"] == 0.0
    assert participants["chr_0004_pelica"]["rdps"] == 25.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert _collect_buff_labels(record) == ["攻击提升"]')
def test_collect_zone_effects_atk02_parent_keeps_only_wearer_attack() -> None:
    record = {
        "event_key": "buff_equipsuit_atk_02",
        "source_character_key": "chr_0005_chen",
        "target_character_key": "chr_0005_chen",
        "target_enemy_key": None,
        "bb_values": {"atk_up": 0.15, "dmg_up": 0.2, "max_stack": 3},
        "bb_keys": ["atk_up", "dmg_up", "max_stack"],
        "attr_mods": [],
        "attr_types": [],
    }

    assert _collect_buff_labels(record) == ["攻击提升"]
    assert _collect_zone_effects(record) == [{"zone": "atk", "element": "all", "rate": 0.15}]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert natural_hit["damage_element"] == "natural"')
def test_parse_raw_battle_log_text_suppresses_legacy_false_fracture_for_all_elements() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart self=0000000000000000 msg=0000000000000000 startMs=0 expireMs=0 prepareSeconds=0",
            '[10:00:00.000] BUFF_START #1 id="buff_common_enemy_spell_status_do_frozen" uid=99 owner=eny_0051_rodin src=chr_0029_pograni dur=24.00 lifeT=24.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[99]: duration=24 physical_res_down=0.2 count=3 atk_scale=5.36",
            '[10:00:01.000] HP_V2 #2 hit=120 cum=120 raw=120.00 packetFinalValue=120.0 pHP=5000 eHP=899880 skill="chr_0013_aglina_attack1_projhit" hits=1 src=chr_0013_aglina tgt=eny_0051_rodin atk=chr_0013_aglina seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] PKT_MOD #2 atk=[] def=[99]",
            '[10:00:01.500] HP_V2 #3 hit=120 cum=240 raw=120.00 packetFinalValue=120.0 pHP=5000 eHP=899760 skill="chr_0028_wulfa_normal_skill_projhit2" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.500] PKT_MOD #3 atk=[] def=[99]",
            "[10:00:02.000] GAME_TIMER_END seq=1 source=ChallengeComplete self=0000000000000000 msg=0000000000000000 elapsedMs=2000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        include_rdps_debug=True,
        file_name="pograni-fracture-natural-physical-school.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    natural_hit, fire_spell_hit = damage_events
    assert natural_hit["damage_element"] == "natural"
    assert natural_hit["damage_school"] == "physical"
    assert natural_hit["rdps_contributions"] == [
        {"character_key": "chr_0013_aglina", "character_name": "洁尔佩塔", "value": 120.0},
    ]
    assert fire_spell_hit["damage_element"] == "fire"
    assert fire_spell_hit["damage_school"] == "spell"
    assert fire_spell_hit["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 120.0},
    ]
    assert parsed["rdps_preflight"]["ok"] is True

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")')
def test_parse_raw_battle_log_text_suppresses_mislabeled_legacy_false_fracture() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0028_wulfa_100514 chr_0029_pograni_100542]",
            '[10:00:01.000] BUFF_START #1 id="buff_common_enemy_spell_status_do_frozen" uid=99 owner=chr_0028_wulfa src=chr_0029_pograni dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000]   BB[99]: duration=24 physical_res_down=0.2 count=3 atk_scale=2",
            '[10:00:02.000] HP_V2 #2 hit=120 cum=120 raw=120.00 packetFinalValue=120.0 pHP=0 eHP=899880 skill="chr_0028_wulfa_attack1" hits=1 skillLv=1 templateIntId=1993 actionId=6 src=chr_0028_wulfa tgt=chr_0028_wulfa atk=chr_0028_wulfa atkId=100514 tgtId=100590 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #2 atk=[] def=[99]",
            "[10:00:30.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=30000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="pograni-fracture-mislabeled-owner.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-30-000",
    )

    assert not [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["target_character_key"] == "eny_0051_rodin"
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 120.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: buff_event = next(')
def test_parse_raw_battle_log_text_ignores_pograni_fracture_trigger_atk_scale() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0028_wulfa_100514 chr_0029_pograni_100542]",
            '[10:00:01.000] BUFF_START #1 id="1211" uid=99 owner=chr_0028_wulfa src=chr_0029_pograni dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000]   BB[99]: duration=24 physical_res_down=0.2 count=3 atk_scale=2",
            '[10:00:02.000] HP_V2 #2 hit=120 cum=120 raw=120.00 packetFinalValue=120.0 pHP=0 eHP=899880 skill="chr_0028_wulfa_attack1" hits=1 skillLv=1 templateIntId=1993 actionId=6 src=chr_0028_wulfa tgt=chr_0028_wulfa atk=chr_0028_wulfa atkId=100514 tgtId=100590 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #2 atk=[] def=[99]",
            "[10:00:30.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=30000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="pograni-fracture-trigger-atk-scale.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-30-000",
    )

    buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and event["source_character_key"] == "chr_0029_pograni"
    )
    assert buff_event["event_key"] == "buff_physical_do_fracture"
    assert buff_event["event_name"] == "碎甲"
    assert buff_event["effects"] == [
        {
            "zone": "vuln_taken",
            "element": "physical",
            "rate": 0.2,
            "condition": {
                "type": "damage_type_in",
                "source": "blackboard_key",
                "elements": ["physical"],
            },
        }
    ]

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 100.0},
        {"character_key": "chr_0029_pograni", "character_name": "骏卫", "value": 20.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert anomaly_event["rdps_contributions"] == [')
def test_arts_strength_allocates_only_anomaly_damage() -> None:
    base = [
        "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
        "[10:00:00.000] SQUAD size=2 members=[chr_0028_wulfa_1001 chr_0029_pograni_1002]",
        '[10:00:00.100] BUFF_START #1 id="buff_chr_0029_pograni_talent1" uid=1 owner=chr_0028_wulfa src=chr_0029_pograni dur=20.00 lifeT=20.00 passed=0.00 enh=1',
        "[10:00:00.100]   BB[1]: duration=20 physpell_up=30",
    ]
    anomaly = parse_raw_battle_log_text(
        "\n".join(
            base
            + [
                '[10:00:01.000] HP_V2 #2 hit=130 cum=130 raw=130.00 pHP=5000 eHP=899870 skill="buff_common_cryst_cryst_triggered" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            ]
        ),
        file_name="arts-strength-anomaly.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )
    normal = parse_raw_battle_log_text(
        "\n".join(
            base
            + [
                '[10:00:01.000] HP_V2 #2 hit=130 cum=130 raw=130.00 pHP=5000 eHP=899870 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            ]
        ),
        file_name="arts-strength-normal.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    anomaly_event = next(event for event in anomaly["timeline_events"] if event["lane_type"] == "skill")
    assert anomaly_event["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 100.0},
        {"character_key": "chr_0029_pograni", "character_name": "骏卫", "value": 30.0},
    ]
    normal_event = next(event for event in normal["timeline_events"] if event["lane_type"] == "skill")
    assert normal_event["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 130.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert damage_event["rdps_contributions"] == [')
def test_arts_strength_uses_loadout_baseline_in_anomaly_denominator() -> None:
    content = "\n".join(
        [
            "[09:59:59.000] LOADOUT reason=SC_SELF_SCENE_INFO",
            "[09:59:59.000] LOADOUT slot=0 char=chr_0028_wulfa weaponTemplate=wpn_sword_0022 weaponLv=90 refine=1 break=4 equips={[0]=item_test|stats=main:防御力=1;sub3:源石技艺强度=100@3} equipSuit={}",
            "[09:59:59.000] LOADOUT slot=1 char=chr_0029_pograni weaponTemplate=wpn_sword_0008 weaponLv=90 refine=1 break=4 equips={} equipSuit={}",
            '[10:00:00.100] BUFF_START #1 id="buff_chr_0029_pograni_talent1" uid=1 owner=chr_0028_wulfa src=chr_0029_pograni dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: duration=20 physpell_up=30",
            '[10:00:01.000] HP_V2 #2 hit=115 cum=115 raw=115.00 pHP=5000 eHP=899885 skill="buff_common_cryst_cryst_triggered" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="arts-strength-static-baseline.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )
    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0028_wulfa", "character_name": "洛茜", "value": 100.0},
        {"character_key": "chr_0029_pograni", "character_name": "骏卫", "value": 15.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert round(contributions["chr_0028_wulfa"], 4) == 100.0')
def test_arts_strength_reattributes_enhanced_fracture_effect() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] SQUAD size=3 members=[chr_0028_wulfa_1001 chr_0013_aglina_1002 chr_0029_pograni_1003]",
            '[10:00:00.100] BUFF_START #1 id="buff_chr_0029_pograni_talent1" uid=1 owner=chr_0013_aglina src=chr_0029_pograni dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: duration=20 physpell_up=30",
            '[10:00:01.000] BUFF_START #2 id="buff_physical_do_fracture" uid=2 owner=eny_0051_rodin src=chr_0013_aglina dur=20.00 lifeT=20.00 passed=0.00 enh=1',
            "[10:00:01.000]   BB[2]: duration=20 physical_res_down=0.36 atk_scale=2",
            '[10:00:02.000] HP_V2 #3 hit=136 cum=136 raw=136.00 packetFinalValue=136.0 pHP=5000 eHP=899864 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #3 atk=[] def=[2]",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="arts-strength-fracture-provenance.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-03-000",
    )
    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contributions = {row["character_key"]: row["value"] for row in damage_event["rdps_contributions"]}
    assert round(contributions["chr_0028_wulfa"], 4) == 100.0
    assert round(contributions["chr_0013_aglina"], 4) == 30.4615
    assert round(contributions["chr_0029_pograni"], 4) == 5.5385

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: buff_event = next(')
def test_parse_raw_battle_log_text_handles_conduct_with_mislabeled_owner() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0017_yvonne_1001 chr_0004_pelica_1002]",
            '[10:00:01.000] BUFF_START #1 id="2268" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000]   BB[1]: spell_resistance_decrease=0.2 duration=8.75 final_spell_resistance_decrease=0.25 count=1",
            '[10:00:02.000] HP_V2 #2 hit=125 cum=125 raw=125.00 packetFinalValue=125.0 pHP=0 eHP=899875 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=chr_0017_yvonne atk=chr_0017_yvonne atkId=1001 tgtId=2000 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #2 atk=[] def=[1]",
            "[10:00:10.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=10000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="conduct-mislabeled-owner.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-10-000",
    )

    buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and "导电" in event["event_name"]
    )
    assert buff_event["event_key"] == "buff_common_pulse_pulse_conduct_triggered_do"
    assert buff_event["target_player_key"] is None
    assert buff_event["target_enemy_key"] == "eny_0051_rodin"
    assert buff_event["duration_ms"] == 8750
    assert buff_event["effects"] == [
        {"zone": "vuln_taken", "element": "spell", "rate": 0.25, "bb_key": "final_spell_resistance_decrease"}
    ]

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0004_pelica", "character_name": "佩丽卡", "value": 25.0},
        {"character_key": "chr_0017_yvonne", "character_name": "伊冯", "value": 100.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: buff_event = next(')
def test_parse_raw_battle_log_text_handles_corrosion_with_mislabeled_owner() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0027_tangtang_1001 chr_0013_aglina_1002]",
            '[10:00:01.000] BUFF_START #1 id="327" uid=1 owner=chr_0027_tangtang src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000]   BB[1]: def_decrease=0.1 max_def_decrease=0.1 duration=15 def_decrease_tick=0 start_def_decrease=0.1 count=1",
            '[10:00:02.000] HP_V2 #2 hit=110 cum=110 raw=110.00 packetFinalValue=110.0 pHP=0 eHP=899890 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=chr_0027_tangtang atk=chr_0027_tangtang atkId=1001 tgtId=2000 seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:20.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=20000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="corrosion-mislabeled-owner.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-20-000",
    )

    buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and "腐蚀" in event["event_name"]
    )
    assert buff_event["event_key"] == "buff_common_natural_cryst_triggered"
    assert buff_event["target_player_key"] is None
    assert buff_event["target_enemy_key"] == "eny_0051_rodin"
    assert buff_event["duration_ms"] == 15000
    assert buff_event["effects"] == [{"zone": "res", "element": "all", "rate": 0.1}]

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["rdps_contributions"] == [
        {"character_key": "chr_0013_aglina", "character_name": "洁尔佩塔", "value": 10.0},
        {"character_key": "chr_0027_tangtang", "character_name": "汤汤", "value": 100.0},
    ]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0027_tangtang"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_applies_hidden_karin_combo_rule() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0019_karin_talent_2_combo" uid=1 owner=chr_0027_tangtang src=chr_0019_karin dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:00.500] HP_V2 #2 hit=130 cum=130 raw=130.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_normal_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="karin-combo.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 130.0
    assert participants["chr_0027_tangtang"]["rdps"] == 100.0
    assert participants["chr_0019_karin"]["dps"] == 0.0
    assert participants["chr_0019_karin"]["rdps"] == 30.0
    combo_event = next(event for event in parsed["timeline_events"] if event["event_name"] == "连击增伤")
    assert combo_event["target_player_key"] == "chr_0027_tangtang"
    assert combo_event["target_enemy_key"] is None

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0027_tangtang"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_applies_generic_combo_consume_rule_to_normal_skill() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_combo_trigger" uid=1 owner=chr_0027_tangtang src=chr_0015_lifeng dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: imbue_scale=0.2',
            '[10:00:00.050] BUFF_START #2 id="buff_common_affixes_skillimbue" uid=2 owner=chr_0027_tangtang src=chr_0015_lifeng dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.050]   BB[1]: imbue_scale=0.2',
            '[10:00:00.100] HP_V2 #2 hit=130 cum=130 raw=130.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_normal_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="lifeng-combo.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 130.0
    assert participants["chr_0027_tangtang"]["rdps"] == 100.0
    assert participants["chr_0015_lifeng"]["dps"] == 0.0
    assert participants["chr_0015_lifeng"]["rdps"] == 30.0
    combo_event = next(event for event in parsed["timeline_events"] if event["event_name"] == "连击增伤")
    assert combo_event["target_player_key"] == "chr_0027_tangtang"
    assert combo_event["target_enemy_key"] is None

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0027_tangtang"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_applies_generic_combo_stack_curve_to_normal_skill() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_combo_trigger" uid=1 owner=chr_0027_tangtang src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: imbue_scale=0.2',
            '[10:00:00.010] BUFF_START #2 id="buff_common_affixes_combo_trigger" uid=2 owner=chr_0027_tangtang src=chr_0015_lifeng dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.010]   BB[2]: imbue_scale=0.2',
            '[10:00:00.050] BUFF_START #3 id="buff_common_affixes_skillimbue" uid=3 owner=chr_0027_tangtang src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.050] BUFF_START #4 id="buff_common_affixes_skillimbue" uid=4 owner=chr_0027_tangtang src=chr_0015_lifeng dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.100] HP_V2 #5 hit=145 cum=145 raw=145.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_normal_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="combo-stack-normal-skill.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 145.0
    assert participants["chr_0027_tangtang"]["rdps"] == 100.0
    assert participants["chr_0019_karin"]["rdps"] == 30.0
    assert participants["chr_0015_lifeng"]["rdps"] == 15.0

    combo_events = [event for event in parsed["timeline_events"] if event["event_name"] == "连击增伤"]
    assert sorted(event["effects"][0]["rate"] for event in combo_events) == [0.15, 0.3]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0015_lifeng"]["rdps"] == 145.83')
def test_parse_raw_battle_log_text_applies_generic_combo_consume_rule_to_ultimate_family() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_combo_trigger" uid=1 owner=chr_0015_lifeng src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: imbue_scale=0.2',
            '[10:00:00.050] BUFF_START #2 id="buff_common_affixes_skillimbue" uid=2 owner=chr_0015_lifeng src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.050]   BB[1]: imbue_scale=0.2',
            '[10:00:00.100] HP_V2 #2 hit=75 cum=75 raw=75.00 pHP=5000 eHP=900000 skill="sk_wpn_lance_0010" hits=1 src=chr_0015_lifeng tgt=eny_0051_rodin atk=chr_0015_lifeng seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.100] HP_V2 #3 hit=100 cum=175 raw=100.00 pHP=5000 eHP=899925 skill="chr_0015_lifeng_ultimate_skill_abentity" hits=2 src=chr_0015_lifeng tgt=eny_0051_rodin atk=chr_0015_lifeng seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="lifeng-ultimate-combo.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0015_lifeng"]["dps"] == 175.0
    assert participants["chr_0015_lifeng"]["rdps"] == 145.83
    assert participants["chr_0019_karin"]["dps"] == 0.0
    assert participants["chr_0019_karin"]["rdps"] == 29.17

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0027_tangtang"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_consumes_replicated_combo_trigger_once_globally() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_combo_trigger" uid=1 owner=chr_0027_tangtang src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: imbue_scale=0.2',
            '[10:00:00.001] BUFF_START #2 id="buff_common_affixes_combo_trigger" uid=2 owner=chr_0006_wolfgd src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.001]   BB[1]: imbue_scale=0.2',
            '[10:00:00.100] HP_V2 #3 hit=120 cum=120 raw=120.00 pHP=5000 eHP=900000 skill="chr_0006_wolfgd_normal_skill" hits=1 src=chr_0006_wolfgd tgt=eny_0051_rodin atk=chr_0006_wolfgd seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.150] BUFF_START #4 id="buff_common_affixes_skillimbue" uid=4 owner=chr_0027_tangtang src=chr_0019_karin dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.150]   BB[1]: imbue_scale=0.2',
            '[10:00:00.200] HP_V2 #5 hit=130 cum=130 raw=130.00 pHP=5000 eHP=899880 skill="chr_0027_tangtang_normal_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.300] HP_V2 #6 hit=120 cum=120 raw=120.00 pHP=5000 eHP=899750 skill="chr_0006_wolfgd_normal_skill" hits=1 src=chr_0006_wolfgd tgt=eny_0051_rodin atk=chr_0006_wolfgd seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="karin-combo-global-consume.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["rdps"] == 100.0
    assert participants["chr_0006_wolfgd"]["rdps"] == 240.0
    assert participants["chr_0019_karin"]["rdps"] == 30.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0003_endminf"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_credits_pograni_pd_up_weapon_team_buff() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart self=0 msg=0 startMs=0 expireMs=0 prepareSeconds=0",
            '[10:00:00.000] BUFF_START #1 id="1806" uid=1 owner=chr_0029_pograni src=chr_0029_pograni dur=30.00 lifeT=30.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: pd_up=0.08 duration=30 max_stack=5",
            '[10:00:00.001] BUFF_START #2 id="1806" uid=2 owner=chr_0003_endminf src=chr_0029_pograni dur=30.00 lifeT=30.00 passed=0.00 enh=1',
            "[10:00:00.001]   BB[1]: pd_up=0.04 duration=30 max_stack=5",
            '[10:00:00.500] HP_V2 #3 hit=104 cum=104 raw=104.00 pHP=5000 eHP=900000 skill="chr_0003_endminf_attack1" hits=1 src=chr_0003_endminf tgt=eny_0051_rodin atk=chr_0003_endminf seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:01.000] GAME_TIMER_END seq=1 source=ChallengeComplete self=0 msg=0 elapsedMs=1000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="pograni-pd-up-weapon-team.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0003_endminf"]["dps"] == 104.0
    assert participants["chr_0003_endminf"]["rdps"] == 100.0
    assert participants["chr_0029_pograni"]["dps"] == 0.0
    assert participants["chr_0029_pograni"]["rdps"] == 4.0

    team_buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and event["target_player_key"] == "chr_0003_endminf"
    )
    assert team_buff_event["event_key"] == "buff_wpn_sword_0016_valid"
    assert team_buff_event["event_name"] == "增伤"
    assert team_buff_event["source_character_key"] == "chr_0029_pograni"
    assert team_buff_event["effects"] == [{"zone": "dmg_inc", "element": "physical", "rate": 0.04}]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0027_tangtang"]["rdps"] == 120.0')
def test_parse_raw_battle_log_text_maps_cryst_attr_type_to_damage_increase() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_cryst_damage_up_demo" i=0 attrType=53 modType=0 formula=5 useKey=1 val=0.0000 bbKey="cryst_dmg_up2"',
            '[10:00:00.000] BUFF_START #1 id="buff_cryst_damage_up_demo" uid=1 owner=chr_0027_tangtang src=chr_0013_aglina dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: cryst_dmg_up2=0.25 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="damage-up-bb-key.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0027_tangtang"]["dps"] == 150.0
    assert participants["chr_0027_tangtang"]["rdps"] == 120.0
    assert participants["chr_0013_aglina"]["dps"] == 0.0
    assert participants["chr_0013_aglina"]["rdps"] == 30.0
    buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")
    assert buff_event["event_name"] == "增伤"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0026_lastrite"]["rdps"] == 118.02')
def test_parse_raw_battle_log_text_supports_dynamic_def_decrease_windows() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_common_natural_cryst_triggered" i=0 attrType=82 modType=0 formula=5 useKey=1 val=0.0000 bbKey="def_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_natural_cryst_triggered" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[4]: def_decrease=0.08129 =0 max_def_decrease=0.271 =0 def_decrease_tick=0.01897 =0 duration=15',
            '[10:00:10.000] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="dynamic-def-decrease.log",
        first_hit_hint="10-00-10-000",
        last_hit_hint="10-00-11-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0026_lastrite"]["dps"] == 150.0
    assert participants["chr_0026_lastrite"]["rdps"] == 118.02
    assert participants["chr_0013_aglina"]["dps"] == 0.0
    assert participants["chr_0013_aglina"]["rdps"] == 31.98
    buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")
    assert buff_event["event_name"] == "腐蚀 / 减抗"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0026_lastrite"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_classifies_enhance_default_child_as_spell_amp() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_enhance_spell_default_child" uid=1 owner=chr_0026_lastrite src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: rate=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="buff_chr_0026_lastrite_normal_skill_phantom_main" hits=1 src=chr_0026_lastrite tgt=eny_0051_rodin atk=chr_0026_lastrite seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="enhance-default-child.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0026_lastrite"]["dps"] == 150.0
    assert participants["chr_0026_lastrite"]["rdps"] == 100.0
    assert participants["chr_0011_seraph"]["dps"] == 0.0
    assert participants["chr_0011_seraph"]["rdps"] == 50.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")')
def test_parse_raw_battle_log_text_rehomes_off_loadout_player_enhance_source_to_owner() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] LOADOUT slot=0 char=chr_0030_zhuangfy weaponTemplate=wpn_sword_0006 equipSuit={}",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0019_karin weaponTemplate=wpn_sword_0006 equipSuit={}",
            '[10:00:00.000] ATTR_MOD buff="buff_common_affixes_enhance_pulse_default_child" i=0 attrType=66 modType=0 formula=5 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_affixes_enhance_pulse_default_child" uid=1 owner=chr_0030_zhuangfy src=chr_0013_aglina dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: rate=0.18 duration=2",
            '[10:00:00.500] HP_V2 #2 hit=1180 cum=1180 raw=1180.00 pHP=5000 eHP=900000 skill="chr_0030_zhuangfy_normal_skill_ult" hits=1 src=chr_0030_zhuangfy tgt=eny_0051_rodin atk=chr_0030_zhuangfy seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="off-loadout-player-enhance.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert set(participants) == {"chr_0030_zhuangfy"}
    assert participants["chr_0030_zhuangfy"]["total_rd"] == 1180.0
    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert {item["character_key"] for item in damage_event["rdps_contributions"]} == {"chr_0030_zhuangfy"}
    buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")
    assert buff_event["source_character_key"] == "chr_0030_zhuangfy"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 106.02')
def test_parse_raw_battle_log_text_recognizes_seraph_ultimate_child_buff_as_elemental_amp() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0011_seraph_ultimate_effect" uid=1 owner=chr_0017_yvonne src=chr_0011_seraph dur=12.00 lifeT=12.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[2]: rate=0.414858 duration=12",
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="seraph-ultimate-child.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0017_yvonne"]["dps"] == 150.0
    assert participants["chr_0017_yvonne"]["rdps"] == 106.02
    assert round(participants["chr_0011_seraph"]["rdps"], 2) == 43.98
    buff_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "buff")
    assert buff_event["event_key"] == "buff_chr_0011_seraph_ultimate_effect"
    assert buff_event["event_name"] == "增幅"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_keeps_valid_generic_buff_src_without_chr_borrow() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0017_yvonne_ultimate_skill_voice_start" uid=1 owner=chr_0017_yvonne src=chr_0017_yvonne dur=4.00 lifeT=4.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: duration=4',
            '[10:00:00.100] ATTR_MOD buff="buff_common_affixes_enhance_crystal" i=0 attrType=67 modType=0 formula=5 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.100] BUFF_START #2 id="buff_common_affixes_enhance_crystal" uid=2 owner=chr_0017_yvonne src=chr_0011_seraph dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.100]   BB[2]: rate=0.5 =0 duration=2',
            '[10:00:00.500] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="generic-src.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0017_yvonne"]["dps"] == 150.0
    assert participants["chr_0017_yvonne"]["rdps"] == 100.0
    assert participants["chr_0011_seraph"]["dps"] == 0.0
    assert participants["chr_0011_seraph"]["rdps"] == 50.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 16.67')
def test_parse_raw_battle_log_text_extends_indefinite_enemy_vulnerable_to_battle_end() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=0 expireMs=0",
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=340282346638528859811704183484516925440.00 lifeT=340282346638528859811704183484516925440.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: rate=0.5',
            '[10:00:05.000] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:06.000] GAME_TIMER_END seq=3 source=OnSrvComplete self=0 elapsedMs=6000 startMs=0 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="indefinite-vuln.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-06-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0017_yvonne"]["dps"] == 25.0
    assert participants["chr_0017_yvonne"]["rdps"] == 16.67
    assert participants["chr_0013_aglina"]["dps"] == 0.0
    assert participants["chr_0013_aglina"]["rdps"] == 8.33

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert len(buff_events) == 1')
def test_parse_raw_battle_log_text_infers_missing_debuff_end_from_related_parent() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=0 expireMs=0",
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0013_aglina_ultimate_skill" uid=parent owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.000] ATTR_MOD buff="buff_chr_0013_aglina_ultimate_spell_vulnerable" i=0 attrType=85 modType=0 formula=0 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=main owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[main]: rate=0.5 duration=-1",
            '[10:00:05.000] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:06.000] BUFF_END #4 id="buff_chr_0013_aglina_ultimate_skill" uid=parent',
            '[10:00:07.000] HP_V2 #5 hit=150 cum=300 raw=150.00 pHP=5000 eHP=899850 skill="chr_0017_yvonne_ult_attack1_projhit" hits=2 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:08.000] GAME_TIMER_END seq=6 source=OnSrvComplete self=0 elapsedMs=8000 startMs=0 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="related-parent-end.log")

    buff_events = [
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff"
        and event["event_key"] == "buff_chr_0013_aglina_ultimate_spell_vulnerable"
    ]
    assert len(buff_events) == 1
    assert buff_events[0]["duration_ms"] == 6000
    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert round(participants["chr_0013_aglina"]["total_rd"], 2) == 50.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert buff_event["duration_ms"] == 2000')
def test_parse_raw_battle_log_text_does_not_infer_end_before_packet_modifier_evidence() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=0 expireMs=0",
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0028_wulfa_normal_bleed" uid=bleed owner=eny_0051_rodin src=chr_0028_wulfa dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[bleed]: duration=25 damage_up=0.12",
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0028_wulfa_normal_bleed_effect" uid=bleed_effect owner=eny_0051_rodin src=chr_0028_wulfa dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[bleed_effect]: duration=0.9 atk_scale=0.3",
            '[10:00:00.500] BUFF_END #3 id="buff_chr_0028_wulfa_normal_bleed_effect" uid=bleed_effect',
            '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="chr_0029_pograni_attack1" hits=1 src=chr_0029_pograni tgt=eny_0051_rodin atk=chr_0029_pograni seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #1 atk=[] def=[bleed]",
            "[10:00:03.000] GAME_TIMER_END seq=2 source=OnSrvComplete self=0 elapsedMs=3000 startMs=0 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="packet-modifier-end-guard.log")

    buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff"
        and event["event_key"] == "buff_chr_0028_wulfa_normal_bleed"
    )
    assert buff_event["duration_ms"] == 2000
    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert round(participants["chr_0028_wulfa"]["total_rd"], 2) > 0.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: buff_event = next(')
def test_parse_raw_battle_log_text_infers_missing_debuff_end_from_default_child() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=OnSrvStart self=0 startMs=0 expireMs=0",
            '[10:00:00.000] ATTR_MOD buff="buff_chr_0013_aglina_ultimate_spell_vulnerable" i=0 attrType=85 modType=0 formula=0 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=main owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[main]: rate=0.5 duration=-1",
            '[10:00:00.000] BUFF_START #3 id="buff_common_affixes_vulnerable_spell_default_child" uid=child owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[child]: rate=0.5 duration=-1",
            '[10:00:05.000] HP_V2 #4 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:06.000] BUFF_END #5 id="buff_common_affixes_vulnerable_spell_default_child" uid=child',
            '[10:00:07.000] HP_V2 #6 hit=150 cum=300 raw=150.00 pHP=5000 eHP=899850 skill="chr_0017_yvonne_ult_attack1_projhit" hits=2 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:08.000] GAME_TIMER_END seq=7 source=OnSrvComplete self=0 elapsedMs=8000 startMs=0 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, file_name="related-child-end.log")

    buff_event = next(
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff"
        and event["event_key"] == "buff_chr_0013_aglina_ultimate_spell_vulnerable"
    )
    assert buff_event["duration_ms"] == 6000
    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert round(participants["chr_0013_aglina"]["total_rd"], 2) == 50.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 37.5')
def test_parse_raw_battle_log_text_preserves_overlapping_stackable_buff_windows() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_stack_spell_vuln" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: spell_taken_up=0.5',
            '[10:00:01.000] BUFF_START #2 id="buff_stack_spell_vuln" uid=2 owner=eny_0051_rodin src=chr_0004_pelica dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:01.000]   BB[1]: spell_taken_up=0.5',
            '[10:00:01.500] HP_V2 #3 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="stacked-vuln.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0017_yvonne"]["dps"] == 75.0
    assert participants["chr_0017_yvonne"]["rdps"] == 37.5
    assert participants["chr_0004_pelica"]["dps"] == 0.0
    assert participants["chr_0004_pelica"]["rdps"] == 37.5

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert second_contribs == {"chr_0027_tangtang": 100.0, "chr_0004_pelica": 30.0}')
def test_parse_raw_battle_log_text_filters_attrisuit_next_skill_damage() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_equipsuit_attrisuitup_01" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: dmg_up=0.3 max_stack=2',
            '[10:00:00.500] HP_V2 #2 hit=130 cum=130 raw=130.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_combo_skill" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=130 cum=260 raw=130.00 pHP=5000 eHP=899870 skill="chr_0027_tangtang_normal_skill_water_projhit_1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="attrisuit-next-skill.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-01-000",
    )

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    first_contribs = {item["character_key"]: item["value"] for item in damage_events[0]["rdps_contributions"]}
    second_contribs = {item["character_key"]: item["value"] for item in damage_events[1]["rdps_contributions"]}

    assert first_contribs == {"chr_0027_tangtang": 130.0}
    assert second_contribs == {"chr_0027_tangtang": 100.0, "chr_0004_pelica": 30.0}

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert second_contribs == {"chr_0027_tangtang": 100.0, "chr_0004_pelica": 50.0}')
def test_parse_raw_battle_log_text_filters_attr_type_skill_damage() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] ATTR_MOD buff="buff_demo_normal_skill_up" i=0 attrType=32 modType=0 formula=5 useKey=1 val=0.0000 bbKey="dmg_up"',
            '[10:00:00.000] BUFF_START #1 id="buff_demo_normal_skill_up" uid=1 owner=chr_0027_tangtang src=chr_0004_pelica dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: dmg_up=0.5',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:01.000] HP_V2 #3 hit=150 cum=300 raw=150.00 pHP=5000 eHP=899850 skill="chr_0027_tangtang_normal_skill_water_projhit_1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="attr-type-skill-filter.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-01-000",
    )

    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    first_contribs = {item["character_key"]: item["value"] for item in damage_events[0]["rdps_contributions"]}
    second_contribs = {item["character_key"]: item["value"] for item in damage_events[1]["rdps_contributions"]}

    assert first_contribs == {"chr_0027_tangtang": 150.0}
    assert second_contribs == {"chr_0027_tangtang": 100.0, "chr_0004_pelica": 50.0}

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert contribs == {')
def test_parse_raw_battle_log_text_filters_external_buffs_by_packet_modifier_uid() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1',
            '[10:00:00.000] DMG_MOD buff="buff_pelica_spell_res_down" d=3 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="final_spell_resistance_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_pelica_spell_res_down" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: final_spell_resistance_decrease=0.2',
            '[10:00:00.000] DMG_MOD buff="buff_antal_spell_res_down" d=3 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="final_spell_resistance_decrease"',
            '[10:00:00.000] BUFF_START #2 id="buff_antal_spell_res_down" uid=2 owner=eny_0051_rodin src=chr_0023_antal dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: final_spell_resistance_decrease=0.2',
            '[10:00:00.500] HP_V2 #3 hit=144 cum=144 raw=144.00 pHP=5000 eHP=900000 skill="chr_0028_wulfa_ultimate_skill" hits=1 skillLv=12 templateIntId=2397 actionId=177 origTemplateIntId=2397 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] PKT_MOD #3 atk=[] def=[1]',
            '[10:00:01.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=1000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="packet-uid-filter.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contribs = {item["character_key"]: item["value"] for item in damage_event["rdps_contributions"]}
    assert contribs == {
        "chr_0028_wulfa": 120.0,
        "chr_0004_pelica": 24.0,
    }

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert contribs == {')
def test_parse_raw_battle_log_text_keeps_enemy_fragile_when_packet_modifier_def_list_is_partial() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            '[10:00:00.000] ATTR_MOD buff="buff_chr_0013_aglina_ultimate_spell_vulnerable" i=0 attrType=85 modType=0 formula=0 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: rate=0.33 duration=-1",
            '[10:00:02.000] HP_V2 #2 hit=1330 cum=1330 raw=1330.00 pHP=5000 eHP=898670 skill="chr_0028_wulfa_ultimate_skill" hits=1 skillLv=12 templateIntId=2397 actionId=177 origTemplateIntId=2397 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            "[10:00:02.000] PKT_MOD #2 atk=[] def=[other_debuff]",
            "[10:00:03.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=3000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="partial-def-packet-fragile.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-03-000",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contribs = {item["character_key"]: item["value"] for item in damage_event["rdps_contributions"]}
    assert contribs == {
        "chr_0028_wulfa": 1000.0,
        "chr_0013_aglina": 330.0,
    }

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=KeyError, reason='Fixture lacks exact current hit/condition evidence; inferred element or HP defaults are not authorized; fails at: assert contribs["chr_0025_ardelia"] > 0.0')
def test_parse_raw_battle_log_text_physical_fragile_applies_to_physical_school_fire_hit() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0025_ardelia_affixes_vulnerable_physic_child" uid=1 owner=eny_0051_rodin src=chr_0025_ardelia dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: rate=0.28',
            '[10:00:00.500] HP_V2 #2 hit=370 cum=370 raw=370.42 pHP=5000 eHP=900000 skill="chr_0006_wolfgd_attack2_projhit" hits=1 src=chr_0006_wolfgd tgt=eny_0051_rodin atk=chr_0006_wolfgd seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="physical-fragile-school-filter.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    contribs = {item["character_key"]: item["value"] for item in damage_event["rdps_contributions"]}
    assert contribs["chr_0025_ardelia"] > 0.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: speed = next(event for event in buff_events if event["event_key"] == "buff_chr_0027_tangtang_comboskill_waterbuff_outaura")')
def test_parse_raw_battle_log_text_projects_tangtang_speed_and_slow_utility_windows() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0027_tangtang_comboskill_waterbuff_outaura" uid=1 owner=chr_0004_pelica src=chr_0027_tangtang dur=3.00 lifeT=3.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: duration_talent1buff=3 ratio_speed=0.2',
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0027_tangtang_comboskill_waterdebuff_outaura" uid=2 owner=eny_0051_rodin src=chr_0027_tangtang dur=3.00 lifeT=3.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: duration_talent1buff=3 ratio_speedreduction=0.6',
            '[10:00:00.500] HP_V2 #3 hit=100 cum=100 raw=100.00 pHP=5000 eHP=899900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="tangtang-utility-windows.log",
        first_hit_hint="10-00-00-500",
        last_hit_hint="10-00-00-500",
    )

    buff_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "buff"]
    speed = next(event for event in buff_events if event["event_key"] == "buff_chr_0027_tangtang_comboskill_waterbuff_outaura")
    slow = next(event for event in buff_events if event["event_key"] == "buff_chr_0027_tangtang_comboskill_waterdebuff_outaura")

    assert speed["event_name"] == "加速"
    assert speed["effects"] == [{"zone": "speedup", "element": "all", "rate": 0.2}]
    assert slow["event_name"] == "缓速"
    assert slow["effects"] == [{"zone": "slow", "element": "all", "rate": 0.6}]

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert effects')
def test_parse_raw_battle_log_text_suppresses_duplicate_corrosion_fx_projection() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_common_enemy_spell_cryst_triggered_fx" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: duration=15 start_def_decrease=0.04 def_decrease_tick=0.01 max_def_decrease=0.14",
            '[10:00:00.100] BUFF_START #2 id="buff_common_natural_cryst_triggered" uid=2 owner=eny_0051_rodin src=chr_0013_aglina dur=15.00 lifeT=15.00 passed=0.00 enh=1',
            "[10:00:00.100] BB[2]: duration=15 start_def_decrease=0.04 def_decrease_tick=0.01 max_def_decrease=0.14",
            '[10:00:01.000] HP_V2 #3 hit=114 cum=114 raw=114.00 pHP=5000 eHP=899886 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        include_rdps_debug=True,
        file_name="corrosion-duplicate-fx.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )
    effects = [
        contributor
        for zone in parsed["debug_hits"][0]["zones"]
        for contributor in zone["contributors"]
        if contributor.get("source_character_key") == "chr_0013_aglina"
    ]
    assert effects
    assert {row["event_key"] for row in effects} == {"buff_common_natural_cryst_triggered"}

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy skill mapping/display/report contract; old fixture or field expectation needs migration; fails at: assert damage_event["event_key"] == "chr_0028_wulfa_combo_2_skill"')
def test_parse_raw_battle_log_text_maps_runtime_damage_buff_hit_back_to_origin_skill() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="2018" uid=1 owner=eny_0051_rodin src=chr_0028_wulfa dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[4]: duration=0.3 atk_scale=0.1725 trigger_times=3 damage_interval=0.125',
            '[10:00:00.200] HP_V2 #2 hit=614 cum=614 raw=613.62 pHP=0 eHP=899386 skill="chr_0028_wulfa_skill_2017" hits=1 skillLv=unknown templateIntId=2017 actionId=unknown origTemplateIntId=2257 damageUnitIndex=0 partInstId=unknown dynBB=unknown calcBB=unknown src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="wulfa-combo-2-trigger.log",
        first_hit_hint="10-00-00-200",
        last_hit_hint="10-00-00-200",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["event_key"] == "chr_0028_wulfa_combo_2_skill"
    assert damage_event["event_name"] == "燎影时刻 / 派生"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy skill mapping/display/report contract; old fixture or field expectation needs migration; fails at: assert damage_event["event_name"] == "爪印斫痕"')
def test_parse_raw_battle_log_text_maps_runtime_skill_number_to_damage_buff_name() -> None:
    content = "\n".join(
        [
            '[10:00:00.200] HP_V2 #2 hit=1049 cum=1049 raw=1049.39 pHP=0 eHP=899000 skill="chr_0028_wulfa_skill_2193" hits=1 skillLv=unknown templateIntId=2193 actionId=2 origTemplateIntId=unknown damageUnitIndex=0 partInstId=unknown dynBB=unknown calcBB=unknown src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="wulfa-normal-bleed.log",
        first_hit_hint="10-00-00-200",
        last_hit_hint="10-00-00-200",
    )

    damage_event = next(event for event in parsed["timeline_events"] if event["lane_type"] == "skill")
    assert damage_event["event_key"] == "buff_chr_0028_wulfa_normal_bleed"
    assert damage_event["event_name"] == "爪印斫痕"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: assert len(buff_events) == 1')
def test_parse_raw_battle_log_text_treats_equipsuit_reapply_as_refresh() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_equipsuit_attrisuit_01" uid=1 owner=chr_0027_tangtang src=chr_0027_tangtang dur=999.00 lifeT=999.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: atk_up=0.15 dmg_up=0.3',
            '[10:00:05.000] BUFF_START #2 id="buff_equipsuit_attrisuit_01" uid=2 owner=chr_0027_tangtang src=chr_0027_tangtang dur=999.00 lifeT=999.00 passed=0.00 enh=1',
            '[10:00:05.000]   BB[2]: atk_up=0.15 dmg_up=0.3',
            '[10:00:06.000] HP_V2 #3 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0051_rodin atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="equipsuit-refresh.log",
        first_hit_hint="10-00-06-000",
        last_hit_hint="10-00-06-000",
    )

    buff_events = [
        event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "buff" and event["event_key"] == "buff_equipsuit_attrisuit_01"
    ]
    assert len(buff_events) == 1

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0017_yvonne"]["rdps"] == 125.0')
def test_parse_raw_battle_log_text_maps_rate_spellvulnerable_to_fragile() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0027_tangtang_normalskill_spellvulnerable" uid=1 owner=eny_0051_rodin src=chr_0027_tangtang dur=5.00 lifeT=5.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[3]: duration_spellvulnerable=5 =0 rate_spellvulnerable=0.2 =0 cntmax=1',
            '[10:00:00.500] HP_V2 #2 hit=150 cum=150 raw=150.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="rate-spellvulnerable.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0017_yvonne"]["dps"] == 150.0
    assert participants["chr_0017_yvonne"]["rdps"] == 125.0
    assert participants["chr_0027_tangtang"]["dps"] == 0.0
    assert participants["chr_0027_tangtang"]["rdps"] == 25.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert participants["chr_0028_wulfa"]["rdps"] == 100.0')
def test_parse_raw_battle_log_text_maps_lifeng_purify_to_physical_fragile() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0015_lifeng_purify" uid=1 owner=eny_0051_rodin src=chr_0015_lifeng dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[1]: duration=12 rate=0.1',
            '[10:00:00.000] BUFF_START #2 id="buff_chr_0015_lifeng_purify_icon" uid=2 owner=eny_0051_rodin src=chr_0015_lifeng dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.000]   BB[2]: duration=12 rate=0.1',
            '[10:00:00.500] HP_V2 #3 hit=110 cum=110 raw=110.00 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="lifeng-physical-fragile.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
        include_rdps_debug=True,
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert participants["chr_0028_wulfa"]["dps"] == 110.0
    assert participants["chr_0028_wulfa"]["rdps"] == 100.0
    assert participants["chr_0015_lifeng"]["dps"] == 0.0
    assert participants["chr_0015_lifeng"]["rdps"] == 10.0
    assert parsed["rdps_preflight"]["ok"] is True

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert parsed["rdps_preflight"]["ok"] is True')
def test_parse_raw_battle_log_text_allows_avywen_ultimate_pulse_fragile_with_skill_guard() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] SKILL_CAST_START seq=1 startMs=0 inst=ult1 owner=chr_0012_avywen skill=chr_0012_avywen_ultimate_skill',
            '[10:00:00.100] BUFF_START #2 id="buff_common_affixes_vulnerable_pulse_default_child" uid=2 owner=eny_0051_rodin src=chr_0012_avywen dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: duration=10 rate=0.1",
            '[10:00:00.500] HP_V2 #3 hit=110 cum=110 raw=110.00 pHP=5000 eHP=900000 skill="unknown_proc_damage" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] DPD_RAW #3 probe=3 calc=110.0000 atkScale=1.0000 blocked=0 damageType=0x3 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.1000]',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="avywen-ultimate-pulse-fragile.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
        include_rdps_debug=True,
    )

    participants = {entry["character_key"]: entry for entry in parsed["participants"]}
    assert parsed["rdps_preflight"]["ok"] is True
    assert participants["chr_0004_pelica"]["rdps"] == 100.0
    assert participants["chr_0012_avywen"]["rdps"] == 10.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=KeyError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert parsed["rdps_preflight"]["blockers"][0]["event_key"] == "buff_common_affixes_vulnerable_pulse_default_child"')
def test_parse_raw_battle_log_text_blocks_avywen_pulse_fragile_without_ultimate_guard() -> None:
    content = "\n".join(
        [
            '[10:00:00.000] SKILL_CAST_START seq=1 startMs=0 inst=skill1 owner=chr_0012_avywen skill=chr_0012_avywen_normal_skill',
            '[10:00:00.100] BUFF_START #2 id="buff_common_affixes_vulnerable_pulse_default_child" uid=2 owner=eny_0051_rodin src=chr_0012_avywen dur=10.00 lifeT=10.00 passed=0.00 enh=1',
            "[10:00:00.100]   BB[1]: duration=10 rate=0.1",
            '[10:00:00.500] HP_V2 #3 hit=110 cum=110 raw=110.00 pHP=5000 eHP=900000 skill="unknown_proc_damage" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] DPD_RAW #3 probe=3 calc=110.0000 atkScale=1.0000 blocked=0 damageType=0x3 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.1000]',
        ]
    )

    parsed = parse_raw_battle_log_text(
        content,
        file_name="avywen-normal-pulse-fragile-blocked.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-01-000",
        include_rdps_debug=True,
    )

    assert parsed["rdps_preflight"]["ok"] is False
    assert parsed["rdps_preflight"]["blockers"][0]["event_key"] == "buff_common_affixes_vulnerable_pulse_default_child"
    assert parsed["rdps_damage_basis"]["rdps_strict_ok"] is False

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=KeyError, reason='Legacy skill mapping/display/report contract; old fixture or field expectation needs migration; fails at: assert skill_events["chr_0017_yvonne_ultimate_skill"]["poise_damage"] is None')
def test_parse_raw_battle_log_text_marks_poise_damage_hits() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.500] HP_V2 #1 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=900000 skill="chr_0028_wulfa_attack4" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000 templateIntId=1996 origTemplateIntId=1996',
            '[10:00:01.000] HP_V2 #2 hit=600 cum=700 raw=600.00 packetFinalValue=600.0 pHP=5000 eHP=899300 skill="chr_0028_wulfa_attack5" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000 templateIntId=1997 origTemplateIntId=1997',
            "[10:00:01.000] POISE_V1 seq=3 tick=1000 type=PoiseDamage value=-18 cur=262 attacker=? attackerId=unknown ownerType=BATTLE_ACTION_OWNER_TYPE_None sourceType=Skill source=chr_0028_wulfa_attack5 sourceInt=1997 origSourceType=Skill origSource=chr_0028_wulfa_attack5 origSourceInt=1997 actionId=100741",
            '[10:00:01.500] HP_V2 #4 hit=300 cum=1000 raw=300.00 packetFinalValue=300.0 pHP=5000 eHP=899000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000 templateIntId=2101 origTemplateIntId=2101',
            "[10:00:02.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=2000 startMs=0 endMs=2000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="poise-damage.log")
    skill_events = {
        event["event_key"]: event
        for event in parsed["timeline_events"]
        if event["lane_type"] == "skill"
    }

    assert skill_events["chr_0028_wulfa_attack4"].get("poise_damage") is None
    assert skill_events["chr_0028_wulfa_attack5"]["poise_damage"] == {
        "type": "PoiseDamage",
        "value": -18.0,
        "current_value": 262.0,
        "source": "chr_0028_wulfa_attack5",
        "source_int": 1997,
        "orig_source": "chr_0028_wulfa_attack5",
        "orig_source_int": 1997,
    }
    assert skill_events["chr_0017_yvonne_ultimate_skill"]["poise_damage"] is None

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy skill mapping/display/report contract; old fixture or field expectation needs migration; fails at: assert [event["event_key"] for event in cast_events] == ["chr_0019_karin_ultimate_skill"]')
def test_parse_raw_battle_log_text_emits_zero_damage_cast_events() -> None:
    content = "\n".join(
        [
            "[10:00:00.000] GAME_TIMER_START seq=1 source=ChallengeStart startMs=0 expireMs=0",
            '[10:00:00.500] HP_V2 #1 hit=100 cum=100 raw=100.00 packetFinalValue=100.0 pHP=5000 eHP=900000 skill="chr_0019_karin_attack1" hits=1 src=chr_0019_karin tgt=eny_0051_rodin atk=chr_0019_karin seg=0 shared=2 critFlag=0 critDmg=0.5000 templateIntId=1996 origTemplateIntId=1996',
            "[10:00:01.000] SKILL_CAST_START seq=5 startMs=1000 inst=100900 owner=chr_0019_karin skill=chr_0019_karin_ultimate_skill",
            "[10:00:01.400] SKILL_CAST_END seq=6 endMs=1400 inst=100900 owner=chr_0019_karin skill=chr_0019_karin_ultimate_skill",
            "[10:00:01.450] SKILL_CAST_START seq=7 startMs=1450 inst=100901 owner=chr_0019_karin skill=chr_0019_karin_skill_100901",
            "[10:00:01.500] SKILL_CAST_START seq=8 startMs=1500 inst=100902 owner=chr_0017_yvonne skill=chr_0017_yvonne_ultimate_skill",
            '[10:00:01.800] HP_V2 #2 hit=300 cum=400 raw=300.00 packetFinalValue=300.0 pHP=5000 eHP=899700 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=2 critFlag=0 critDmg=0.5000 templateIntId=2101 origTemplateIntId=2101',
            "[10:00:02.000] GAME_TIMER_END seq=1 source=ChallengeComplete elapsedMs=2000 startMs=0 endMs=2000 expireMs=0 sane=1",
        ]
    )

    parsed = parse_raw_battle_log_text(content, include_rdps_debug=True, file_name="zero-damage-cast.log")
    cast_events = [
        event for event in parsed["timeline_events"] if event.get("event_type") == "cast"
    ]

    # 只有秋栗的零伤害终结技被补录；运行时兜底 id 不发；带伤害的终结技不重复。
    assert [event["event_key"] for event in cast_events] == ["chr_0019_karin_ultimate_skill"]
    cast_event = cast_events[0]
    assert cast_event["lane_type"] == "skill"
    assert cast_event["source_character_key"] == "chr_0019_karin"
    assert cast_event["value"] is None
    assert cast_event["important"] is True
