"""Exercise the standalone Python transport through an actual localhost socket."""
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

from PySide6.QtTest import QTest
from websockets.sync.server import serve

from endfield_pcap.overlays.client import SnapshotClient


def message(sequence, stream='one', snapshot=None):
    return dict(type='analysis_summary', schema_version=1, stream_id=stream,
                sequence=sequence, snapshot=snapshot)


def wait(condition, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QTest.qWait(10)
        if condition():
            return
    assert condition(), 'native transport timed out'


def test_native_client_connects_reconnects_and_stops(app):
    attempts, paths = [], []
    release = threading.Event()

    def handler(socket):
        paths.append(socket.request.path)
        attempts.append(1)
        if len(attempts) == 1:
            socket.send(json.dumps(message(20, snapshot={'battle': {'total_damage': 10}})))
            socket.close()
            return
        socket.send(json.dumps(message(0, 'two')))
        socket.send(json.dumps(message(1, 'two', {'battle': {'total_damage': 20}})))
        socket.send(json.dumps(message(999, 'one', {'battle': {'total_damage': 99}})))
        release.wait(8)

    with serve(handler, '127.0.0.1', 0) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        client = SnapshotClient(server.socket.getsockname()[1], 'test+/= token')
        received, states = [], []
        client.snapshot.connect(received.append)
        client.connectedChanged.connect(states.append)
        try:
            client.start()
            wait(lambda: any(m['stream_id'] == 'two' and m['sequence'] == 1 for m in received))
            assert received[-1]['snapshot']['battle']['total_damage'] == 20
            assert True in states and False in states
            assert all(parse_qs(urlsplit(p).query)['access_token'] == ['test+/= token'] for p in paths)
            assert all(parse_qs(urlsplit(p).query)['analysis'] == ['summary'] for p in paths)
        finally:
            client.stop()
            release.set()
            wait(lambda: not client._thread.is_alive())
            server.shutdown()
            worker.join(2)


def test_native_queue_coalesces_before_gui_drain_and_rejects_retired_streams(app):
    client = SnapshotClient(1)
    received = []
    client.snapshot.connect(received.append)
    for sequence in range(5000):
        client._post('analysis_summary', message(sequence))
    assert len(client._pending) == 1
    client._post('analysis_summary', message(0, 'two'))
    client._post('analysis_summary', message(10000, 'one'))
    client._post('analysis_summary', message(0, 'two'))
    app.processEvents()
    assert received == [message(0, 'two')]
    client._post('analysis_summary', message(1, 'two'))
    client.stop()
    app.processEvents()
    assert received == [message(0, 'two')]
