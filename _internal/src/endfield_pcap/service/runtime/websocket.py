from __future__ import annotations
import asyncio
import copy
import json
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from endfield_pcap._version import __version__
from endfield_pcap.service.runtime.access import browser_request_allowed


class WebSocketDelivery:
    async def _ws_process_request(self, connection, request):
        if isinstance(connection, str):
            # Legacy API: (path, request_headers), with an HTTP response tuple.
            if not browser_request_allowed(request, self.config.ws_browser_token, path=connection):
                return (HTTPStatus.FORBIDDEN, [('Content-Type', 'text/plain; charset=utf-8')],
                        b'Browser WebSocket access requires a valid token.\n')
            return None
        if not browser_request_allowed(request, self.config.ws_browser_token):
            return connection.respond(HTTPStatus.FORBIDDEN, 'Browser WebSocket access requires a valid token.\n')

    async def _ws_handler(self, websocket):
        from urllib.parse import parse_qs, urlsplit
        from endfield_pcap.analysis.live.delivery import ClientSender
        request = getattr(websocket, 'request', None)
        path = getattr(request, 'path', getattr(websocket, 'path', ''))
        if request is None:
            request = getattr(websocket, 'request_headers', None)
        # Retain the boundary for embedded callers that omit process_request.
        if not browser_request_allowed(request, self.config.ws_browser_token, path=path):
            await websocket.close(code=1008, reason='Browser access denied')
            return
        summary = parse_qs(urlsplit(path).query).get('analysis') == ['summary']
        publisher = self.summary_publisher if summary else self.snapshot_publisher
        sender = None
        if not summary:
            self._full_handshakes += 1
            self._full_demand_changed.set()
        else:
            self._summary_handshakes += 1
        self._analysis_demand_changed.set()
        try:
            # Handshake I/O holds no shared lock: a blocked hello cannot stop
            # calculation, Qt publication, or another client's handshake.
            await asyncio.wait_for(websocket.send(json.dumps(self._hello_payload(), ensure_ascii=False)), 1.0)
            cached = publisher.current_message(copy_result=False)
            if (cached.get('source_revision') != publisher._revision
                    or cached.get('source_generation') != publisher._generation):
                publisher.request_current()
                # Initial/reset null and following current state are ordered.
                publish = self._publish_analysis_summary if summary else self._publish_analysis_snapshot
                await publish()
                await publish()
            handshake_state = publisher.current_message(copy_result=False)
            encoded = (json.dumps(handshake_state, ensure_ascii=False) if summary else
                       await asyncio.to_thread(json.dumps, handshake_state, ensure_ascii=False))
            await asyncio.wait_for(websocket.send(encoded), 1.0)
            await self._catch_up_display_inputs()
            await asyncio.wait_for(websocket.send(json.dumps(self.buff_publisher.current_message(), ensure_ascii=False)), 1.0)
            sender = ClientSender(websocket,
                lambda payload: json.dumps(payload, ensure_ascii=False, allow_nan=False), self.clients.discard)
            self._client_senders[websocket] = sender
            if summary:
                self._summary_clients.add(websocket)
            self.clients.add(websocket)
            # Catch updates completed during handshake without mixing sources.
            if not publisher.is_current(handshake_state):
                sender.put(publisher.current_message(copy_result=False))
            self._full_demand_changed.set()
            self._analysis_demand_changed.set()
            await websocket.wait_closed()
        finally:
            if not summary:
                self._full_handshakes -= 1
            else:
                self._summary_handshakes -= 1
            self.clients.discard(websocket)
            self._summary_clients.discard(websocket)
            self._client_senders.pop(websocket, None)
            self._full_demand_changed.set()
            self._analysis_demand_changed.set()
            # Wake a clean scheduler too, so the last consumer disconnecting
            # releases its worker without waiting for another capture line.
            publisher.request_current()
            if sender is not None:
                sender.task.cancel()
                await asyncio.gather(sender.task, return_exceptions=True)

    def _hello_payload(self) -> dict[str, object]:
        return {
            "type": "hello",
            "schema_version": 2,
            "service_version": __version__,
            "state": self.state.value,
            "session_id": self.active_session.session_id if self.active_session else None,
            "metrics": asdict(self.metrics),
        }

    async def _broadcast(self, payload: dict[str, object]) -> None:
        await self._deliver_snapshot(payload, None)

    async def _batch_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            await self._flush_batch()

    async def _deliver_snapshot(self, payload: dict, observer_name: str | None, *, is_current=None) -> None:
        callback = getattr(self.observer, observer_name, None) if observer_name else None
        if callback is not None:
            owned = await asyncio.to_thread(copy.deepcopy, payload) if payload.get('type') == 'analysis_snapshot' else copy.deepcopy(payload)
            if is_current is not None and not is_current(payload):
                return
            callback(owned)
        # Managed sockets are always queued. The direct path supports embedded
        # callers that register an existing socket without using _ws_handler.
        direct = []
        for client in tuple(self.clients):
            kind = payload.get('type')
            if kind == 'analysis_summary' and client not in self._summary_clients:
                continue
            if kind == 'analysis_snapshot' and client in self._summary_clients:
                continue
            sender = self._client_senders.get(client)
            if sender is not None:
                sender.put(payload)
            else:
                direct.append(client)
        if not direct:
            # Yield to independent senders without waiting for any network I/O.
            await asyncio.sleep(0)
            return
        message = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        async def send(client):
            try:
                await asyncio.wait_for(client.send(message), 1.0)
            except Exception:
                self.clients.discard(client)
                try:
                    await asyncio.wait_for(client.close(), .1)
                except Exception:
                    pass
        await asyncio.gather(*(send(client) for client in direct))

    async def _flush_batch(self) -> None:
        if not self.batch:
            return
        payload = {
            "type": "event_batch",
            "session_id": self.active_session.session_id if self.active_session else None,
            "sent_at_ms": int(datetime.now().timestamp() * 1000),
            "events": self.batch[:128],
        }
        del self.batch[:128]
        self.metrics.ws_batches_sent += 1
        await self._broadcast(payload)
