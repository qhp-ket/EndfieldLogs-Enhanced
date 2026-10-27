"""Native localhost summary client, with one queued notification per batch."""
import json
import logging
import threading
from PySide6.QtCore import QObject, Signal, Qt, Slot

LOGGER = logging.getLogger(__name__)


class SnapshotClient(QObject):
    snapshot = Signal(object)
    connectedChanged = Signal(bool)
    _wake = Signal()

    def __init__(self, port, token='', parent=None):
        super().__init__(parent)
        self.url = f'ws://127.0.0.1:{int(port)}/ws?analysis=summary'
        if token:
            from urllib.parse import quote
            self.url += '&access_token='+quote(token, safe='')
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending = {}
        self._thread = None
        from .native.model import SnapshotGate
        self._gates = {'analysis_summary': SnapshotGate(), 'combo_snapshot': SnapshotGate()}
        self._wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)

    def start(self):
        if self._thread is not None: return
        self._thread = threading.Thread(target=self._run, name='overlay-summary', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _post(self, kind, value):
        if kind in self._gates and not self._gates[kind].accept(value, {kind}, 2 if kind == 'combo_snapshot' else 1):
            return
        with self._lock:
            wake = not self._pending
            self._pending[kind] = value
        if wake and not self._stop.is_set():
            self._wake.emit()

    @Slot()
    def _drain(self):
        with self._lock:
            pending, self._pending = self._pending, {}
        if self._stop.is_set(): return
        if 'connection' in pending:
            self.connectedChanged.emit(pending.pop('connection'))
        for message in pending.values():
            self.snapshot.emit(message)

    def _run(self):
        from websockets.sync.client import connect
        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=2, close_timeout=.2, max_size=1024*1024,
                             max_queue=4, proxy=None) as socket:
                    self._post('connection', True)
                    while not self._stop.is_set():
                        try:
                            raw = socket.recv(timeout=.25)
                        except TimeoutError:
                            continue
                        message = json.loads(raw)
                        if isinstance(message, dict) and message.get('type') in {'analysis_summary', 'combo_snapshot'}:
                            self._post(message['type'], message)
            except Exception as exc:
                if not self._stop.is_set(): LOGGER.debug('浮窗连接中断：%s', exc)
            self._post('connection', False)
            self._stop.wait(1.5)
