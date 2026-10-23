from copy import deepcopy
import pytest
from parser_core.live_totals import LiveDamageTotals
from parser_core import battle_log_parser as core


@pytest.mark.parametrize('reverse', [False, True])
def test_damage_crit_and_visual_maxima_match_canonical_after_corrections(reverse):
    rows = [dict(character_key='chr_0004_pelica', character_name='A', target_enemy_key='enemy',
                 hit_value=value, crit_flag=index % 2, skill_key='same', ts_ms=stamp)
            for index, (value, stamp) in enumerate([(10,100), (20,120), (7,500), (5,510)])]
    if reverse:
        rows.reverse()
    cache = LiveDamageTotals()
    variants = [rows[:1], rows[:2], rows, rows[:3], deepcopy(rows), []]
    variants[4][1].update(hit_value=2, crit_flag=0, ts_ms=1000, character_name='corrected')
    variants[4][2].update(character_key='chr_0035_liino', target_enemy_key='other', skill_key='changed')
    buffs = [{'source_character_key':'chr_0032_lizhiyan', 'target_character_key':'chr_0004_pelica'}]
    for hits in variants:
        got = cache.project(hits, buffs)
        expected = core._rebuild_hit_totals(hits, buffs)
        assert got[0] == expected[0]
        assert got[2:] == expected[2:]
    cache.project(rows, buffs)
    frozen = deepcopy(cache.project(rows, buffs)[0])
    assert cache.updated_hits == 0 and cache.reused_hits == len(rows)
    cache.project([], buffs)
    assert frozen['chr_0004_pelica']['total_damage'] == 42
