"""Last-resort foreground state transitions, explicitly distinct from raw events.

Some exclusive input paths do not deliver keyboard hooks or WM_INPUT. Sampling
cannot recover repeats, wheel reports, device identities or sub-sample taps.
These limitations are recorded, rather than claiming complete Raw Input.
"""
from __future__ import annotations
import time
import threading
from endfield_pcap.inputlog.backends.raw_input import key_code


class WindowsStateFallback:
    interval_ms = 8
    delay_ns = 80_000_000

    def __init__(self, emit, foreground, read_state):
        self.emit, self.foreground, self.read_state = emit, foreground, read_state
        self.states = None
        self.pending = []
        self.delivered = {}
        self.announced = set()
        self.last_sample = None
        self.samples = 0
        self._lock = threading.Lock()

    def note_event(self, fields):
        if fields.get('phase') in ('down', 'up', 'repeat'):
            with self._lock:
                self.delivered[(fields.get('code'), 'down' if fields['phase']=='repeat' else fields['phase'])] = fields.get('mono_ns', time.perf_counter_ns())

    def pump(self):
        now = time.perf_counter_ns()
        if not self.foreground():
            self.states = None
            self.pending.clear()
            with self._lock: self.delivered.clear()
            self.last_sample = None
            return
        if self.last_sample is not None and now-self.last_sample < self.interval_ms*1_000_000:
            return
        self.last_sample = now
        self.samples += 1
        values = {vk for vk in range(1, 256) if self.read_state(vk) & 0x8000}
        if self.states is not None:
            for vk in sorted(values ^ self.states):
                # Generic modifiers and their side-specific forms are the same
                # key; the log's existing normalized bindings use generic forms.
                if vk in (0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5):
                    continue
                mouse = {1:1, 2:2, 4:3, 5:4, 6:5}.get(vk)
                code = f'M:{mouse}' if mouse else 'K:'+key_code(vk)
                phase = 'down' if vk in values else 'up'
                self.pending.append(dict(code=code, phase=phase, value=int(vk in values),
                    kind='button' if mouse else 'key', mono_ns=now, wall_ns=time.time_ns(),
                    raw=dict(vk=vk, observation='sampled_state', sample_interval_ms=self.interval_ms)))
        self.states = values
        waiting = []
        for event in self.pending:
            if now-event['mono_ns'] < self.delay_ns:
                waiting.append(event)
                continue
            with self._lock: recent = self.delivered.get((event['code'], event['phase']))
            if recent is not None and abs(recent-event['mono_ns']) <= self.delay_ns*2:
                continue
            device = 'windows:state:keyboard' if event['kind']=='key' else 'windows:state:mouse'
            if device not in self.announced:
                self.announced.add(device)
                self.emit('device', device=device, backend='windows_state', device_identity_available=False,
                          name='Windows 状态采样（兼容模式）')
                self.emit('diagnostic', reason='input_state_sampling_fallback', device=device,
                    sample_interval_ms=self.interval_ms,
                    message='原始报告和事件回调未送达，使用前台按键状态采样；无物理设备身份、自动重复、滚轮及原始鼠标位移，短于采样间隔的点击可能遗漏。')
            self.emit('input', device=device, backend='windows_state', device_identity_available=False,
                      timing_uncertainty_ms=self.interval_ms, **event)
        self.pending = waiting
        with self._lock:
            self.delivered = {k:v for k,v in self.delivered.items() if now-v < 1_000_000_000}

    def close(self):
        self.pending.clear()
