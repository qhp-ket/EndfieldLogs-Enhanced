"""Unchanged observations do not drive repeated DOM/layout updates."""
from copy import deepcopy
from types import SimpleNamespace
from endfield_pcap.vision.controller import VisionController


def test_timing_only_changes_are_not_published_but_identity_and_state_are(app):
    controller=VisionController('unused.exe')
    controller.hwnd=1
    state=dict(target_hwnd=1,frame_valid=True,status='识别中',layout='keyboard',
               processing_ms=1,published_mono=1,slots=[dict(slot=0,status='ready',progress=1.,
               estimated_remaining_ms=0,stale=False,held=False)])
    controller.receive(state)
    first=controller.take_snapshot()
    assert first['sequence']==1
    for i in range(20):
        controller.receive(dict(state,processing_ms=i,published_mono=i))
        assert controller.take_snapshot() is None
    controller.set_identity([SimpleNamespace(squad_index=0,templateid='char_1',display_name='角色')],'session')
    assert controller.take_snapshot()['snapshot']['slots'][0]['character_key']=='char_1'
    changed=deepcopy(state)
    changed['slots'][0].update(status='cooldown',progress=0.)
    controller.receive(changed)
    assert controller.take_snapshot()['snapshot']['slots'][0]['status']=='cooldown'
    controller.deleteLater()
