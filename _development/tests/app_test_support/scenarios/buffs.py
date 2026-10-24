
def buff(start=0, end=10000, uid='a', policy='Refresh', **changes):
    return dict(lane_type='buff', event_type='buff', event_key='buff_test', event_name='测试增益',
        source_character_key='source', source_actor_id='11', target_character_key='target', target_actor_id='22',
        buff_uid=uid, stacking_type=policy, ts_ms_from_start=start, duration_ms=end-start,
        actual_end_ms_from_start=end, **changes)
