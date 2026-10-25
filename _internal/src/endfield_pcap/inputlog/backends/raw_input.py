"""Windows Raw Input keyboard/mouse receiver; device events, no hooks or injection."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import struct
import uuid
import time


class Header(c.Structure):
    _fields_ = [('kind', w.DWORD), ('size', w.DWORD), ('device', w.HANDLE), ('param', w.WPARAM)]


class Device(c.Structure):
    _fields_ = [('page', w.USHORT), ('usage', w.USHORT), ('flags', w.DWORD), ('target', w.HWND)]


def key_code(vk):
    return {0x10:'SHIFT', 0xa0:'SHIFT', 0xa1:'SHIFT', 0x11:'CTRL', 0xa2:'CTRL', 0xa3:'CTRL',
            0x12:'ALT', 0xa4:'ALT', 0xa5:'ALT', 0x5b:'WIN', 0x5c:'WIN'}.get(vk, str(vk))


class RawInput:
    def __init__(self, emit):
        self.emit = emit
        self.user = c.WinDLL('user32', use_last_error=True)
        kernel = c.WinDLL('kernel32', use_last_error=True)
        self.callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        class WindowClass(c.Structure):
            _fields_ = [('style', w.UINT), ('proc', self.callback_type), ('cls_extra', c.c_int),
                ('wnd_extra', c.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]
        self.user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user.DefWindowProcW.restype = c.c_ssize_t
        self.user.GetRawInputData.argtypes = [w.HANDLE, w.UINT, c.c_void_p, c.POINTER(w.UINT), w.UINT]
        self.user.GetRawInputData.restype = w.UINT
        self.user.GetRawInputDeviceInfoW.argtypes = [w.HANDLE, w.UINT, c.c_void_p, c.POINTER(w.UINT)]
        self.user.GetRawInputDeviceInfoW.restype = w.UINT
        self.user.CreateWindowExW.argtypes = [w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,
            c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p]
        self.user.CreateWindowExW.restype = w.HWND
        self.user.RegisterRawInputDevices.argtypes = [c.POINTER(Device), w.UINT, w.UINT]
        self.user.DestroyWindow.argtypes = [w.HWND]
        self.user.UnregisterClassW.argtypes = [w.LPCWSTR,w.HINSTANCE]
        self.user.PeekMessageW.argtypes = [c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT]
        self.user.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
        self.user.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]
        self.user.DispatchMessageW.restype = c.c_ssize_t
        self.user.MsgWaitForMultipleObjectsEx.argtypes=[w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.DWORD]
        self.user.MsgWaitForMultipleObjectsEx.restype=w.DWORD
        kernel.GetModuleHandleW.restype = w.HMODULE
        self.known, self.pressed = set(), set()
        self.error = None
        self.received = {'keyboard':0,'mouse':0,'hid':0}
        self.name = 'EndfieldInput_'+uuid.uuid4().hex
        self.proc = self.callback_type(self._message)
        self.instance = kernel.GetModuleHandleW(None)
        wc = WindowClass(proc=self.proc, instance=self.instance, name=self.name)
        if not self.user.RegisterClassW(c.byref(wc)):
            raise c.WinError(c.get_last_error())
        self.hwnd = self.user.CreateWindowExW(0, self.name, '', 0, 0,0,0,0,
                                             w.HWND(-3), None, self.instance, None)
        if not self.hwnd:
            raise c.WinError(c.get_last_error())
        devices = (Device*2)(Device(1,6,0x2100,self.hwnd), Device(1,2,0x2100,self.hwnd))
        if not self.user.RegisterRawInputDevices(devices, 2, c.sizeof(Device)):
            self.close()
            raise c.WinError(c.get_last_error())

    def _device(self, handle):
        identity = f'raw:{int(getattr(handle,"value",handle) or 0):x}'
        if identity not in self.known:
            size = w.UINT()
            self.user.GetRawInputDeviceInfoW(handle, 0x20000007, None, c.byref(size))
            name = c.create_unicode_buffer(size.value+1)
            self.user.GetRawInputDeviceInfoW(handle, 0x20000007, name, c.byref(size))
            self.known.add(identity)
            self.emit('device', device=identity, backend='raw_input', name=name.value)
        return identity

    def _message(self, hwnd, message, param, data):
        try:
            if message == 0xff:
                size = w.UINT()
                result=self.user.GetRawInputData(w.HANDLE(data), 0x10000003, None, c.byref(size), c.sizeof(Header))
                if result==0xffffffff:
                    raise c.WinError(c.get_last_error())
                if size.value:
                    buffer = c.create_string_buffer(size.value)
                    got = self.user.GetRawInputData(w.HANDLE(data), 0x10000003, buffer, c.byref(size), c.sizeof(Header))
                    if got == 0xffffffff:
                        raise c.WinError(c.get_last_error())
                    if got < c.sizeof(Header):
                        raise RuntimeError('Raw Input 返回了不完整的报告头')
                    header=Header.from_buffer_copy(buffer)
                    self.received[{0:'mouse',1:'keyboard'}.get(header.kind,'hid')]+=1
                    self._decode(buffer.raw[:got])
            elif message == 0xfe:
                identity = self._device(w.HANDLE(data))
                self.emit('device_change', device=identity, connected=param == 1)
                if param == 2:
                    self.pressed = {p for p in self.pressed if p[0] != identity}
                    self.known.discard(identity)
        except Exception as exc:
            self.error = str(exc)
        return self.user.DefWindowProcW(hwnd, message, param, data)

    def _decode(self, data):
        header = Header.from_buffer_copy(data)
        device = self._device(header.device)
        raw = data[c.sizeof(Header):]
        if header.kind == 1 and len(raw) >= 16:
            scan, flags, _, vk, message, extra = struct.unpack_from('<HHHHII', raw)
            if vk == 255:
                return
            code = 'K:'+key_code(vk)
            key = (device, scan, flags & 6)
            up = bool(flags & 1)
            repeat = not up and key in self.pressed
            self.pressed.discard(key) if up else self.pressed.add(key)
            self.emit('input', device=device, backend='raw_input', kind='key', code=code,
                phase='up' if up else ('repeat' if repeat else 'down'), value=0 if up else 1,
                raw=dict(vk=vk, scan=scan, flags=flags, message=message, extra=extra))
        elif header.kind == 0 and len(raw) >= 24:
            flags = struct.unpack_from('<H',raw)[0]
            buttons, button_data = struct.unpack_from('<HH',raw,4)
            dx,dy,extra = struct.unpack_from('<iiI',raw,12)
            if dx or dy or flags & 1:
                self.emit('input', device=device, backend='raw_input', kind='motion',
                    code='M:MOVE', value=[dx,dy], raw=dict(flags=flags, extra=extra))
            for n in range(5):
                for bit,phase in ((1<<(n*2),'down'),(2<<(n*2),'up')):
                    if buttons & bit:
                        self.emit('input', device=device, backend='raw_input',kind='button',
                                  code=f'M:{n+1}',phase=phase,value=int(phase=='down'))
            for bit,axis in ((0x400,'WHEEL'),(0x800,'HWHEEL')):
                if buttons & bit:
                    value = c.c_short(button_data).value
                    self.emit('input', device=device, backend='raw_input', kind='wheel',code='M:'+axis,value=value)

    def pump(self):
        message = w.MSG()
        deadline=time.perf_counter()+.004
        while time.perf_counter()<deadline and self.user.PeekMessageW(c.byref(message), None, 0,0,1):
            self.user.TranslateMessage(c.byref(message))
            self.user.DispatchMessageW(c.byref(message))
        if self.error:
            raise RuntimeError(self.error)

    def wait(self,milliseconds):
        # Wake immediately for input, rather than polling 500 times per second.
        self.user.MsgWaitForMultipleObjectsEx(0,None,milliseconds,0x04ff,0x0004)

    def close(self):
        if self.hwnd:
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
        self.user.UnregisterClassW(self.name, self.instance)
