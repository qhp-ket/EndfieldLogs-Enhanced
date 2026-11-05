"""New character data must reach parsing, native views and offline restores."""
import json

from app_test_support.paths import ROOT
from parser_core.catalog import names, resources, skill_damage
from endfield_pcap.data.names import load_name_index
from endfield_pcap.data.skill_names import character_name, skill_label

CHAR = 'chr_0037_minghe'


def test_minghe_names_and_skill_categories_reach_parser_and_native_timeline():
    assert names._resolve_character_name(CHAR) == character_name(CHAR) == '明河'
    assert load_name_index(ROOT/'_internal/jsondata/CharacterNameIndex.json')[CHAR] == '明河'
    for suffix, name, category, group in (
        ('attack1', '曜尘', '普攻', 0),
        ('normalskill_1', '镇影', '战技', 1),
        ('normalskill_2', '奔霆', '战技', 1),
        ('combo_skill', '星移', '连携', 3),
        ('ultimate_skill', '裂天', '大招', 2),
    ):
        key = CHAR+'_'+suffix
        assert names._resolve_skill_name(key) == name
        label = skill_label(key)
        assert label.name.startswith(name) and label.category == category
        assert skill_damage._load_skill_profiles()[key]['group_type'] == group
    assert names._resolve_skill_name('skill_3680') == '镇影'
    assert names._resolve_skill_name('skill_3681') == '奔霆'
    assert skill_damage._load_skill_profiles()[CHAR+'_normalskill_1']['elements'] == ['physical']
    assert skill_damage._load_skill_profiles()[CHAR+'_normalskill_2']['elements'] == ['pulse']


def test_minghe_attributes_potentials_and_presentation_references():
    stats = resources._load_character_base_stat_catalog()[CHAR]
    assert stats[1]['atk'] == 30 and stats[90]['main_attr_type'] == 42
    potentials = resources._load_character_potential_rows(CHAR)
    assert len(potentials) == 5 and potentials[1]['values']['Will'] == 20
    data = ROOT/'_internal/data'
    energy = json.loads((data/'local_semantics/team_energy_rules.json').read_bytes())
    frames = json.loads((data/'local_semantics/skill_frame_rules.json').read_bytes())
    for suffix in ('normalskill_1', 'normalskill_2'):
        key = CHAR+'_'+suffix
        assert energy['skills'][key]['cost'] == 100
        assert frames['skills'][key]['duration_frames'] > 0
    manifest = json.loads((data/'resource-manifest.json').read_bytes())
    supplement = manifest['supplements'][0]
    assert supplement['character_ids'] == [CHAR]
    assert supplement['table_version'] == '1.6.4@11529267-11'
    assert sum('/SkillData/' in row['path'] for row in supplement['files']) == 19
