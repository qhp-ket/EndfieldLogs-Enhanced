from __future__ import annotations
import asyncio
import copy


class AnalysisStreams:
    async def _analysis_snapshot_loop(self) -> None:
        from endfield_pcap.analysis.live.schedule import run_snapshot_updates
        async def wait():
            while not self._has_full_consumers():
                self._full_demand_changed.clear()
                await self.snapshot_publisher.close()
                if self._has_full_consumers():
                    break
                await self._full_demand_changed.wait()
            await self.snapshot_publisher.wait_for_pending()
        async def publish():
            if self._has_full_consumers():
                await self._publish_analysis_snapshot()
        await run_snapshot_updates(wait, publish, minimum_interval=1.0)

    def _has_full_consumers(self):
        return bool(self.clients-self._summary_clients or self._custom_full or self._full_handshakes
                    or getattr(self.observer, 'on_analysis_snapshot', None))

    def set_full_analysis_required(self, required):
        changed = self._custom_full != bool(required)
        self._custom_full = bool(required)
        if required or changed:
            self.snapshot_publisher.request_current()
        self._full_demand_changed.set()

    async def _analysis_summary_loop(self):
        from endfield_pcap.analysis.live.schedule import run_snapshot_updates
        async def wait():
            while not self._analysis_required('analysis_summary'):
                self._analysis_demand_changed.clear()
                await self.summary_publisher.close()
                if self._analysis_required('analysis_summary'):
                    break
                await self._analysis_demand_changed.wait()
            await self.summary_publisher.wait_for_pending()
        async def publish():
            if self._analysis_required('analysis_summary'):
                await self._publish_analysis_summary()
        await run_snapshot_updates(wait, publish)

    def _analysis_required(self, stream):
        if stream == 'combo_snapshot':
            return False
        if stream == 'analysis_summary':
            remote = bool(self._summary_clients or self._summary_handshakes)
        else:
            # Both WS modes continue to include observed BUFF state.
            remote = bool(self.clients or self._full_handshakes or self._summary_handshakes)
        return self._analysis_streams is None or stream in self._analysis_streams or remote

    def set_analysis_streams(self, streams):
        streams = frozenset(streams) - {'combo_snapshot'}
        if streams == self._analysis_streams:
            return
        self._analysis_streams = streams
        self.summary_publisher.request_current()
        self._analysis_demand_changed.set()

    async def _catch_up_display_inputs(self):
        while self._buff_inputs.pending:
            self._buff_inputs.drain()
            await asyncio.sleep(0)

    async def _publish_analysis_summary(self):
        payload = await self.summary_publisher.publish_pending(copy_result=False)
        if (payload is not None and self.summary_publisher.is_current(payload)
                and self._analysis_required('analysis_summary')):
            await self._deliver_snapshot(payload, 'on_analysis_summary')

    async def _buff_snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            if self._analysis_required('buff_snapshot') and self._buff_inputs.drain():
                await self._publish_buff_snapshot()

    async def _publish_buff_snapshot(self) -> None:
        payload = self.buff_publisher.current_message()
        if payload == self._last_buff_message:
            return
        self._last_buff_message = payload
        callback = getattr(self.observer, "on_buff_snapshot", None)
        if callback is not None:
            callback(copy.deepcopy(payload))
        async with self._analysis_delivery_lock:
            if payload == self._last_buff_message:
                await self._deliver_snapshot(payload, None)

    async def _publish_analysis_snapshot(self) -> None:
        payload = await self.snapshot_publisher.publish_pending(copy_result=False)
        if payload is None:
            return
        if self.snapshot_publisher.is_current(payload):
            await self._deliver_snapshot(payload, "on_analysis_snapshot",
                                         is_current=self.snapshot_publisher.is_current)
