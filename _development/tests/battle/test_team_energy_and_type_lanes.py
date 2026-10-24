"""Shared resource semantics, independent lane expansion and native controls."""
from app_test_support.scenarios.energy import resource_snapshot
import asyncio
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
import endfield_pcap.analysis.battle.energy as energy
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from endfield_pcap.analysis.live.schedule import run_snapshot_updates
from endfield_pcap.trace.bridge import TraceBridge

def test_shared_energy_does_not_reset_or_disappear_on_control_or_character_filter():
    snapshot = resource_snapshot()
    before = deepcopy(snapshot)
    track = energy.energy_tracks(snapshot, 'chr_0004_pelica')
    assert len(track) == 1 and [p['value'] for p in track[0]['samples']] == [200, 120, 130]
    assert [(s['name'], s['start_ms'], s['end_ms']) for s in energy.control_segments(snapshot)] == [
        ('未知', 0, 1000), ('佩丽卡', 1000, 3000), ('陈千语', 3000, 6000)]
    assert snapshot == before

def test_energy_hover_distinguishes_measured_estimated_unknown_and_zero_speed(monkeypatch):
    monkeypatch.setattr(energy, 'energy_rules', lambda: dict(capacity=300, base_recovery_per_second=8, skills={}))
    series = energy.energy_series(resource_snapshot())
    assert energy.energy_value_at(series, 500)[0] is None
    assert energy.energy_value_at(series, 1000) == (200, '实测')
    assert energy.energy_value_at(series, 2000)[0] == 208
    assert '估算' in energy.energy_value_at(series, 2000)[1]
    assert energy.energy_value_at(series, 3500)[0] == 120  # Explicit zero recovery is not missing.
    assert energy.energy_value_at(series, 4000) == (130, '实测')
    assert energy.energy_value_at(series, 7000)[0] is None

def test_known_consumption_pauses_and_caps_without_double_counting_anchors(monkeypatch):
    skill = 'chr_0004_pelica_normal_skill'
    monkeypatch.setattr(energy, 'energy_rules', lambda: dict(capacity=300, base_recovery_per_second=8,
        stages={'known-stage': {'capacity': 300}},
        skills={skill: {'cost': 100}}))
    snapshot = dict(battle={'duration_ms': 20000, 'dungeon_context_id': 'known-stage'}, atb_events=[
        dict(ts_ms_from_start=0, value=300, recovery_speed=8),
        dict(ts_ms_from_start=4000, value=228, recovery_speed=8)],
        casts=[dict(skill_key=skill, ts_ms_from_start=1000)])
    series = energy.energy_series(snapshot)
    assert energy.energy_value_at(series, 1000)[0] == 200
    assert energy.energy_value_at(series, 1400)[0] == 200
    assert energy.energy_value_at(series, 2000)[0] == 204
    assert energy.energy_value_at(series, 4000) == (228, '实测')
    assert energy.energy_value_at(series, 20000)[0] == 300

