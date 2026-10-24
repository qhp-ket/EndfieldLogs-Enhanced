"""Entry demand pauses computation while capture inputs and clocks survive."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from endfield_pcap.analysis.activity import DeferredDisplayInputs
from endfield_pcap.analysis.buffs import BuffDisplayPublisher
from endfield_pcap.models import ServiceObserver
from app_test_support.runtime.service import service_factory, FIXTURE
from app_test_support.scenarios.combo import publisher, scene, trigger
from app_test_support.scenarios.buff_lines import start


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.01)


def test_disabled_buff_replay_retains_receipt_clock_and_reset(tmp_path):
    clock = [0.]
    active = BuffDisplayPublisher(clock=lambda: clock[0], data_root=tmp_path)
    paused = BuffDisplayPublisher(clock=lambda: clock[0], data_root=tmp_path)
    inputs = DeferredDisplayInputs(paused)
    rows = [(0, start(duration='10')), (2, '[10:00:02.000] harmless=1'),
            (3, start('2', duration='20', stamp='10:00:03.000'))]
    for stamp, line in rows:
        clock[0] = stamp
        active.feed_line(line)
        inputs.feed(line, active=False)
    assert not paused.buffs and len(inputs.pending) == 3
    clock[0] = 8
    assert not inputs.drain(limit=1)
    assert inputs.drain()
    assert paused.current_message()['snapshot'] == active.current_message()['snapshot']
    assert paused.current_message()['snapshot']['buffs'][0]['remaining_ms'] == 2000
    inputs.feed('[10:00:09.000] GAME_TIMER_RESET source=test', active=False)
    inputs.feed(start('3', stamp='10:00:09.100'), active=False)
    inputs.drain()
    assert [row['uid'] for row in paused.current_message()['snapshot']['buffs']] == ['3']


def test_disabled_combo_replay_preserves_debounce_clocks_and_order():
    active, clock = publisher()
    paused, _ = publisher()
    paused._wall_ms = lambda: clock.wall
    paused._monotonic_ms = lambda: clock.mono
    inputs = DeferredDisplayInputs(paused, combo=True)
    for event, advance in [(scene(), 0), (trigger(), 1000),
                           (trigger(seq_id=2, timestamp_ms=1_001_000), 3000),
                           (trigger(seq_id=3, timestamp_ms=1_004_000), 1000)]:
        active.feed_event(deepcopy(event))
        inputs.feed(deepcopy(event), active=False)
        clock.advance(advance)
    assert not paused._slots[0] and len(inputs.pending) == 4
    assert inputs.drain()
    assert paused.current_message()['snapshot'] == active.current_message()['snapshot']
    inputs.feed(None, reset=True, active=False)
    inputs.feed(trigger(seq_id=4, timestamp_ms=clock.wall), active=True)
    assert len(inputs.pending) == 2  # New input cannot overtake the reset.
    inputs.drain()
    assert paused.current_message()['snapshot']['slots'][0]['remaining_ms'] == 20_000


def test_service_disabled_streams_do_no_analysis_and_reenable_catches_up(service_factory, monkeypatch):
    async def run():
        observed, calls = [], []
        service = service_factory(observer=ServiceObserver(on_analysis_summary=observed.append))
        service.set_analysis_streams(set())
        original = service.summary_publisher.publish_pending
        async def measured(**kwargs):
            calls.append(True)
            return await original(**kwargs)
        monkeypatch.setattr(service.summary_publisher, 'publish_pending', measured)
        tasks = [asyncio.create_task(service._analysis_summary_loop()),
                 asyncio.create_task(service._buff_snapshot_loop())]
        try:
            for line in FIXTURE.splitlines(keepends=True):
                service._handle_trace_line(line)
            service._handle_trace_line(start(duration='10'))
            await asyncio.sleep(.15)
            assert not calls and not observed
            assert not service.buff_publisher.buffs
            assert service._buff_inputs.pending
            assert service.snapshot_publisher._trace_lines  # Full path retains input too.
            service.set_analysis_streams({'analysis_summary', 'buff_snapshot'})
            await eventually(lambda: any(row['snapshot'] for row in observed)
                             and not service._buff_inputs.pending)
            assert observed[-1]['snapshot']['battle']['total_damage'] == 760
            assert service.buff_publisher.buffs
            service.set_analysis_streams(set())
            await asyncio.sleep(.15)
            before = len(calls)
            service._handle_trace_line('[10:00:09.000] harmless=1')
            await asyncio.sleep(.15)
            assert len(calls) == before
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(run())


def test_explicit_websocket_consumers_override_disabled_gui_streams(service_factory):
    async def run():
        service = service_factory()
        service.set_analysis_streams(set())
        for line in FIXTURE.splitlines(keepends=True): service._handle_trace_line(line)
        service._handle_trace_line(start())
        class Socket:
            request = SimpleNamespace(path='/ws?analysis=summary')
            def __init__(self): self.frames = []
            async def send(self, text): self.frames.append(json.loads(text))
            async def wait_closed(self):
                for stream in ('analysis_summary', 'buff_snapshot'):
                    assert service._analysis_required(stream)
                assert not service._has_full_consumers()
        socket = Socket()
        await service._ws_handler(socket)
        assert [row['type'] for row in socket.frames] == ['hello', 'analysis_summary', 'buff_snapshot']
        assert socket.frames[1]['snapshot']['battle']['total_damage'] == 760
        assert socket.frames[-1]['snapshot']['buffs']
        assert not service._analysis_required('analysis_summary')
        assert not service._analysis_required('buff_snapshot')
        service.set_analysis_streams({'buff_snapshot'})
        service.active_flow = object()
        service._reset_session()
        assert not service._buff_inputs.pending
        assert not service.buff_publisher.buffs
        assert not service.summary_publisher._trace_lines
    asyncio.run(run())
