from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import sys
from ctypes import POINTER, Structure, WinDLL, byref, c_char, c_void_p, cast, create_string_buffer
from ctypes.wintypes import BOOL, DWORD
from pathlib import Path


class _DataBlob(Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_char))]


class SessionStore:
    def __init__(self) -> None:
        appdata_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".endfield-pcap")
        self._session_path = appdata_root / "EndfieldPCAP" / "session.json"
        self._legacy_session_path = appdata_root / "EndfieldLogsUploader" / "session.json"
        self._migrate_legacy_session()

    def _migrate_legacy_session(self) -> None:
        if self._session_path.exists() or not self._legacy_session_path.exists():
            return
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self._legacy_session_path, self._session_path)
        except OSError:
            pass

    @staticmethod
    def _protect_token(token: str) -> str:
        if sys.platform != "win32":
            return token

        data = token.encode("utf-8")
        # Keep the input buffer alive until CryptProtectData returns. Building the
        # pointer from a temporary ctypes array worked in the interpreter by
        # accident, but the frozen uploader could release that array before the
        # Windows API consumed it and fail immediately after a successful login.
        input_buffer = create_string_buffer(data)
        in_blob = _DataBlob(len(data), cast(input_buffer, POINTER(c_char)))
        out_blob = _DataBlob()
        crypt32 = WinDLL("crypt32.dll", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            POINTER(_DataBlob),
            c_void_p,
            POINTER(_DataBlob),
            c_void_p,
            c_void_p,
            DWORD,
            POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = BOOL
        kernel32 = WinDLL("kernel32.dll", use_last_error=True)
        kernel32.LocalFree.argtypes = [c_void_p]
        kernel32.LocalFree.restype = c_void_p
        if not crypt32.CryptProtectData(byref(in_blob), None, None, None, None, 0, byref(out_blob)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            encrypted = cast(out_blob.pbData, POINTER(c_char * out_blob.cbData)).contents.raw
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            kernel32.LocalFree(cast(out_blob.pbData, c_void_p))

    @staticmethod
    def _unprotect_token(protected_token: str) -> str | None:
        if sys.platform != "win32":
            return protected_token

        try:
            encrypted = base64.b64decode(protected_token.encode("ascii"))
        except (ValueError, OSError):
            return None
        input_buffer = create_string_buffer(encrypted)
        in_blob = _DataBlob(
            len(encrypted),
            cast(input_buffer, POINTER(c_char)),
        )
        out_blob = _DataBlob()
        crypt32 = WinDLL("crypt32.dll", use_last_error=True)
        crypt32.CryptUnprotectData.argtypes = [
            POINTER(_DataBlob),
            c_void_p,
            POINTER(_DataBlob),
            c_void_p,
            c_void_p,
            DWORD,
            POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = BOOL
        kernel32 = WinDLL("kernel32.dll", use_last_error=True)
        kernel32.LocalFree.argtypes = [c_void_p]
        kernel32.LocalFree.restype = c_void_p
        if not crypt32.CryptUnprotectData(byref(in_blob), None, None, None, None, 0, byref(out_blob)):
            return None
        try:
            decrypted = cast(out_blob.pbData, POINTER(c_char * out_blob.cbData)).contents.raw
            return decrypted.decode("utf-8")
        finally:
            kernel32.LocalFree(cast(out_blob.pbData, c_void_p))

    def _read_payload(self) -> dict:
        if not self._session_path.exists():
            return {}
        try:
            return json.loads(self._session_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_payload(self, payload: dict) -> None:
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        self._session_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalized_payload(self, payload: dict) -> dict | None:
        session_token = payload.get("sessionToken")
        protected_token = payload.get("sessionTokenProtected")

        if not session_token and protected_token:
            session_token = self._unprotect_token(str(protected_token))
        if not session_token:
            return None

        normalized = dict(payload)
        normalized["sessionToken"] = str(session_token)
        return normalized

    def load_token(self) -> str | None:
        payload = self._normalized_payload(self._read_payload())
        if payload is None:
            return None
        return str(payload["sessionToken"])

    def load_session(self) -> dict | None:
        return self._normalized_payload(self._read_payload())

    def save_token(self, token: str) -> None:
        payload = self._read_payload()
        payload.pop("sessionToken", None)
        payload["sessionTokenProtected"] = self._protect_token(token)
        self._write_payload(payload)

    def save_session(self, session_payload: dict) -> None:
        payload = dict(session_payload)
        token = str(payload.pop("sessionToken", "") or "")
        if token:
            payload["sessionTokenProtected"] = self._protect_token(token)
        self._write_payload(payload)

    def clear(self) -> None:
        if self._session_path.exists():
            self._session_path.unlink()
        if self._legacy_session_path.exists():
            self._legacy_session_path.unlink()
