"""Read-only Windows process/window identity shared by independent services."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import os
import time


def process_executable(pid):
    """Query process identity without a third-party module or reading process memory."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        name = ctypes.create_unicode_buffer(32768)
        size = w.DWORD(len(name))
        return name.value if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) else None
    finally:
        kernel.CloseHandle(handle)


class GameWindows:
    def __init__(self, executable):
        self.executable = os.path.normcase(os.path.abspath(str(executable)))
        self._cache = {}
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.GetForegroundWindow.restype = w.HWND
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.IsWindowVisible.argtypes = [w.HWND]
        self.user.IsIconic.argtypes = [w.HWND]
        self.user.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]

    def matches(self, hwnd):
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        now = time.monotonic()
        cached = self._cache.get(pid.value)
        if cached and now-cached[0] < 1:
            return cached[1]
        executable = process_executable(pid.value)
        match = executable is not None and os.path.normcase(os.path.abspath(executable)) == self.executable
        self._cache[pid.value] = now, match
        if len(self._cache) > 256:
            self._cache = {pid.value: (now, match)}
        return match

    def foreground(self):
        hwnd = self.user.GetForegroundWindow()
        return int(hwnd) if hwnd and self.matches(hwnd) else None

    def windows(self):
        found = []
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def visit(hwnd, _):
            if self.user.IsWindowVisible(hwnd) and self.matches(hwnd):
                rect = w.RECT()
                self.user.GetClientRect(hwnd, ctypes.byref(rect))
                if rect.right > 0 and rect.bottom > 0:
                    found.append(int(hwnd))
            return True
        callback = callback_type(visit)
        self.user.EnumWindows(callback, 0)
        return found

    def client_in_frame(self, hwnd, width, height):
        """WGC includes the visible frame; map its client rect without screen DPI assumptions."""
        dwm = ctypes.WinDLL('dwmapi')
        frame, client = w.RECT(), w.RECT()
        origin = w.POINT()
        dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
        self.user.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame)) != 0:
            return (0, 0, width, height)
        self.user.GetClientRect(hwnd, ctypes.byref(client))
        self.user.ClientToScreen(hwnd, ctypes.byref(origin))
        sx, sy = width/max(1, frame.right-frame.left), height/max(1, frame.bottom-frame.top)
        x, y = max(0, round((origin.x-frame.left)*sx)), max(0, round((origin.y-frame.top)*sy))
        return x, y, min(width-x, round(client.right*sx)), min(height-y, round(client.bottom*sy))
