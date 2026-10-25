"""Passive Windows hooks for sessions where Raw Input delivery is unavailable.

Raw reports take precedence. Hook reports retain their actual source and lack
of device identity; they are never presented as device-specific Raw Input.
No input is suppressed, injected or sent to another process.
"""
from __future__ import annotations
from collections import deque
import ctypes as c
from ctypes import wintypes as w
import time
from endfield_pcap.inputlog.backends.raw_input import key_code


class Keyboard(c.Structure):
    _fields_=[('vk',w.DWORD),('scan',w.DWORD),('flags',w.DWORD),('time',w.DWORD),('extra',c.c_size_t)]


class Mouse(c.Structure):
    _fields_=[('point',w.POINT),('data',w.DWORD),('flags',w.DWORD),('time',w.DWORD),('extra',c.c_size_t)]


class WindowsInputFallback:
    delay=.06

    def __init__(self,emit,foreground,on_event=None):
        self.emit,self.foreground=emit,foreground
        self.on_event=on_event
        self.pending=deque()
        self.raw_times={}
        self.pressed=set()
        self.announced=set()
        self.error=None
        self.user=c.WinDLL('user32',use_last_error=True)
        self.callback_type=c.WINFUNCTYPE(c.c_ssize_t,c.c_int,w.WPARAM,w.LPARAM)
        self.user.SetWindowsHookExW.argtypes=[c.c_int,self.callback_type,w.HINSTANCE,w.DWORD]
        self.user.SetWindowsHookExW.restype=w.HHOOK
        self.user.CallNextHookEx.argtypes=[w.HHOOK,c.c_int,w.WPARAM,w.LPARAM]
        self.user.CallNextHookEx.restype=c.c_ssize_t
        self.user.UnhookWindowsHookEx.argtypes=[w.HHOOK]
        kernel=c.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleHandleW.restype=w.HMODULE
        self.callbacks=[self.callback_type(self._keyboard),self.callback_type(self._mouse)]
        self.hooks=[]
        try:
            for kind,callback in zip((13,14),self.callbacks):
                handle=self.user.SetWindowsHookExW(kind,callback,kernel.GetModuleHandleW(None),0)
                if not handle:raise c.WinError(c.get_last_error())
                self.hooks.append(handle)
        except Exception:
            self.close()
            raise

    def _queue(self,**fields):
        # Do not retain other applications' keys, even in the transient queue.
        if not self.foreground():return
        now=time.perf_counter_ns()
        if len(self.pending)>=8192:
            missing=len(self.pending)
            self.pending.clear()
            # One sequence record describes the dropped backend events; these
            # were never assigned JSONL sequence numbers by the writer.
            self.emit('gap',reason='windows_fallback_overflow',count=1,missing_events=missing,
                      mono_ns=now,wall_ns=time.time_ns())
        event=dict(fields,mono_ns=now,wall_ns=time.time_ns())
        self.pending.append(event)
        observed=getattr(self,'on_event',None)
        if observed:observed(event)

    def _keyboard(self,code,message,data):
        try:
            if code>=0:
                item=c.cast(data,c.POINTER(Keyboard)).contents
                up=message in (0x101,0x105)
                repeat=not up and item.vk in self.pressed
                self.pressed.discard(item.vk) if up else self.pressed.add(item.vk)
                self._queue(kind='key',code='K:'+key_code(item.vk),phase='up' if up else 'repeat' if repeat else 'down',
                            value=0 if up else 1,raw=dict(vk=item.vk,scan=item.scan,flags=item.flags,
                                                      native_time_ms=item.time,injected=bool(item.flags&0x10)))
        except Exception as exc:self.error=str(exc)
        return self.user.CallNextHookEx(None,code,message,data)

    def _mouse(self,code,message,data):
        try:
            if code>=0:
                item=c.cast(data,c.POINTER(Mouse)).contents
                raw=dict(flags=item.flags,native_time_ms=item.time,injected=bool(item.flags&1))
                if message==0x200:
                    self._queue(kind='motion',code='M:MOVE',value=[item.point.x,item.point.y],
                                raw=dict(raw,coordinate_space='screen_absolute'))
                elif message in (0x20a,0x20e):
                    self._queue(kind='wheel',code='M:WHEEL' if message==0x20a else 'M:HWHEEL',
                                value=c.c_short(item.data>>16).value,raw=raw)
                else:
                    buttons={0x201:(1,False),0x202:(1,True),0x204:(2,False),0x205:(2,True),
                             0x207:(3,False),0x208:(3,True),0x20b:(3+(item.data>>16),False),
                             0x20c:(3+(item.data>>16),True)}
                    if message in buttons:
                        button,up=buttons[message]
                        self._queue(kind='button',code=f'M:{button}',phase='up' if up else 'down',value=int(not up),raw=raw)
        except Exception as exc:self.error=str(exc)
        return self.user.CallNextHookEx(None,code,message,data)

    def note_raw(self,fields):
        group=(fields.get('kind'),fields.get('code'),fields.get('phase'))
        self.raw_times[group]=time.perf_counter_ns()

    def pump(self):
        now=time.perf_counter_ns()
        while self.pending and now-self.pending[0]['mono_ns']>=self.delay*1e9:
            item=self.pending.popleft()
            group=(item['kind'],item['code'],item.get('phase'))
            # The raw callback normally follows the hook in the same message
            # batch. Also discard recent raw duplicates when batches straddle.
            if abs(self.raw_times.get(group,-10**30)-item['mono_ns'])<=self.delay*2e9:continue
            if not self.foreground():continue
            device='windows:keyboard' if item['kind']=='key' else 'windows:mouse'
            if device not in self.announced:
                self.announced.add(device)
                self.emit('device',device=device,backend='windows_hook',name='Windows 输入（设备身份不可用）',
                          device_identity_available=False)
                self.emit('diagnostic',reason='raw_input_delivery_fallback',device=device,
                          message='未收到对应 Raw Input 报告，使用 Windows 输入事件；无法区分物理设备')
            self.emit('input',device=device,backend='windows_hook',device_identity_available=False,**item)
        if self.error:raise RuntimeError(self.error)

    def close(self):
        for handle in self.hooks:self.user.UnhookWindowsHookEx(handle)
        self.hooks.clear()
