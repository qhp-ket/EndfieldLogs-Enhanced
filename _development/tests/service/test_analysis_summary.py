import asyncio
import json
import websockets
import threading
from endfield_pcap.models import ServiceObserver
from endfield_pcap.analysis.live.delivery import ClientSender
from endfield_pcap.analysis.live.delivery import GuiDeliveryQueue
from endfield_pcap.analysis.live.delivery import MAX_PENDING_MESSAGES
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from endfield_pcap.analysis.live.publisher import _transport_copy
from parser_core.live_summary import summary_from_report
from parser_core.unified import parse_overlay_battle_snapshot_text
from app_test_support.runtime.service import service_factory, FIXTURE


def frame(revision=1, *, snapshot=True):
    return dict(type='analysis_summary', schema_version=1, stream_id='one', sequence=revision,
                source_generation=0, source_revision=revision,
                snapshot={'battle': {'total_damage': revision}} if snapshot else None)


def test_existing_observer_positional_arguments_keep_their_meaning():
    full, combo, summary = (lambda value: None for _ in range(3))
    observer = ServiceObserver(None, None, None, full, combo, summary)
    assert observer.on_analysis_snapshot is full
    assert observer.on_combo_snapshot is combo and observer.on_analysis_summary is summary


def test_hello_reports_application_version_from_shared_source(service_factory,monkeypatch):
    import endfield_pcap.service.runtime.websocket as module
    from endfield_pcap._version import __version__
    service=service_factory()
    assert service._hello_payload()['service_version']==__version__
    monkeypatch.setattr(module,'__version__','0.2.3')
    assert service._hello_payload()['service_version']=='0.2.3'


def test_gui_keeps_latest_state_across_metrics_but_never_across_reset_or_error():
    queue = GuiDeliveryQueue()
    queue.put(('analysis_summary', frame(1)))
    queue.put(('metrics', {}))
    queue.put(('analysis_summary', frame(2)))
    queue.put(('analysis_summary', frame(3, snapshot=False)))
    queue.put(('analysis_summary', frame(4)))
    queue.put(('error', RuntimeError('test')))
    queue.put(('analysis_summary', frame(5)))
    rows = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [row['source_revision'] for kind, row in rows if kind == 'analysis_summary'] == [2, 3, 4, 5]


def test_summary_publisher_is_canonical_compact_and_reset_isolated():
    async def run():
        publisher = SnapshotPublisher(summary=True)
        assert (await publisher.publish_pending())['snapshot'] is None
        for line in FIXTURE.splitlines(keepends=True): publisher.feed_line(line)
        message = await publisher.publish_pending()
        full = parse_overlay_battle_snapshot_text(FIXTURE, file_name='live-overlay.log')
        assert message['snapshot'] == _transport_copy(summary_from_report(full))
        assert message['source_revision'] == len(FIXTURE.splitlines())
        assert 'snapshot_quality' not in message['snapshot']
        assert await publisher.publish_pending() is None
        publisher.reset()
        assert (await publisher.publish_pending())['source_generation'] > message['source_generation']
    asyncio.run(run())


