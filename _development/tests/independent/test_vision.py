from copy import deepcopy
import numpy as np
import pytest
from endfield_pcap.vision.pixels import Observation,observe
from endfield_pcap.vision.tracking import SlotTracker
from endfield_pcap.vision.engine import VisionEngine
from endfield_pcap.vision.layout import normalize_config,presets,crop,game_area


def test_recognized_state_replaces_ready_immediately_and_duplicate_frame_is_ignored():
    tracker=SlotTracker()
    ready=Observation(True,1,ready=True)
    assert tracker.feed(ready,0,1)['status']=='ready'
    assert tracker.feed(Observation(True,.3),.05,1)['status']=='ready'  # Same frame isn't a new observation.
    assert tracker.feed(Observation(True,.3),.1,2)['status']=='cooldown'
    assert tracker.feed(ready,.15,3)['status']=='ready'
    dim=Observation(False,reason='ambiguous_energy')
    for i in range(4,8): assert tracker.feed(dim,i/20,i)['status']=='ready'
    empty=Observation(True,0,consumed=True)
    assert tracker.feed(empty,.5,10)['status']=='cooldown'
    assert tracker.feed(empty,.55,11)['status']=='cooldown'


def test_velocity_is_optional_stops_on_pause_jump_and_never_creates_ready():
    tracker=SlotTracker()
    for i in range(25):
        result=tracker.feed(Observation(True,.05+i*.01),i*.05,i)
    assert result['status']=='cooldown'
    assert result['estimated_remaining_ms']==pytest.approx((1-.29)/.2*1000,rel=.02)
    result=tracker.feed(Observation(True,.29),1.5,26)
    assert result['estimated_remaining_ms'] is None
    result=tracker.feed(Observation(True,.9),1.55,27)
    assert result['estimated_remaining_ms'] is None and result['status']=='cooldown'
    tracker.invalid(3)
    assert tracker.payload(3)['stale'] and tracker.payload(3)['estimated_remaining_ms'] is None


def test_stale_recovery_holds_ready_and_dead_is_not_low_hp():
    tracker=SlotTracker()
    for i in range(2): tracker.feed(Observation(True,1,ready=True),i*.05,i)
    tracker.invalid(2)
    assert tracker.payload(2)['status']=='ready'
    assert tracker.payload(2)['held']
    assert tracker.feed(Observation(True,1,ready=True),2.1,3)['status']=='ready'
    assert tracker.feed(Observation(True,1,ready=True),2.15,4)['status']=='ready'
    e=np.full((4,100,3),50,dtype=np.uint8);h=np.zeros((7,100,3),dtype=np.uint8)
    h[:,:2]=[20,180,240]
    p=np.full((26,26,3),70,dtype=np.uint8)
    assert not observe(e,h,p).dead


def test_missing_frames_continue_only_an_existing_estimate_then_hold_ready():
    tracker=SlotTracker()
    for i in range(25):tracker.feed(Observation(True,.05+i*.01),i*.05,i)
    remaining=tracker.remaining
    tracker.invalid(1.3)
    held=tracker.payload(2)
    assert held['status']=='cooldown' and held['held']
    assert held['progress']>.29
    assert held['estimated_remaining_ms']==pytest.approx(remaining-800)
    assert tracker.payload(5)['status']=='ready'
    tracker.invalid(20)
    assert tracker.payload(20)['status']=='ready'
    # A successful observation immediately replaces extrapolated readiness.
    assert tracker.feed(Observation(True,.1,consumed=True),21,30)['status']=='cooldown'
    assert tracker.feed(Observation(True,.1,consumed=True),21.1,31)['status']=='cooldown'
    assert SlotTracker().payload(21)['status']=='unknown'


def test_missing_frames_without_a_speed_do_not_invent_a_countdown():
    tracker=SlotTracker()
    for i in range(2):tracker.feed(Observation(True,.25),i*.05,i)
    tracker.invalid(1)
    result=tracker.payload(100)
    assert result['status']=='cooldown' and result['progress']==.25
    assert result['estimated_remaining_ms'] is None


@pytest.mark.parametrize('fraction',[0,.2,.7,1])
def test_small_roi_progress_and_bright_background_rejection(fraction):
    e=np.full((4,100,3),50,dtype=np.uint8);e[:,:round(fraction*100)]=240
    h=np.tile(np.array([20,180,240],dtype=np.uint8),(7,100,1));p=np.full((26,26,3),60,dtype=np.uint8)
    result=observe(e,h,p)
    assert result.readable and result.progress==pytest.approx(fraction,abs=.02)
    assert result.ready==(fraction==1)
    # No HP/rail geometry -> white scene cannot establish a HUD.
    assert not observe(np.full_like(e,240),np.full_like(h,240),p).readable


