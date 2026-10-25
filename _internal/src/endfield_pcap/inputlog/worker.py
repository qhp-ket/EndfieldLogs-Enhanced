"""Input subprocess entry: raw devices -> bounded writer, status-only parent IPC."""
from __future__ import annotations
from collections import Counter
import ctypes
import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from endfield_pcap.inputlog.storage import InputWriter, companion
from endfield_pcap.runtime.game_window import GameWindows


class Recorder:
    def __init__(self, config):
        self.config = config
        self.target = GameWindows(config['game_exe'])
        self.commands = queue.Queue()
        self.writer = None
        self.focus = False
        self.states = {}
        self.devices = {}
        self.errors = []
        self.backends = []
        self.active = True
        self.trace = None
        self.input_counts=Counter()
        self.filtered_counts=Counter()
        self.routes={}
        self.device_routes={}
        self.backend_lost=0
        from endfield_pcap.inputlog.elevation import is_admin
        self.administrator=is_admin()

    def emit(self, record_type, **fields):
        kind = record_type
        if kind=='gap':
            self.backend_lost+=fields.get('missing_events',fields.get('count',0))
        if kind == 'backend_baseline':
            self.states[fields['device']]=fields['values']
            if self.writer:
                self.writer.put('baseline',states={fields['device']:self.states[fields['device']]},
                                device=fields['device'],reason='device_baseline')
            return
        if kind == 'device':
            self.devices[fields['device']] = fields
            if self.writer:
                self.writer.put(kind, **fields)
            return
        if kind == 'error':
            self.errors.append(fields.get('message','设备错误'))
            self.errors=self.errors[-4:]
        if kind == 'device_change' and not fields.get('connected'):
            self.states.pop(fields['device'],None)
            self.devices.pop(fields['device'],None)
            if self.writer:
                self.writer.put('interrupt',reason='device_disconnected',device=fields['device'])
        # Refresh foreground on the event itself; timer transitions also cover idle focus loss.
        self.check_focus()
        if kind == 'input':
            backend=fields.get('backend')
            if backend in ('raw_input','windows_hook','windows_state'):
                family='keyboard' if fields.get('kind')=='key' else 'mouse'
                previous=self.routes.get(family)
                if previous and previous!=backend:
                    for device,route in self.device_routes.items():
                        if route==(family,previous):
                            if self.writer and self.focus:
                                self.writer.put('interrupt',reason='input_backend_changed',device=device)
                            self.states.pop(device,None)
                self.routes[family]=backend
                self.device_routes[fields['device']]=(family,backend)
            group=fields.get('kind','other')
            self.input_counts[group]+=1
            values = self.states.setdefault(fields['device'],{})
            values[fields['code']] = fields.get('value')
            if fields.get('phase') == 'up':
                values.pop(fields['code'],None)
            if not self.focus:
                self.filtered_counts[group]+=1
                return
        if self.writer and (kind != 'input' or self.focus):
            self.writer.put(kind,**fields)

    def check_focus(self):
        focused = bool(self.target.foreground())
        if focused == self.focus:
            return
        self.focus = focused
        if self.writer:
            self.writer.put('focus',active=focused)
            if not focused:
                self.writer.put('interrupt',reason='focus_lost')
            else:
                # Already-held keys are a baseline, never fabricated down events.
                from endfield_pcap.inputlog.backends.raw_input import key_code
                held = sorted({f'K:{key_code(v)}' for v in range(256)
                               if ctypes.windll.user32.GetAsyncKeyState(v)&0x8000})
                self.writer.put('baseline',states=self.states,keyboard_vks=held)

    def rotate(self, trace=None):
        if self.writer:
            self.writer.put('interrupt',reason='recording_boundary')
            self.writer.close('rotation')
        self.trace = str(trace) if trace else None
        folder = Path(self.config['log_dir'])/datetime.now().strftime('%Y%m%d')
        if trace:
            base = companion(trace)
        else:
            base = folder/f'input_{datetime.now():%Y%m%d_%H%M%S_%f}.input.jsonl'
        path = base
        if path.exists():
            # Repeated toggles stay associated through the session header, without overwrites.
            path = base.with_name(base.name.removesuffix('.input.jsonl')+f'.part-{time.time_ns()}.input.jsonl')
        self.writer = InputWriter(path,trace=trace)
        self.writer.put('diagnostic',reason='input_process_privilege',administrator=self.administrator)
        for fields in self.devices.values():
            self.writer.put('device',**fields)
        self.writer.put('focus',active=self.focus)
        self.writer.put('baseline',states=self.states)

    def run(self):
        from endfield_pcap.inputlog.backends.windows import WindowsInput
        from endfield_pcap.inputlog.backends.sdl import SDLInput
        self.rotate(self.config.get('trace'))
        def read_commands():
            try:
                for line in sys.stdin:
                    self.commands.put(json.loads(line))
            finally:
                self.commands.put({'command':'stop'})
        threading.Thread(target=read_commands,name='input-control',daemon=True).start()
        sent = 0
        checked=0
        published=None
        diagnosed=0
        failed = False
        try:
            self.backends.append(WindowsInput(self.emit, self.config['game_exe']))
            try:
                self.backends.append(SDLInput(self.emit))
            except Exception as exc:
                self.emit('error',message=f'手柄记录不可用：{exc}')
            while self.active:
                self.check_focus()
                while not self.commands.empty():
                    command = self.commands.get_nowait()
                    if command['command'] == 'stop':
                        self.active = False
                    elif command['command'] == 'trace' and command.get('path') != self.trace:
                        self.rotate(command.get('path'))
                for backend in self.backends:
                    backend.pump()
                if self.writer.error:
                    raise OSError(self.writer.error)
                now = time.monotonic()
                health=self.backends[0].health()
                if now-diagnosed>=5:
                    diagnosed=now
                    self.writer.put('diagnostic',reason='input_backend_health',**health)
                if now-checked >= .1:
                    checked=now
                    payload=dict(status='recording' if self.focus else 'waiting_game',
                        path=str(self.writer.path),count=self.writer.count,lost=self.writer.lost+self.backend_lost,
                        input_received=dict(self.input_counts),input_filtered=dict(self.filtered_counts),
                        raw_received=dict(self.backends[0].received),
                        fallback_devices=sorted(self.backends[0].announced),
                        capture_health=health,
                        administrator=self.administrator,
                        errors=self.errors[-4:],devices=list(self.devices.values()))
                    if payload!=published or now-sent>=5:
                        print(json.dumps(payload),flush=True)
                        published=payload
                        sent=now
                self.backends[0].wait(8 if self.focus else 50)
        except Exception as exc:
            failed = True
            self.writer.put('error',fatal=True,message=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            for backend in reversed(self.backends):
                backend.close()
            if self.writer:
                self.writer.put('interrupt',reason='stopped')
                self.writer.close('error' if failed else 'stopped')


def run(config):
    try:
        Recorder(config).run()
    except Exception as exc:
        print(json.dumps(dict(status='error',error=str(exc))),flush=True)
        raise SystemExit(1)


def main():
    config=json.loads(sys.argv[1])
    if config.pop('elevated',False):
        from endfield_pcap.inputlog.elevation import is_admin,relay
        if not is_admin():
            try:
                return relay(config)
            except Exception as exc:
                print(json.dumps(dict(status='error',error=str(exc))),flush=True)
                raise SystemExit(1)
    run(config)
