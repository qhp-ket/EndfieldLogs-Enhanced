"""Unbound display records cannot invent element, family or cast evidence."""
from parser_core.battle_log_parser import parse_raw_battle_log_text
from parser_core.hit_debug import parse_hit_debug_log_text


def test_known_skill_family_does_not_absorb_unbound_buff_damage():
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=1670 cum=1670 raw=1669.94 pHP=6085 eHP=2259523 skill="chr_0028_wulfa_combo_2_skill" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.376] HP_V2 #2 hit=2505 cum=4175 raw=2504.91 pHP=6085 eHP=2257019 skill="chr_0028_wulfa_combo_2_skill" hits=2 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:00.676] HP_V2 #3 hit=756 cum=756 raw=755.56 pHP=6085 eHP=2251516 skill="buff_chr_0028_wulfa_combo_2_damage" hits=1 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:00.801] HP_V2 #4 hit=796 cum=1552 raw=796.38 pHP=6085 eHP=2250719 skill="buff_chr_0028_wulfa_combo_2_damage" hits=2 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:00.929] HP_V2 #5 hit=838 cum=2390 raw=838.14 pHP=6085 eHP=2237146 skill="buff_chr_0028_wulfa_combo_2_damage" hits=3 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:01.430] HP_V2 #6 hit=19102 cum=31517 raw=19101.81 pHP=6085 eHP=2208019 skill="chr_0028_wulfa_combo_3_skill" hits=5 src=chr_0028_wulfa tgt=eny_0051_rodin atk=chr_0028_wulfa seg=0 shared=2 critFlag=0 critDmg=1.0000',
        ]
    )
    parsed = parse_raw_battle_log_text(
        content,
        file_name="wulfa-combo-family.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-02-000",
    )
    combo_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    # The current profile already binds combo_3 to combo_2. That known family
    # does not authorize folding the separate damage buff into the same cast.
    assert {event['event_key'] for event in combo_events} == {
        'chr_0028_wulfa_combo_2_skill', 'buff_chr_0028_wulfa_combo_2_damage'}
    assert len({event['event_group_key'] for event in combo_events}) > 1
    assert sum(event['value'] for event in combo_events) == 25667
    assert parsed['battle']['total_damage'] == 25667


def test_unbound_ultimate_phases_keep_keys_and_conserve_damage():
    content = "\n".join(
        [
            '[10:00:00.000] HP_V2 #1 hit=100 cum=100 raw=100.00 pHP=5000 eHP=900000 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:00.140] HP_V2 #2 hit=200 cum=300 raw=200.00 pHP=5000 eHP=899800 skill="chr_0017_yvonne_ult_attack2_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:03.900] HP_V2 #3 hit=300 cum=600 raw=300.00 pHP=5000 eHP=899500 skill="chr_0017_yvonne_ult_attack1_projhit" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=3 critFlag=1 critDmg=0.5000',
            '[10:00:06.000] HP_V2 #4 hit=400 cum=1000 raw=400.00 pHP=5000 eHP=899100 skill="chr_0017_yvonne_ult_attack_end" hits=1 src=chr_0017_yvonne tgt=eny_0051_rodin atk=chr_0017_yvonne seg=0 shared=3 critFlag=1 critDmg=0.5000',
        ]
    )
    parsed = parse_raw_battle_log_text(
        content,
        file_name="yvonne-ultimate-family.log",
        first_hit_hint="10-00-00-000",
        last_hit_hint="10-00-06-000",
    )
    damage_events = [event for event in parsed["timeline_events"] if event["lane_type"] == "skill"]
    assert {event['event_key'] for event in damage_events} == {
        'chr_0017_yvonne_ult_attack1_projhit', 'chr_0017_yvonne_ult_attack2_projhit',
        'chr_0017_yvonne_ult_attack_end'}
    assert len({event['event_group_key'] for event in damage_events}) > 1
    assert sum(event['value'] for event in damage_events) == 1000
    assert sum(row['total_damage'] for row in parsed['role_skill_stats']) == 1000
    assert parsed['battle']['total_damage'] == 1000


def test_viewer_unknown_element_cannot_borrow_dpd_or_award_external_credit():
    content = "\n".join(
        [
            '[10:00:00.000] BUFF_START #1 id="buff_fire_taken_probe" uid=1 owner=eny_0051_rodin src=chr_0004_pelica dur=2.00 lifeT=2.00 passed=0.00 enh=1',
            "[10:00:00.000]   BB[1]: damage_taken_up_fire=0.2 duration=2",
            '[10:00:00.500] HP_V2 #2 hit=120 cum=120 raw=120.00 pHP=5000 eHP=900000 skill="unknown_proc_damage" hits=1 src=chr_9999_dummy tgt=eny_0051_rodin atk=chr_9999_dummy seg=0 shared=2 critFlag=0 critDmg=0.5000',
            '[10:00:00.500] DPD_RAW #2 probe=2 calc=120.0000 atkScale=1.0000 blocked=0 damageType=0x2 decorateMask=0x80 collider="BattleShape" atkZones=[1.0000,1.0000,1.0000,1.0000,1.0000,1.0000] defZones=[1.0000,1.2000,1.0000,1.0000,1.0000,1.0000]',
        ]
    )
    parsed = parse_hit_debug_log_text(content, file_name="dpd-damage-type-fallback.log")
    hit = parsed['hits'][0]
    assert hit['damage_element'] is None
    assert hit['zones'] == []
    assert hit['external_sources'] == []
    assert hit['hit_value'] == hit['attacker_share'] == 120
