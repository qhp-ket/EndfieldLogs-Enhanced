from __future__ import annotations

import ctypes
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from ctypes import wintypes


WM_HOTKEY = 0x0312

MOD_ALT = 0x0001

MOD_CONTROL = 0x0002

MOD_SHIFT = 0x0004

MOD_WIN = 0x0008

MOD_NOREPEAT = 0x4000

GLOBAL_HOTKEY_ID = 0xB100

USER32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None

def _qt_key_to_vk(key: Qt.Key) -> int | None:
    key_value = int(key)
    if int(Qt.Key.Key_0) <= key_value <= int(Qt.Key.Key_9):
        return key_value
    if int(Qt.Key.Key_A) <= key_value <= int(Qt.Key.Key_Z):
        return key_value
    if int(Qt.Key.Key_F1) <= key_value <= int(Qt.Key.Key_F24):
        return 0x70 + (key_value - int(Qt.Key.Key_F1))
    explicit_map = {
        int(Qt.Key.Key_Space): 0x20,
        int(Qt.Key.Key_Tab): 0x09,
        int(Qt.Key.Key_Backspace): 0x08,
        int(Qt.Key.Key_Return): 0x0D,
        int(Qt.Key.Key_Enter): 0x0D,
        int(Qt.Key.Key_Escape): 0x1B,
        int(Qt.Key.Key_Left): 0x25,
        int(Qt.Key.Key_Up): 0x26,
        int(Qt.Key.Key_Right): 0x27,
        int(Qt.Key.Key_Down): 0x28,
        int(Qt.Key.Key_Home): 0x24,
        int(Qt.Key.Key_End): 0x23,
        int(Qt.Key.Key_PageUp): 0x21,
        int(Qt.Key.Key_PageDown): 0x22,
        int(Qt.Key.Key_Insert): 0x2D,
        int(Qt.Key.Key_Delete): 0x2E,
        int(Qt.Key.Key_Minus): 0xBD,
        int(Qt.Key.Key_Equal): 0xBB,
        int(Qt.Key.Key_Comma): 0xBC,
        int(Qt.Key.Key_Period): 0xBE,
        int(Qt.Key.Key_Slash): 0xBF,
        int(Qt.Key.Key_Semicolon): 0xBA,
        int(Qt.Key.Key_Apostrophe): 0xDE,
        int(Qt.Key.Key_BracketLeft): 0xDB,
        int(Qt.Key.Key_BracketRight): 0xDD,
        int(Qt.Key.Key_Backslash): 0xDC,
        int(Qt.Key.Key_QuoteLeft): 0xC0,
    }
    return explicit_map.get(key_value)

def _portable_hotkey_to_native(hotkey: str) -> tuple[int, int] | None:
    sequence = QKeySequence(hotkey or "")
    combo = sequence[0]
    if combo.key() == Qt.Key.Key_unknown:
        return None
    modifiers = 0
    if combo.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
        modifiers |= MOD_CONTROL
    if combo.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        modifiers |= MOD_ALT
    if combo.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
        modifiers |= MOD_SHIFT
    if combo.keyboardModifiers() & Qt.KeyboardModifier.MetaModifier:
        modifiers |= MOD_WIN
    vk = _qt_key_to_vk(combo.key())
    if vk is None:
        return None
    return modifiers, vk


class OverlayHotkeys:
    def _update_overlay_shortcut(self, hotkey: str | None = None) -> bool:
        target_hotkey = hotkey or self.app_config.toggle_overlays_hotkey or "Ctrl+O"
        if sys.platform != "win32" or USER32 is None:
            self.settings_page.set_hotkey_status("当前平台不支持全局热键", is_error=True)
            return False
        native = _portable_hotkey_to_native(target_hotkey)
        if native is None:
            self.settings_page.set_hotkey_status("快捷键格式无效，请换一个组合键", is_error=True)
            return False
        hwnd = int(self.winId())
        previous_hotkey = self._registered_hotkey
        if self._global_hotkey_registered:
            USER32.UnregisterHotKey(hwnd, GLOBAL_HOTKEY_ID)
            self._global_hotkey_registered = False
        modifiers, vk = native
        if USER32.RegisterHotKey(hwnd, GLOBAL_HOTKEY_ID, modifiers | MOD_NOREPEAT, vk):
            self._global_hotkey_registered = True
            self._registered_hotkey = target_hotkey
            self.settings_page.set_hotkey_status(f"全局热键设定成功：{target_hotkey}")
            return True
        if previous_hotkey:
            previous_native = _portable_hotkey_to_native(previous_hotkey)
            if previous_native is not None:
                prev_modifiers, prev_vk = previous_native
                if USER32.RegisterHotKey(hwnd, GLOBAL_HOTKEY_ID, prev_modifiers | MOD_NOREPEAT, prev_vk):
                    self._global_hotkey_registered = True
                    self._registered_hotkey = previous_hotkey
        self.settings_page.set_hotkey_status(f"快捷键冲突：{target_hotkey}", is_error=True)
        return False

    def _unregister_overlay_hotkey(self) -> None:
        if sys.platform != "win32" or USER32 is None or not self._global_hotkey_registered:
            return
        USER32.UnregisterHotKey(int(self.winId()), GLOBAL_HOTKEY_ID)
        self._global_hotkey_registered = False

    def nativeEvent(self, eventType, message):  # noqa: N802
        if sys.platform == "win32" and USER32 is not None:
            event_type = bytes(eventType).decode(errors="ignore")
            if event_type in {"windows_generic_MSG", "windows_dispatcher_MSG"}:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and int(msg.wParam) == GLOBAL_HOTKEY_ID:
                    self._toggle_overlay_visibility()
                    return True, 0
        return super().nativeEvent(eventType, message)
