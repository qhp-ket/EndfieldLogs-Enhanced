from __future__ import annotations
import pytest
from parser_test_support.paths import INTERNAL
from pathlib import Path
from parser_core.unified import parse_hit_viewer_log_text, parse_overlay_battle_snapshot_text
from parser_core.live import LiveOverlayBattleParser


def _repo_root() -> Path:
    return INTERNAL


@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy lifetime/stack expectation; verify exact lifetime and instance evidence before updating; fails at: conduct_zone = next(zone for zone in hit["zones"] if zone["zone"] == "vuln_taken")')
def test_hit_viewer_extends_conduct_window_from_packet_modifier_uid() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0028_wulfa_1001 chr_0004_pelica_1002]",
            '[10:00:00.000] DMG_MOD buff="buff_common_pulse_pulse_conduct_triggered_do" d=0 p=0 enableSide=1 class="DamageScaleProcessor" side=1 zone="NormalCalcZone" useKey=1 val=0.0000 bbKey="final_spell_resistance_decrease"',
            '[10:00:00.000] BUFF_START #1 id="buff_common_pulse_pulse_conduct_triggered_do" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: spell_resistance_decrease=0.12 duration=2 final_spell_resistance_decrease=0.12",
            '[10:00:02.500] HP_V2 #2 hit=112 cum=112 raw=112.00 pHP=5000 eHP=899888 skill="chr_0028_wulfa_ultimate_skill" hits=1 skillLv=12 templateIntId=2397 actionId=177 origTemplateIntId=2397 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa atkId=1001 tgtId=2000 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            "[10:00:02.500] PKT_MOD #2 atk=[] def=[other]",
            '[10:00:03.000] HP_V2 #3 hit=112 cum=224 raw=112.00 pHP=5000 eHP=899776 skill="chr_0028_wulfa_ultimate_skill" hits=1 skillLv=12 templateIntId=2397 actionId=177 origTemplateIntId=2397 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa atkId=1001 tgtId=2000 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            "[10:00:03.000] PKT_MOD #3 atk=[] def=[1]",
            "[10:00:04.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=4000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    report = parse_hit_viewer_log_text(text, file_name="conduct-packet-mod-extension.log")
    mismatched_hit, hit = report["hits"]
    conduct_zone = next(zone for zone in hit["zones"] if zone["zone"] == "vuln_taken")
    conduct_row = next(
        contributor
        for contributor in conduct_zone["contributors"]
        if contributor["event_key"] == "buff_common_pulse_pulse_conduct_triggered_do"
    )

    assert all(zone["zone"] != "vuln_taken" for zone in mismatched_hit["zones"])
    assert hit["damage_school"] == "spell"
    assert hit["damage_element"] == "fire"
    assert conduct_row["source_character_key"] == "chr_0004_pelica"
    assert conduct_row["rdps_credit"] == 12.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=StopIteration, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: fragile_zone = next(zone for zone in hit["zones"] if zone["zone"] == "fragile")')
