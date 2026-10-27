"""Diagnostic paths retain their own message identity after framing extraction."""
from types import SimpleNamespace

import pytest

from endfield_pcap.capture.protocol import SessionBodyDecompressionError
from endfield_pcap.capture.registry import MessageDecodeFailure
from endfield_pcap.models import RuntimeMetrics
from endfield_pcap.service.session.framing import FramingEvents


class Framer(FramingEvents):
    def __init__(self, failure=None):
        self.session_id = 'synthetic'
        self.records = []
        self.on_debug_record = self.records.append
        self.metrics = RuntimeMetrics()
        self.reliability_flags = set()

        def decode(direction, head, body):
            if failure is not None:
                raise failure
            return ['decoded']

        self.registry = SimpleNamespace(resolve_class_name=lambda direction, msg_id: 'CS_PING', decode_messages=decode)


@pytest.mark.parametrize('message_id, expected_id', [(42, 42), (None, 0), ('123', 123)])
@pytest.mark.parametrize('compressed', [False, True])
def test_ignored_frame_diagnostics_keep_message_identity(message_id, expected_id, compressed):
    framer = Framer()
    head = {'msgid': message_id, 'is_compress': compressed}
    framer._record_ignored_frame('cs', head, b'bad', False, 1000)
    assert framer.records[-1]['type'] == 'debug_ignored_frame'
    assert all(record['msg_id'] == expected_id for record in framer.records)
    assert framer.records[-1]['body_hex'] == b'bad'.hex()
    assert framer.metrics.decompression_errors == int(compressed)


@pytest.mark.parametrize('kind', ['body', 'protobuf', 'merged'])
def test_failed_decode_reports_message_without_interrupting_session(kind):
    failure = {'body': None, 'protobuf': MessageDecodeFailure('synthetic decode failure'),
               'merged': SessionBodyDecompressionError('synthetic merged failure')}[kind]
    framer = Framer(failure)
    head = {'msgid': 123, 'is_compress': kind == 'body'}
    assert framer._decode_frame_body('cs', head, b'bad', False, 1000) is None
    assert framer.records[-1]['msg_id'] == 123
    assert framer.records[-1]['head'] == head
    assert framer.records[-1]['body_len'] == 3
    assert framer.records[-1]['type'] == ('debug_protobuf_error' if kind == 'protobuf' else 'debug_decompression_error')
    assert framer.metrics.protobuf_decode_errors == int(kind == 'protobuf')
    assert framer.metrics.decompression_errors == int(kind != 'protobuf')


def test_successful_decode_preserves_existing_result():
    framer = Framer()
    assert framer._decode_frame_body('cs', {'msgid': 123}, b'plain', False, 1000) == (['decoded'], b'plain')
    assert framer.records == []
