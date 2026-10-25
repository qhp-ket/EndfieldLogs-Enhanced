"""Input intent rules are evidence only, not inferred successful casts."""
from copy import deepcopy
import pytest
from endfield_pcap.inputlog.interpret import Interpreter,project,normalize_settings


def event(ms,code,phase='down',device='keyboard',**extra):
    return dict(type='input',kind='key',device=device,code=code,phase=phase,
                wall_ns=1_800_000_000_000_000_000+int(ms*1e6),mono_ns=int(ms*1e6),**extra)


def interpret(rows,settings=None):
    parser=Interpreter(settings)
    for row in rows: parser.feed(row)
    return parser.close()


@pytest.mark.parametrize('duration,expected',[(0,'skill'),(279.999,'skill'),(280,'ultimate'),(600,'ultimate')])
def test_threshold_only_changes_interpretation_not_original_position(duration,expected):
    rows=[event(10,'K:49'),event(10+duration,'K:49','up')];original=deepcopy(rows)
    result=interpret(rows)
    assert len(result)==1 and result[0]['action']==expected
    assert result[0]['start_wall_ns']==rows[0]['wall_ns'] and result[0]['duration_ms']==pytest.approx(duration)
    assert rows==original


@pytest.mark.parametrize('modifier_first',[True,False])
def test_actual_overlapping_combination_upgrades_subset_without_duplicates(modifier_first):
    first,last=('K:ALT','K:49') if modifier_first else ('K:49','K:ALT')
    rows=[event(0,first),event(80,last),event(120,'K:49','repeat'),event(200,'K:49','up'),event(210,'K:ALT','up')]
    result=interpret(rows)
    assert len(result)==1 and result[0]['action']=='ultimate'
    assert result[0]['start_wall_ns']==rows[1]['wall_ns']
    assert result[0]['rule']=='组合成立 / 按下'


def test_nonoverlapping_modifier_and_two_devices_do_not_form_combination():
    rows=[event(0,'K:ALT'),event(10,'K:ALT','up'),event(15,'K:49'),event(20,'K:49','up'),
          event(30,'K:ALT',device='other'),event(35,'K:49'),event(40,'K:49','up')]
    result=interpret(rows)
    assert [r['action'] for r in result]==['skill','skill']


def test_repeats_and_held_baselines_never_fabricate_new_down():
    rows=[dict(type='baseline',wall_ns=1,states={'keyboard':{'K:49':1}}),event(1,'K:49','repeat'),
          event(2,'K:49','up'),event(10,'K:49'),event(11,'K:49'),event(12,'K:49','repeat'),event(40,'K:49','up')]
    result=interpret(rows)
    assert len(result)==1 and result[0]['duration_ms']==30


@pytest.mark.parametrize('reason',['focus_lost','stopped','device_disconnected','gap'])
def test_interruption_closes_spans_without_synthetic_up(reason):
    marker=dict(type='gap' if reason=='gap' else 'interrupt',reason=reason,
                wall_ns=event(100,'K:49')['wall_ns'],mono_ns=100_000_000)
    result=interpret([event(0,'K:49'),marker,event(200,'K:49','up')])
    assert len(result)==1 and result[0]['interrupted'] and result[0]['duration_ms']==100


def test_gamepad_specific_ultimate_and_raw_mapped_duplicate_suppression():
    settings={'bindings':[dict(action='combo',slot=None,keys=['P:RB'],gesture='press'),
                          dict(action='ultimate',slot=1,keys=['P:RB','P:NORTH'],gesture='press')]}
    rows=[event(0,'P:RB',device='pad'),event(1,'J:BUTTON10',device='pad',mapped_device=True),
          event(5,'P:NORTH',device='pad'),event(30,'P:NORTH','up',device='pad'),event(40,'P:RB','up',device='pad')]
    result=interpret(rows,settings)
    assert len(result)==1 and result[0]['action']=='ultimate' and result[0]['slot']==1


def test_combo_global_and_hold_crossing_battle_boundary_keeps_source_position():
    actions=interpret([event(0,'K:49'),event(500,'K:49','up'),event(600,'K:69'),event(650,'K:69','up')])
    start=event(200,'K:49')['wall_ns']/1e6
    result=project(actions,start,1000,slots={0:'chr_one'})
    assert result[0]['start_ms']==-200 and result[0]['end_ms']==300
    assert result[0]['character_key']=='chr_one'
    assert result[1]['action']=='combo' and result[1]['character_key'] is None


def test_invalid_configuration_is_bounded_and_has_safe_defaults():
    assert normalize_settings({'hold_ms':'bad'})['hold_ms']==280
    assert normalize_settings({'bindings':'bad'})['bindings']
    assert normalize_settings({'bindings':[{'action':'invent','keys':['K:49']}]})['bindings']==[]


def test_unobserved_held_key_at_focus_baseline_is_suppressed_until_release():
    rows=[dict(type='baseline',wall_ns=1,states={},keyboard_vks=['K:49','K:ALT']),
          event(0,'K:49'),event(10,'K:49','up'),event(20,'K:ALT','up'),
          event(30,'K:49'),event(50,'K:49','up')]
    result=interpret(rows)
    assert len(result)==1 and result[0]['duration_ms']==20


def test_wall_clock_jump_is_preserved_and_duration_uses_monotonic_clock():
    down=event(0,'K:49');up=event(300,'K:49','up')
    up['wall_ns']+=2_000_000_000
    result=interpret([down,up])[0]
    assert result['end_wall_ns']==up['wall_ns']
    assert result['duration_ms']==300


def test_device_reconnection_does_not_interrupt_another_devices_held_key():
    baseline=dict(type='baseline',device='pad',states={'pad':{'P:LB':1}},
                  wall_ns=event(100,'K:49')['wall_ns'],mono_ns=100_000_000)
    result=interpret([event(0,'K:49'),baseline,event(500,'K:49','up')])
    assert len(result)==1 and result[0]['duration_ms']==500 and not result[0]['interrupted']