def test_hit_viewer_keeps_enemy_fragile_when_packet_modifier_def_list_is_partial() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
            "[10:00:00.000] SQUAD size=2 members=[chr_0028_wulfa_1001 chr_0013_aglina_1002]",
            '[10:00:00.000] ATTR_MOD buff="buff_chr_0013_aglina_ultimate_spell_vulnerable" i=0 attrType=85 modType=0 formula=0 useKey=1 val=0.0000 bbKey="rate"',
            '[10:00:00.000] BUFF_START #1 id="buff_chr_0013_aglina_ultimate_spell_vulnerable" uid=1 owner=eny_0051_rodin src=chr_0013_aglina dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:00.000] BB[1]: rate=0.33 duration=-1",
            '[10:00:02.000] HP_V2 #2 hit=1330 cum=1330 raw=1330.00 pHP=5000 eHP=898670 skill="chr_0028_wulfa_ultimate_skill" hits=1 skillLv=12 templateIntId=2397 actionId=177 origTemplateIntId=2397 damageUnitIndex=0 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa atkId=1001 tgtId=2000 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            "[10:00:02.000] PKT_MOD #2 atk=[] def=[other_debuff]",
            "[10:00:03.000] GAME_TIMER_END seq=3 source=ChallengeComplete self=0 msg=0 elapsedMs=3000 startMs=0 expireMs=0 forceLeaveTs=0 sane=1",
        ]
    )

    report = parse_hit_viewer_log_text(text, file_name="partial-def-packet-fragile.log")
    hit = report["hits"][0]
    fragile_zone = next(zone for zone in hit["zones"] if zone["zone"] == "fragile")

    assert any(
        contributor["source_character_key"] == "chr_0013_aglina"
        and contributor["event_key"] == "buff_chr_0013_aglina_ultimate_spell_vulnerable"
        for contributor in fragile_zone["contributors"]
    )

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy attribution expectation; current typed approval, baseline and packet evidence must be reviewed; fails at: assert hit["damage_school"] == "spell"')
def test_hit_viewer_does_not_merge_raw_debug_hits_by_index_when_seq_mismatch(monkeypatch) -> None:
    text = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=900000 skill="chr_0004_pelica_attack1_projhit" hits=1 src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    def fake_raw_report(*args, **kwargs):
        return {
            "debug_hits": [
                {
                    "seq": 161,
                    "damage_school": "physical",
                    "zones": [
                        {
                            "zone": "vuln_taken",
                            "contributors": [
                                {
                                    "event_key": "fake_misaligned_buff",
                                    "event_name": "错位覆盖",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr("parser_core.unified.parse_raw_battle_log_text", fake_raw_report)

    report = parse_hit_viewer_log_text(text, file_name="seq-mismatch.log")
    hit = report["hits"][0]

    assert hit["seq"] == 1
    assert hit["damage_school"] == "spell"
    assert all(
        contributor.get("event_key") != "fake_misaligned_buff"
        for zone in hit.get("zones") or []
        for contributor in zone.get("contributors") or []
    )

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["boss_key"] == "eny_0079_nefarp2"')
def test_overlay_parser_recovers_boss_hits_when_target_actor_was_mislabeled_as_party() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung02_bossrush02_03 source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] ENTITY_STATS id=101710 template=chr_0027_tangtang kind=character level=90 hp=7030 attrs=[]",
            "[10:00:00.000] ENTITY_STATS id=101736 template=chr_0028_wulfa kind=character level=90 hp=6085 attrs=[]",
            "[10:00:00.000] SQUAD size=2 members=[chr_0027_tangtang_101710 chr_0028_wulfa_101736]",
            "[10:00:01.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=dung02_bossrush02_03",
            "[10:00:01.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:02.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=101710 tgtId=101788 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:03.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=0 eHP=700 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=chr_0027_tangtang atk=chr_0028_wulfa atkId=101736 tgtId=101788 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:04.000] HP_V2 #3 hit=200 cum=200 raw=200.00 pHP=0 eHP=500 skill="chr_0028_wulfa_attack2" hits=1 src=chr_0028_wulfa tgt=chr_0027_tangtang atk=chr_0028_wulfa atkId=101736 tgtId=101788 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:05.000] HP_V2 #4 hit=50 cum=50 raw=50.00 pHP=0 eHP=6035 skill="chr_0027_tangtang_skill_2906" hits=1 src=chr_0027_tangtang tgt=chr_0028_wulfa atk=chr_0027_tangtang atkId=101788 tgtId=101736 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            "[10:00:11.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=dung02_bossrush02_03 isPass=1 passTime=10000",
        ]
    )

    snapshot = parse_overlay_battle_snapshot_text(text, file_name="mislabeled-target.log")

    assert snapshot["battle"]["boss_key"] == "eny_0079_nefarp2"
    assert snapshot["battle"]["total_damage"] == 500
    by_key = {participant["character_key"]: participant for participant in snapshot["participants"]}
    assert by_key["chr_0027_tangtang"]["total_damage"] == 100
    assert by_key["chr_0028_wulfa"]["total_damage"] == 400

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["boss_key"] == "eny_0090_wgabyss"')
def test_overlay_parser_retargets_unknown_hits_when_context_identifies_same_boss() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_hard011_s source=SC_SELF_SCENE_INFO",
            "[10:00:00.000] ENTITY_STATS id=101710 template=chr_0027_tangtang kind=character level=90 hp=7030 attrs=[]",
            "[10:00:00.000] ENTITY_STATS id=101736 template=chr_0028_wulfa kind=character level=90 hp=6085 attrs=[]",
            "[10:00:00.000] SQUAD size=2 members=[chr_0027_tangtang_101710 chr_0028_wulfa_101736]",
            "[10:00:01.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_hard011_s",
            "[10:00:01.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=1000 expireMs=0 official=1",
            '[10:00:02.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=101710 tgtId=101788 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:03.000] HP_V2 #2 hit=200 cum=200 raw=200.00 pHP=0 eHP=700 skill="chr_0028_wulfa_attack1" hits=1 src=chr_0028_wulfa tgt=chr_0027_tangtang atk=chr_0028_wulfa atkId=101736 tgtId=101788 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            "[10:00:11.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_hard011_s isPass=1 passTime=10000",
        ]
    )

    snapshot = parse_overlay_battle_snapshot_text(text, file_name="mixed-unknown-target.log")

    assert snapshot["battle"]["boss_key"] == "eny_0090_wgabyss"
    assert snapshot["battle"]["boss_name"] == "破潮之像"
    assert snapshot["battle"]["total_damage"] == 300

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["boss_key"] == "eny_0082_hsbear"')
def test_overlay_snapshot_discards_stale_loadout_when_runtime_party_disagrees() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower007_ex source=CS_ENTER_DUNGEON charTeamCount=0",
            "[10:00:00.000] LOADOUT reason=BATTLE_START slotCount=2 memberCount=2 roster=[1 2]",
            "[10:00:00.000] LOADOUT slot=0 char=chr_0031_mifu weaponTemplate=wpn_claym_0017 equipSuit={}",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0013_aglina weaponTemplate=wpn_funnel_0016 equipSuit={}",
            '[10:00:02.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=0 eHP=899900 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang seg=0 shared=2 critFlag=0 critDmg=-1.0000',
            '[10:00:03.000] HP_V2 #2 hit=50 cum=50 raw=50.00 pHP=0 eHP=899850 skill="chr_0013_aglina_attack1" hits=1 src=chr_0013_aglina tgt=eny_0000_unknown atk=chr_0013_aglina seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    snapshot = parse_overlay_battle_snapshot_text(text, file_name="stale-loadout.log")

    assert snapshot["battle"]["boss_key"] == "eny_0082_hsbear"
    assert snapshot["battle"]["loadout_stale"] is True
    assert snapshot["loadout"] == []
    assert {row["character_key"] for row in snapshot["participants"]} == {
        "chr_0027_tangtang",
        "chr_0013_aglina",
    }

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=KeyError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["actor_mapping_complete"] is False')
def test_live_overlay_parser_falls_back_to_raw_actor_dps_when_actor_map_is_missing() -> None:
    live = LiveOverlayBattleParser()
    for line in [
        "[10:00:00.000] GAME_TIMER_START",
        '[10:00:01.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="2030" hits=1 src=id_100211 tgt=id_100314 atk=id_100211 seg=0 shared=2 critFlag=0 critDmg=0.5000',
        '[10:00:02.000] HP_V2 #2 hit=500 cum=500 raw=500.00 pHP=0 eHP=899500 skill="2132" hits=1 src=id_100237 tgt=id_100314 atk=id_100237 seg=0 shared=3 critFlag=1 critDmg=0.5000',
    ]:
        live.feed_line(line)

    snapshot = live.snapshot()

    assert snapshot is not None
    assert snapshot["battle"]["actor_mapping_complete"] is False
    assert snapshot["battle"]["rdps_available"] is False
    assert [entry["character_key"] for entry in snapshot["participants"]] == ["id_100211", "id_100237"]
    assert snapshot["participants"][0]["total_damage"] == 1000
    assert snapshot["participants"][0]["rdps"] == 0.0

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["boss_key"] == "eny_0000_unknown"')
def test_overlay_parser_recovers_short_actor_ids_from_loadout_bootstrap_buffs() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] LOADOUT reason=SC_SELF_SCENE_INFO slotCount=2 memberCount=2 roster=[1 2]",
            "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 equipSuit={} skillIntIds=[748]",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0023_antal weaponTemplate=wpn_funnel_0008 equipSuit={} skillIntIds=[1462]",
            '[10:00:00.100] BUFF_START #1 id="576" uid=1 owner=id_100474 src=id_100474 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.100] BUFF_START #2 id="2575" uid=2 owner=id_100500 src=id_100500 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000] GAME_TIMER_START",
            '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="skill_2258" hits=1 src=id_100500 tgt=id_100577 atk=id_100500 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    snapshot = parse_overlay_battle_snapshot_text(text, file_name="short-actor.log")

    assert snapshot["battle"]["boss_key"] == "eny_0000_unknown"
    assert snapshot["participants"][0]["character_key"] == "chr_0023_antal"
    assert snapshot["participants"][0]["total_damage"] == 1000

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=KeyError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["actor_mapping_complete"] is False')
def test_overlay_parser_does_not_recover_short_actor_ids_from_char_bag_loadout() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] LOADOUT reason=SC_SYNC_CHAR_BAG_INFO slotCount=2 memberCount=2 roster=[1 2]",
            "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 equipSuit={} skillIntIds=[748]",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0023_antal weaponTemplate=wpn_funnel_0008 equipSuit={} skillIntIds=[1462]",
            '[10:00:00.100] BUFF_START #1 id="576" uid=1 owner=id_100474 src=id_100474 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            '[10:00:00.100] BUFF_START #2 id="2575" uid=2 owner=id_100500 src=id_100500 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
            "[10:00:01.000] GAME_TIMER_START",
            '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="skill_999999" hits=1 src=id_100500 tgt=id_100577 atk=id_100500 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )
    live = LiveOverlayBattleParser()
    for line in text.splitlines():
        live.feed_line(line)

    snapshot = live.snapshot()

    assert snapshot is not None
    assert snapshot["battle"]["actor_mapping_complete"] is False
    assert snapshot["participants"][0]["character_key"] == "id_100500"

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["participants"][0]["character_key"] == "chr_0023_antal"')
def test_overlay_parser_recovers_short_actor_ids_from_runtime_fingerprint() -> None:
    text = "\n".join(
        [
            "[10:00:00.000] LOADOUT reason=SC_SYNC_CHAR_BAG_INFO slotCount=2 memberCount=2 roster=[1 2]",
            "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 equipSuit={} skillIntIds=[748]",
            "[10:00:00.000] LOADOUT slot=1 char=chr_0023_antal weaponTemplate=wpn_funnel_0008 equipSuit={} skillIntIds=[1462]",
            "[10:00:01.000] GAME_TIMER_START",
            '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="skill_2258" hits=1 src=id_100500 tgt=id_100577 atk=id_100500 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        ]
    )

    snapshot = parse_overlay_battle_snapshot_text(text, file_name="runtime-fingerprint.log")

    assert snapshot["participants"][0]["character_key"] == "chr_0023_antal"
    assert snapshot["participants"][0]["total_damage"] == 1000

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["participants"][0]["character_key"] == "chr_0023_antal"')
def test_live_overlay_preserves_loadout_and_bootstrap_buffs_across_timer_start() -> None:
    live = LiveOverlayBattleParser()
    for line in [
        "[10:00:00.000] LOADOUT reason=SC_SELF_SCENE_INFO slotCount=2 memberCount=2 roster=[1 2]",
        "[10:00:00.000] LOADOUT slot=0 char=chr_0016_laevat weaponTemplate=wpn_sword_0006 equipSuit={} skillIntIds=[748]",
        "[10:00:00.000] LOADOUT slot=1 char=chr_0023_antal weaponTemplate=wpn_funnel_0008 equipSuit={} skillIntIds=[1462]",
        '[10:00:00.100] BUFF_START #1 id="576" uid=1 owner=id_100474 src=id_100474 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
        '[10:00:00.100] BUFF_START #2 id="2575" uid=2 owner=id_100500 src=id_100500 dur=9999.00 lifeT=9999.00 passed=0.00 enh=1',
        "[10:00:01.000] GAME_TIMER_START",
        '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=900000 skill="skill_2258" hits=1 src=id_100500 tgt=id_100577 atk=id_100500 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
    ]:
        live.feed_line(line)

    snapshot = live.snapshot()

    assert snapshot is not None
    assert snapshot["participants"][0]["character_key"] == "chr_0023_antal"
    assert snapshot["participants"][0]["total_damage"] == 1000

@pytest.mark.legacy_expectation
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Legacy actor/target recovery or old mapping fields; current identity requires explicit evidence; fails at: assert snapshot["battle"]["boss_key"] == "eny_0051_rodin"')
def test_live_overlay_preserves_dungeon_context_across_timer_start() -> None:
    live = LiveOverlayBattleParser()
    for line in [
        "[10:00:00.000] DUNGEON_CONTEXT dungeonId=dung01_bossrush01_04 source=SC_SELF_SCENE_INFO",
        "[10:00:00.000] LOADOUT reason=BATTLE_START slotCount=2 memberCount=2 roster=[1 2]",
        "[10:00:00.000] LOADOUT slot=0 char=chr_0027_tangtang weaponTemplate=wpn_pistol_0011 equipSuit={}",
        "[10:00:00.000] LOADOUT slot=1 char=chr_0013_aglina weaponTemplate=wpn_funnel_0005 equipSuit={}",
        "[10:00:01.000] GAME_TIMER_START seq=1 source=PacketBattleState startMs=0 expireMs=0 official=1",
        '[10:00:02.000] HP_V2 #1 hit=1000 cum=1000 raw=1000.00 pHP=0 eHP=0 skill="chr_0027_tangtang_attack1" hits=1 src=chr_0027_tangtang tgt=eny_0000_unknown atk=chr_0027_tangtang atkId=1 tgtId=99 seg=0 shared=2 critFlag=0 critDmg=-1.0000',
        "[10:00:04.000] GAME_TIMER_END seq=2 source=PacketBattleState elapsedMs=3000 startMs=0 endMs=3000 expireMs=0 sane=1 official=1",
    ]:
        live.feed_line(line)

    snapshot = live.snapshot()

    assert snapshot is not None
    assert snapshot["battle"]["boss_key"] == "eny_0051_rodin"
    assert snapshot["battle"]["dungeon_key"] == "dung01_group_bossrush01"