def test_layouts_are_normalized_and_window_position_is_irrelevant():
    pixels=np.full((1152,2048,4),20,dtype=np.uint8)
    for row in presets()['keyboard']:
        for key in ('energy','hp','portrait'):
            x,y,w,h=row[key];x,y,w,h=round(x*2048),round(y*1152),round(w*2048),round(h*1152)
            pixels[y:y+h,x:x+w,:3]=[20,180,240] if key=='hp' else (235 if key=='energy' else 50)
    original=pixels.copy()
    engine=VisionEngine()
    for i in range(4): result=engine.analyze(pixels,(0,0,2048,1152),i*.05,i)
    assert result['layout']=='keyboard' and result['frame_valid']
    assert all(s['status']=='ready' for s in result['slots'])
    assert np.array_equal(pixels,original)
    assert not VisionEngine().analyze(np.zeros_like(pixels),(0,0,2048,1152),0,1)['frame_valid']
    assert normalize_config({'layout':'custom','regions':[{}]*4})['regions']==[]
    changed=engine.analyze(pixels[:1000],(0,0,2048,1000),1,9)
    assert not changed['frame_valid']
    assert all(s['status']=='ready' and s['held'] for s in changed['slots'])
    assert normalize_config({'target_hwnd':'invalid'})['target_hwnd']==0


def test_symmetric_black_bands_and_manual_regions():
    pixels=np.zeros((1200,1920,4),dtype=np.uint8);pixels[60:1140,:,:3]=80
    x,y,w,h=game_area(pixels,(0,0,1920,1200))
    assert x==0 and abs(y-60)<8 and abs(h-1080)<16
    assert crop(pixels,(0,60,1920,1080),[0,.9,.1,.01]).size>0


def test_grey_scenery_never_establishes_a_cooldown_layout():
    engine=VisionEngine()
    pixels=np.full((1152,2048,4),75,dtype=np.uint8)
    for frame in range(5):
        result=engine.analyze(pixels,(0,0,2048,1152),frame*.05,frame)
        assert not result['frame_valid']
        assert all(slot['status']=='unknown' for slot in result['slots'])


def test_bar_outline_does_not_hide_partial_or_full_fill():
    h=np.tile(np.array([20,180,240],dtype=np.uint8),(7,100,1))
    p=np.full((26,26,3),60,dtype=np.uint8)
    for end,fraction in ((50,.5),(98,1.)):
        e=np.full((4,100,3),50,dtype=np.uint8)
        e[:,2:end]=240
        observed=observe(e,h,p)
        assert observed.readable
        assert observed.progress==pytest.approx(fraction)
        assert observed.ready==(fraction==1)
    # A bright patch in the middle isn't a prefix filled from the left.
    e=np.full((4,100,3),50,dtype=np.uint8);e[:,30:80]=240
    assert not observe(e,h,p).readable and observe(e,h,p).progress is None


def test_16_10_keyboard_hud_uses_uniform_bottom_left_anchor():
    # Independently measured positions for a width-scaled 2048x1152 HUD
    # displayed in 2560x1600; 160 extra vertical pixels belong above the HUD.
    pixels=np.full((1600,2560,4),20,dtype=np.uint8)
    for x in (56,211,368,524):
        pixels[1476:1481,x:x+111,:3]=50
        pixels[1476:1481,x+2:x+109,:3]=240
        pixels[1481:1490,x:x+111,:3]=[20,180,240]
        pixels[1406:1439,x+40:x+73,:3]=60
    engine=VisionEngine()
    for frame in range(5):
        result=engine.analyze(pixels,(0,0,2560,1600),frame*.05,frame)
    assert result['frame_valid'] and result['layout']=='keyboard'
    assert all(row['status']=='ready' for row in result['slots']),[(s['status'],s['progress']) for s in result['slots']]
    assert result['regions'][0]['energy'][1]==pytest.approx(1476.25/1600)


def test_empty_slot_candidates_need_other_slots_to_establish_hud():
    e=np.full((4,100,3),50,dtype=np.uint8)
    h=np.zeros((7,100,3),dtype=np.uint8)
    p=np.zeros((26,26,3),dtype=np.uint8)
    observation=observe(e,h,p)
    assert observation.empty and not observation.readable
    # A dark scene cannot establish four empty game slots.
    engine=VisionEngine()
    pixels=np.full((1152,2048,4),50,dtype=np.uint8)
    for row in presets()['keyboard']:
        for key in ('hp','portrait'):
            x,y,w,h=row[key]
            pixels[round(y*1152):round((y+h)*1152),round(x*2048):round((x+w)*2048),:3]=0
    for frame in range(4):
        result=engine.analyze(pixels,(0,0,2048,1152),frame*.05,frame)
    assert not result['frame_valid']


