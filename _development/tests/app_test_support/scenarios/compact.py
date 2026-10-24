from app_test_support.scenarios.buffs import buff
from app_test_support.scenarios.timeline import report, OWNER

def sample():
    snapshot = report()
    snapshot['participants'].append({'character_key': 'chr_0005_chen'})
    for event, value in zip(snapshot['timeline_events'], (90, 0)):
        event.update(target_character_key='enemy', target_actor_id='1', target_character_name='测试敌人',
                     poise_damage={'current_value': value, 'value': -10})
    snapshot['timeline_events'] += [
        {**buff(0, 2000), 'event_name': '增伤', 'event_key': 'buff_unknown_a',
             'source_character_key': 'chr_0005_chen', 'target_character_key': OWNER},
        {**buff(2500, 4000, 'second'), 'event_name': '增伤', 'event_key': 'buff_unknown_a',
             'source_character_key': 'chr_0005_chen', 'target_character_key': OWNER},
        {**buff(100, 3000), 'event_name': '测试实际名称', 'event_key': 'buff_unknown_b',
             'source_character_key': OWNER, 'target_character_key': OWNER}]
    return snapshot
