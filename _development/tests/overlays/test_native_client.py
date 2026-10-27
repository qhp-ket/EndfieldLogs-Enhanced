"""Exercise the standalone Python transport through an actual localhost socket."""
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

from websockets.sync.server import serve

from endfield_pcap.overlays.client import SnapshotClient


def message(sequence, stream='one', snapshot=None):
    return dict(type='analysis_summary', schema_version=1, stream_id=stream,
                sequence=sequence, snapshot=snapshot)


def wait(app, condition, phase, diagnostics, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        # qWait can hold the GIL while waiting in Qt, starving the Python
        # client/server threads this test needs to make progress.
        time.sleep(.01)
    assert condition(), f'native transport timed out: {phase}; {diagnostics()}'


def test_native_client_connects_reconnects_and_stops(app, caplog):
    caplog.set_level('DEBUG', logger='endfield_pcap.overlays.client')
    paths, progress = [], []
    disconnect = threading.Event()
    reconnect = threading.Event()
    release = threading.Event()

    def handler(socket):
        paths.append(socket.request.path)
        progress.append('connected')
        if len(paths) == 1:
            socket.send(json.dumps(message(20, snapshot={'battle': {'total_damage': 10}})))
            progress.append('first snapshot sent')
            disconnect.wait(8)
            socket.close()
            progress.append('first connection closed')
            return
        reconnect.wait(8)
        socket.send(json.dumps(message(0, 'two')))
        socket.send(json.dumps(message(1, 'two', {'battle': {'total_damage': 20}})))
        socket.send(json.dumps(message(999, 'one', {'battle': {'total_damage': 99}})))
        progress.append('reconnected snapshots sent')
        release.wait(8)

    with serve(handler, '127.0.0.1', 0) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        client = SnapshotClient(server.socket.getsockname()[1], 'test+/= token')
        received, states = [], []
        client.snapshot.connect(received.append)
        client.connectedChanged.connect(states.append)
        def diagnostics():
            return dict(connections=len(paths), progress=list(progress), states=list(states),
                        received=[(m['stream_id'], m['sequence']) for m in received],
                        client_alive=client._thread.is_alive(), server_alive=worker.is_alive())

        def until(condition, phase):
            wait(app, condition, phase, diagnostics)

        try:
            client.start()
            until(lambda: bool(received), 'first snapshot delivered to Qt')
            assert received[-1]['snapshot']['battle']['total_damage'] == 10
            assert states == [True]
            disconnect.set()
            until(lambda: False in states, 'disconnection delivered to Qt')
            until(lambda: len(paths) == 2, 'second connection established')
            reconnect.set()
            until(lambda: any(m['stream_id'] == 'two' and m['sequence'] == 1 for m in received),
                  'reconnected snapshot delivered to Qt')
            assert received[-1]['snapshot']['battle']['total_damage'] == 20
            assert states == [True, False, True]
            assert all(parse_qs(urlsplit(p).query)['access_token'] == ['test+/= token'] for p in paths)
            assert all(parse_qs(urlsplit(p).query)['analysis'] == ['summary'] for p in paths)
        finally:
            client.stop()
            disconnect.set()
            reconnect.set()
            release.set()
            try:
                until(lambda: not client._thread.is_alive(), 'client stopped')
            finally:
                server.shutdown()
                worker.join(2)
            assert not worker.is_alive(), diagnostics()


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