def test_partial_bright_prefix_corrects_ready_when_empty_frame_was_missed():
    hp=np.tile(np.array([20,180,240],dtype=np.uint8),(7,100,1))
    portrait=np.full((26,26,3),60,dtype=np.uint8)
    tracker=SlotTracker()
    for i in range(2):tracker.feed(Observation(True,1.,ready=True),i*.05,i)
    bar=np.full((4,100,3),50,dtype=np.uint8);bar[:,:32]=240
    observed=observe(bar,hp,portrait)
    assert observed.partial and not observed.consumed
    assert tracker.feed(observed,.2,3)['status']=='cooldown'
    assert tracker.feed(observed,.25,4)['status']=='cooldown'
    dim=observe(np.full_like(bar,100),hp,portrait)
    assert not dim.readable and dim.progress is None
    assert not dim.partial and not dim.consumed


@pytest.mark.parametrize('fraction',[.1,.5,.94])
def test_valid_cooldown_replaces_held_ready_without_waiting_for_an_empty_bar(fraction):
    hp=np.tile(np.array([20,180,240],dtype=np.uint8),(7,100,1))
    portrait=np.full((26,26,3),60,dtype=np.uint8)
    tracker=SlotTracker()
    tracker.feed(Observation(True,1.,ready=True),0,0)
    tracker.invalid(1)
    bar=np.full((4,100,3),50,dtype=np.uint8);bar[:,:round(fraction*100)]=240
    result=tracker.feed(observe(bar,hp,portrait),2,1)
    assert result['status']=='cooldown' and not result['held']
    assert result['progress']==pytest.approx(fraction)


def test_known_layout_updates_readable_slot_immediately_while_other_slots_hold():
    pixels=np.full((1152,2048,4),20,dtype=np.uint8)
    regions=presets()['keyboard']
    for row in regions:
        for key in ('energy','hp','portrait'):
            x,y,w,h=row[key];x,y,w,h=round(x*2048),round(y*1152),round(w*2048),round(h*1152)
            pixels[y:y+h,x:x+w,:3]=[20,180,240] if key=='hp' else (235 if key=='energy' else 50)
    engine=VisionEngine()
    for frame in range(3): result=engine.analyze(pixels,(0,0,2048,1152),frame*.05,frame)
    assert all(s['status']=='ready' for s in result['slots'])
    engine.invalid(1,'temporary obstruction')
    for row in regions[1:]:
        for key in ('energy','hp','portrait'):
            x,y,w,h=row[key];x,y,w,h=round(x*2048),round(y*1152),round(w*2048),round(h*1152)
            pixels[y:y+h,x:x+w,:3]=20
    x,y,w,h=regions[0]['energy'];x,y,w,h=round(x*2048),round(y*1152),round(w*2048),round(h*1152)
    pixels[y:y+h,x:x+w,:3]=50
    pixels[y:y+h,x:x+w//2,:3]=235
    result=engine.analyze(pixels,(0,0,2048,1152),2,4)
    assert result['frame_valid']
    assert result['slots'][0]['status']=='cooldown' and not result['slots'][0]['held']
    assert all(s['status']=='ready' and s['held'] for s in result['slots'][1:])


def test_tinted_full_rail_and_low_hp_are_readable_per_slot():
    portrait=np.full((26,26,3),60,dtype=np.uint8)
    hp=np.zeros((7,100,3),dtype=np.uint8);hp[:,:2]=[25,45,200]
    bar=np.tile(np.array([120,150,255],dtype=np.uint8),(4,100,1))
    observed=observe(bar,hp,portrait)
    assert observed.readable and observed.ready and not observed.dead


def test_two_incidental_scenery_patches_do_not_establish_a_new_layout():
    pixels=np.full((1152,2048,4),20,dtype=np.uint8)
    for row in presets()['keyboard'][:2]:
        for key in ('energy','hp','portrait'):
            x,y,w,h=row[key];left,top=round(x*2048),round(y*1152)
            pixels[top:top+round(h*1152),left:left+round(w*2048),:3]=[20,180,240] if key=='hp' else 200
    engine=VisionEngine()
    for frame in range(4):assert not engine.analyze(pixels,(0,0,2048,1152),frame*.05,frame)['frame_valid']