def test_summary_and_full_ws_handshakes_reconnect_and_raw_compatibility(service_factory):
    async def receive(socket): return json.loads(await asyncio.wait_for(socket.recv(), 3))
    async def run():
        observed = []
        service = service_factory(observer=ServiceObserver(on_analysis_summary=observed.append))
        await service._publish_analysis_summary()
        for line in FIXTURE.splitlines(keepends=True): service._handle_trace_line(line)
        await service._publish_analysis_summary()
        expected = observed[-1]
        assert service.snapshot_publisher._worker is None
        assert not service._has_full_consumers()
        async with websockets.serve(service._ws_handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            for _ in range(2):
                async with websockets.connect(f'ws://127.0.0.1:{port}/ws?analysis=summary') as socket:
                    assert (await receive(socket))['type'] == 'hello'
                    assert await receive(socket) == expected
                    assert not service._has_full_consumers()
                    service.batch.append({'type': 'diagnostic'})
                    await service._flush_batch()
                    assert (await receive(socket))['type'] == 'event_batch'
            async with websockets.connect(f'ws://127.0.0.1:{port}/ws') as socket:
                assert (await receive(socket))['type'] == 'hello'
                full = await receive(socket)
                assert full['type'] == 'analysis_snapshot'
                assert 'timeline_events' in full['snapshot']
                assert full['source_revision'] == expected['source_revision']
                assert full['source_generation'] == expected['source_generation']
    asyncio.run(run())


def test_slow_sender_never_blocks_another_consumer_and_preserves_reset():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Socket:
            def __init__(self, slow=False): self.sent=[]; self.slow=slow
            async def send(self, message):
                if self.slow:
                    entered.set(); await release.wait()
                self.sent.append(json.loads(message))
        slow, fast = Socket(True), Socket()
        a = ClientSender(slow, json.dumps, lambda socket: None)
        b = ClientSender(fast, json.dumps, lambda socket: None)
        try:
            a.put(frame(1)); await entered.wait()
            for revision in range(2, 100): a.put(frame(revision)); b.put(frame(revision))
            await asyncio.sleep(.02)
            assert fast.sent[-1]['source_revision'] == 99 and not slow.sent
            a.put(frame(100, snapshot=False)); a.put(frame(101)); a.put(frame(102))
            release.set(); await asyncio.sleep(.03)
            assert [row['source_revision'] for row in slow.sent] == [1, 99, 100, 102]
        finally:
            a.task.cancel(); b.task.cancel()
            await asyncio.gather(a.task,b.task,return_exceptions=True)
    asyncio.run(run())


def test_burst_queue_is_bounded_at_enqueue_and_disconnects_without_affecting_others():
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        failed=[]
        class Socket:
            def __init__(self,slow=False): self.slow=slow; self.sent=[]; self.closed=False
            async def send(self,message):
                if self.slow: entered.set(); await release.wait()
                self.sent.append(json.loads(message))
            async def close(self): self.closed=True
        slow,fast=Socket(True),Socket()
        sender=ClientSender(slow,json.dumps,failed.append)
        other=ClientSender(fast,json.dumps,failed.append)
        try:
            sender.put(frame(0)); await entered.wait()
            for revision in range(MAX_PENDING_MESSAGES-1):
                sender.put(dict(type='event_batch',sequence=revision))
            sender.put(frame(1))
            sender.put(frame(2))
            assert len(sender.pending)==MAX_PENDING_MESSAGES
            assert sender.pending[-1]['source_revision']==2 and not sender.closed
            for revision in range(10000):
                sender.put(dict(type='event_batch',sequence=revision))
            assert len(sender.pending)==MAX_PENDING_MESSAGES and sender.closed
            other.put(frame(3))
            await asyncio.sleep(.02)
            assert fast.sent[-1]['source_revision']==3
            release.set()
            await asyncio.wait_for(sender.task,2)
            assert failed==[slow] and slow.closed and not sender.pending
            # The in-flight message completes; queued control messages aren't
            # silently skipped to resume an invalid stream after overflow.
            assert slow.sent==[frame(0)]
        finally:
            sender.task.cancel(); other.task.cancel()
            await asyncio.gather(sender.task,other.task,return_exceptions=True)
    asyncio.run(run())


def test_throttled_publisher_delivers_reset_before_new_battle():
    async def run():
        class Parser:
            def feed_lines(self, lines): self.lines = lines
            def snapshot(self): return {'lines': self.lines}
        publisher = SnapshotPublisher(parser_factory=Parser, minimum_interval=.05)
        await publisher.publish_pending()
        publisher.feed_line('old\n')
        await publisher.publish_pending()
        publisher.feed_line('pending\n')
        delayed = asyncio.create_task(publisher.publish_pending())
        await asyncio.sleep(.005)
        publisher.reset()
        publisher.feed_line('new\n')
        cleared = await delayed
        assert cleared['snapshot'] is None
        latest = await publisher.publish_pending()
        assert latest['snapshot'] == {'lines': ['new\n']}
        assert latest['source_generation'] == cleared['source_generation']
    asyncio.run(run())


def test_full_observer_copy_cannot_overtake_reset(service_factory, monkeypatch):
    async def run():
        observed = []
        service = service_factory(observer=ServiceObserver(on_analysis_snapshot=observed.append))
        old = service.snapshot_publisher.current_message()
        old['snapshot'] = {'old': True}
        entered, release = threading.Event(), threading.Event()
        import endfield_pcap.service.runtime.websocket as module
        original = module.copy.deepcopy
        def blocked(value, *args, **kwargs):
            if value is old:
                entered.set()
                assert release.wait(3)
            return original(value, *args, **kwargs)
        monkeypatch.setattr(module.copy, 'deepcopy', blocked)
        task = asyncio.create_task(service._deliver_snapshot(old, 'on_analysis_snapshot',
                                     is_current=service.snapshot_publisher.is_current))
        while not entered.is_set(): await asyncio.sleep(.001)
        service.snapshot_publisher.reset()
        await service._publish_analysis_snapshot()
        release.set()
        await task
        assert len(observed) == 1 and observed[0]['snapshot'] is None
    asyncio.run(run())


def test_summary_process_recovers_retained_input_and_reset_generation():
    async def run():
        publisher = SnapshotPublisher(summary=True, use_process=True)
        try:
            await publisher.publish_pending()
            assert publisher._worker is None
            lines = FIXTURE.splitlines(keepends=True)
            for line in lines: publisher.feed_line(line)
            first = await publisher.publish_pending()
            assert first['source_revision'] == len(lines)
            assert first['snapshot'] == _transport_copy(summary_from_report(
                parse_overlay_battle_snapshot_text(FIXTURE, file_name='live-overlay.log')))
            # Only this test's private worker is terminated. The next call
            # must restore every original input line, including old evidence.
            publisher._worker.process.terminate()
            publisher._worker.process.join(2)
            publisher.feed_line('[10:00:02.500] LATE_UNKNOWN_EVIDENCE test=1\n')
            failed = await publisher.publish_pending()
            assert failed['snapshot'] is None and failed['error']
            recovered = await publisher.publish_pending()
            assert recovered['snapshot'] == first['snapshot']
            assert recovered['source_revision'] == len(lines)+1
            publisher.reset()
            for line in lines: publisher.feed_line(line)
            clear = await publisher.publish_pending()
            fresh = await publisher.publish_pending()
            assert clear['snapshot'] is None and fresh['snapshot'] == first['snapshot']
            assert fresh['source_generation'] == first['source_generation']+1
            assert fresh['source_revision'] == len(lines)
        finally:
            await publisher.close()
    asyncio.run(run())


def test_source_revision_advances_for_new_evidence_even_when_numbers_match():
    async def run():
        publisher = SnapshotPublisher(summary=True)
        await publisher.publish_pending()
        for line in FIXTURE.splitlines(keepends=True): publisher.feed_line(line)
        first = await publisher.publish_pending()
        publisher.feed_line('[10:00:02.500] UNKNOWN_LATE_EVIDENCE test=1\n')
        second = await publisher.publish_pending()
        assert second['snapshot'] == first['snapshot']
        assert second['source_revision'] == first['source_revision']+1
        assert second['sequence'] == first['sequence']+1
        assert await publisher.publish_pending() is None
    asyncio.run(run())
