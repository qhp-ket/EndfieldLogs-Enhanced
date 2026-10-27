"""Idle summary workers and native consumers; no display staging."""
import asyncio
import json
from types import SimpleNamespace
from endfield_pcap.models import ServiceObserver
from app_test_support.runtime.service import service_factory, FIXTURE


def test_inactive_summary_preserves_trace_without_polling_or_display_staging(service_factory,monkeypatch):
    async def run():
        observed,calls=[],[]
        service=service_factory(observer=ServiceObserver(on_analysis_summary=observed.append))
        service.set_analysis_streams(set())
        original=service.summary_publisher.publish_pending
        async def measured(**kwargs):
            calls.append(True)
            return await original(**kwargs)
        monkeypatch.setattr(service.summary_publisher,'publish_pending',measured)
        task=asyncio.create_task(service._analysis_summary_loop())
        try:
            for line in FIXTURE.splitlines(keepends=True): service._handle_trace_line(line)
            await asyncio.sleep(.12)
            assert not calls and not observed
            assert not hasattr(service,'_buff_inputs') and not hasattr(service,'buff_publisher')
            assert not hasattr(service,'_buff_snapshot_loop')
            assert service.snapshot_publisher._trace_lines
            service.set_analysis_streams({'analysis_summary'})
            for _ in range(100):
                if any(row['snapshot'] for row in observed): break
                await asyncio.sleep(.01)
            assert observed[-1]['snapshot']['battle']['total_damage']==760
            service.set_analysis_streams(set())
            await asyncio.sleep(.12)
            before=len(calls)
            service._handle_trace_line('[10:00:09.000] harmless=1')
            await asyncio.sleep(.12)
            assert len(calls)==before
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_explicit_native_websocket_consumers_override_disabled_gui_streams(service_factory):
    async def run():
        service=service_factory();service.set_analysis_streams(set())
        for line in FIXTURE.splitlines(keepends=True): service._handle_trace_line(line)
        class Socket:
            request=SimpleNamespace(path='/ws?analysis=summary',headers={})
            def __init__(self): self.frames=[]
            async def send(self,text): self.frames.append(json.loads(text))
            async def wait_closed(self):
                assert service._analysis_required('analysis_summary')
                assert not service._has_full_consumers()
        socket=Socket();await service._ws_handler(socket)
        assert [row['type'] for row in socket.frames]==['hello','analysis_summary']
        assert socket.frames[1]['snapshot']['battle']['total_damage']==760
        assert not service._analysis_required('analysis_summary')
    asyncio.run(run())
