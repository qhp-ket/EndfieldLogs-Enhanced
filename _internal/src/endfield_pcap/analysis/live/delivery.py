"""Per-consumer state coalescing; control boundaries retain their ordering."""
import asyncio
import queue
from collections import deque


STATE_TYPES = {'analysis_summary', 'analysis_snapshot', 'combo_snapshot', 'buff_snapshot'}
MAX_PENDING_MESSAGES = 1024


def replaceable(item):
    return (item.get('type') in STATE_TYPES and item.get('snapshot', item.get('state')) is not None
            and not item.get('error'))


class ClientSender:
    def __init__(self, socket, serialize, failed):
        self.socket, self.serialize, self.failed = socket, serialize, failed
        self.pending = deque()
        self.closed = False
        self.overflow = False
        self.ready = asyncio.Event()
        self.task = asyncio.create_task(self.run())

    def put(self, payload):
        if self.closed:
            return
        if replaceable(payload):
            # Stop at any control/reset; never move state across that boundary.
            for index in range(len(self.pending)-1, -1, -1):
                old = self.pending[index]
                if not replaceable(old):
                    break
                if (old['type'], old.get('stream_id')) == (payload['type'], payload.get('stream_id')):
                    self.pending[index] = payload
                    self.ready.set()
                    return
        if len(self.pending) >= MAX_PENDING_MESSAGES:
            # Disconnect instead of dropping a control/reset and continuing
            # with a state stream whose ordering is no longer trustworthy.
            self.closed = self.overflow = True
            self.ready.set()
            return
        self.pending.append(payload)
        self.ready.set()

    async def run(self):
        try:
            while True:
                await self.ready.wait()
                while self.pending or self.overflow:
                    if self.overflow:
                        raise RuntimeError('diagnostic consumer cannot keep up; reconnect required')
                    payload = self.pending.popleft()
                    encoded = await asyncio.to_thread(self.serialize, payload) if payload.get('type') == 'analysis_snapshot' else self.serialize(payload)
                    await asyncio.wait_for(self.socket.send(encoded), 1.0)
                self.ready.clear()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failed(self.socket)
            try:
                await asyncio.wait_for(self.socket.close(), .1)
            except Exception:
                pass
        finally:
            self.closed = True
            self.pending.clear()


class GuiDeliveryQueue(queue.Queue):
    """Qt summaries replace pending state only within consecutive state runs."""
    def _put(self, item):
        kind, payload = item
        if kind == 'analysis_summary' and replaceable(payload):
            for index in range(len(self.queue)-1, -1, -1):
                old_kind, old = self.queue[index]
                if old_kind in {'state', 'error', 'stopped'}:
                    break
                if old_kind != kind:
                    continue
                if not replaceable(old):
                    break
                if old.get('stream_id') == payload.get('stream_id'):
                    self.queue[index] = item
                    self.unfinished_tasks -= 1
                    return
        super()._put(item)
