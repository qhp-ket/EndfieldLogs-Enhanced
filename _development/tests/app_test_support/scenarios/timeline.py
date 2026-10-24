
OWNER = 'chr_0004_pelica'

SKILL = OWNER + '_normal_skill'

def report(*, end=900, with_cast=True, hits=(400, 650), skill=SKILL):
    return {'battle': {'duration_ms': 7000, 'total_damage': 200},
            'participants': [{'character_key': OWNER}],
            'casts': [dict(character_key=OWNER, skill_key=skill,
                           ts_ms_from_start=100, end_ms_from_start=end)] if with_cast else [],
            'timeline_events': [dict(lane_type='skill', event_type='damage',
                source_character_key=OWNER, event_key=skill, event_group_key='cast-1',
                actual_start_ms_from_start=100 if with_cast else None,
                actual_end_ms_from_start=end if with_cast else None,
                ts_ms_from_start=stamp, value=100) for stamp in hits]}