def test_type_lanes_start_collapsed_and_expand_independently_with_native_buttons(app):
    owner = 'chr_0004_pelica'
    casts = [dict(character_key=owner, skill_key=owner+kind,
                  ts_ms_from_start=stamp, end_ms_from_start=stamp+3000)
             for kind in ('_normal_skill', '_combo_skill') for stamp in (0, 1000)]
    snapshot = dict(battle={'duration_ms': 5000}, participants=[{'character_key': owner}], casts=casts)
    before = deepcopy(snapshot)
    dialog = BattleDetailDialog(snapshot, '类型轨道')
    try:
        assert dialog.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint
        assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
        dialog.show(); QTest.qWait(80)
        timeline = dialog.timeline
        assert timeline.skill_lane_rows == {(owner, '战技'): 1, (owner, '连携'): 1}
        y, _, key = timeline._expand_rows[0]
        point = timeline.mapFromScene(0, y+10)
        point.setX(round(timeline.LEFT*.7))
        QTest.mouseClick(timeline.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert timeline.skill_lane_rows[key] == 2
        assert timeline.skill_lane_rows[(owner, '连携')] == 1
        timeline.set_zoom(200)
        assert timeline.skill_lane_rows[key] == 2  # Resize/zoom preserves expansion.
        timeline.toggle_lane(key)
        assert timeline.skill_lane_rows[key] == 1
        assert timeline.drawn_blocks == len(casts)
        dialog.showMaximized(); QTest.qWait(30)
        assert dialog.isMaximized()
        dialog.showMinimized(); QTest.qWait(30)
        assert dialog.isMinimized()
        dialog.showNormal()
        assert snapshot == before
    finally:
        dialog.close(); app.processEvents()

def test_recovery_speed_is_preserved_from_service_event_to_exact_trace_line(tmp_path):
    received = []
    path = tmp_path/'trace.log'
    bridge = TraceBridge(path, line_sink=received.append)
    bridge._handle_update_atb_info(dict(owner_id=1, atb_value=150, atb_recovery_speed=0,
        delta_value=-100, reason='ChangeRecoverySpeed', seq_id=3, client_tick_tms=4000), 1000)
    assert len(received) == 1 and 'recoverySpeed=0' in received[0] and 'tick=4000' in received[0]
    assert path.read_bytes() == received[0].encode('utf8')

def test_atb_proto3_absent_speed_is_not_confused_with_an_explicit_pause():
    from endfield_pcap.service.session.pipeline import SessionPipeline
    from endfield_pcap.proto_generated.BATTLE_ATB_DATA_pb2 import BATTLE_ATB_DATA
    assert SessionPipeline._atb_recovery_speed(BATTLE_ATB_DATA(reason=2)) is None
    assert SessionPipeline._atb_recovery_speed(BATTLE_ATB_DATA(reason=1)) == 0
    assert SessionPipeline._atb_recovery_speed(BATTLE_ATB_DATA(reason=2, atb_recovery_speed=8)) == 8

def test_reference_costs_use_runtime_patch_and_preserve_reduced_cost_variants():
    rules = energy.energy_rules()
    assert rules['scope'] == 'presentation_estimates_only'
    assert rules['skills']['chr_0004_pelica_normal_skill']['cost'] == 100  # Raw SkillData default is 40.
    assert rules['skills']['chr_0035_liino_normal_skill']['cost'] == 25
    assert rules['skills']['chr_0031_mifu_normalskill_2']['cost'] == 50

def test_completion_scheduler_coalesces_and_does_not_add_delay_after_slow_work():
    async def scenario():
        now, starts, sleeps = [0.], [], []
        async def wait():
            if len(starts) == 3:
                raise asyncio.CancelledError
        async def sleep(delay):
            sleeps.append(delay)
            now[0] += delay
        async def publish():
            starts.append(now[0])
            now[0] += .03 if len(starts) == 1 else .25
        try:
            await run_snapshot_updates(wait, publish, clock=lambda: now[0], sleep=sleep)
        except asyncio.CancelledError:
            pass
        assert starts == [0., .1, .35]
        assert len(sleeps) == 1 and abs(sleeps[0]-.07) < 1e-9
    asyncio.run(scenario())

def test_publisher_idle_wait_wakes_for_new_lines_and_reset():
    class Parser:
        def feed_lines(self, lines): pass
        def snapshot(self): return None
    async def scenario():
        publisher = SnapshotPublisher(parser_factory=Parser)
        await publisher.publish_pending()
        waiter = asyncio.create_task(publisher.wait_for_pending())
        await asyncio.sleep(0)
        assert not waiter.done()
        publisher.feed_line('one\n')
        await asyncio.wait_for(waiter, 1)
        await publisher.publish_pending()
        waiter = asyncio.create_task(publisher.wait_for_pending())
        await asyncio.sleep(0)
        assert not waiter.done()
        publisher.reset()
        await asyncio.wait_for(waiter, 1)
        assert (await publisher.publish_pending())['snapshot'] is None
    asyncio.run(scenario())
