"""Candidate indexes must preserve the unindexed predicates and ordering."""
from copy import deepcopy
from pathlib import Path

from parser_core.condition_index import ConditionRecordIndex, EffectWindowIndex
from parser_core import battle_log_parser as parser
from parser_core.unified import parse_overlay_battle_snapshot_text


def test_condition_candidates_preserve_predicate_for_both_sides_and_time_reversal():
    records = [dict(event_key=f'buff_{i}', ts_ms=start, end_ts_ms=end,
                    raw_duration_ms=duration, target_character_key=target,
                    target_actor_id='10', uid=str(i), line_no=i)
               for i, (start, end, duration, target) in enumerate([
                   (20, 40, None, 'a'), (0, 10, None, 'a'), (0, None, 30, 'a'),
                   (10, None, None, 'b'), (10, 9, None, 'a'), (None, 80, None, 'a'),
                   (30, None, 0, 'a'), (30, None, -1, 'a'), (0, None, None, 'a')])]
    index = ConditionRecordIndex(records, parser._coerce_optional_int)
    for stamp in (0, 9, 10, 20, 29, 30, 40, 41, 100, 5, 10, 100):
        hit = dict(ts_ms=stamp, line_no=50, target_enemy_key='a', target_actor_id='10',
                   character_key='b', source_actor_id='10',
                   packet_modifier_uids={'defender': [str(i) for i in range(9)], 'attacker': ['3']})
        for side, target in [('defender', 'a'), ('attacker', 'b')]:
            candidates = index.candidates(target, stamp)
            assert [records.index(row) for row in candidates] == sorted(records.index(row) for row in candidates)
            assert parser._active_target_buff_ids_for_hit(hit, candidates, side=side) == parser._active_target_buff_ids_for_hit(hit, records, side=side)


def test_window_index_inclusive_unknown_bounds_and_original_order():
    windows = [dict(start_ts_ms=a, end_ts_ms=b) for a, b in
               [(20, 40), (0, 10), (None, None), (10, 9), ('20', 80), (30, None)]]
    index = EffectWindowIndex(windows)
    for stamp in (0, 10, 20, 30, 40, 41, 100, 5, 40):
        expected = [i for i, w in enumerate(windows)
                    if not (type(w['start_ts_ms']) is int and stamp < w['start_ts_ms']
                            or type(w['end_ts_ms']) is int and stamp > w['end_ts_ms'])]
        assert index.candidates(stamp) == expected


def test_full_snapshot_identical_with_unindexed_reference(monkeypatch):
    from parser_core import condition_index
    text = (Path(__file__).parent / 'fixtures/rdps_snapshot_contract.log').read_text(encoding='utf8')
    actual = deepcopy(parse_overlay_battle_snapshot_text(text))
    monkeypatch.setattr(condition_index.EffectWindowIndex, 'candidates',
                        lambda self, stamp: sorted(row[1] for row in self.rows))
    monkeypatch.setattr(condition_index.ConditionRecordIndex, 'candidates',
                        lambda self, target, stamp: [row[3] for row in sorted(self.groups.get(target, []), key=lambda row: row[1])])
    original = parser._allocate_rdps_for_hit
    def full_scan(hit, windows, **kwargs):
        kwargs.update(effect_window_indices=None, condition_records_by_target=None,
                      condition_records_by_uid=None, condition_records_by_actor=None)
        return original(hit, windows, **kwargs)
    monkeypatch.setattr(parser, '_allocate_rdps_for_hit', full_scan)
    assert parse_overlay_battle_snapshot_text(text) == actual
