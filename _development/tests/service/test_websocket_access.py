"""Browser origins must not receive any battle evidence without a capability."""
import asyncio
import json
from types import SimpleNamespace
import pytest
import websockets
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus, ConnectionClosedError
from app_test_support.runtime.service import service_factory, FIXTURE
from endfield_pcap.service.runtime.access import browser_request_allowed
from endfield_pcap.models import ServiceObserver


@pytest.fixture(params=['asyncio', 'legacy'])
def serve_api(request):
    if request.param == 'legacy':
        from websockets.legacy.server import serve
    else:
        from websockets.asyncio.server import serve
    return serve


@pytest.mark.parametrize('origin', ['https://outside.invalid', 'null', 'http://127.0.0.1:9000'])
@pytest.mark.parametrize('path', ['/ws', '/ws?analysis=summary', '/ws?access_token=wrong',
    '/ws?access_token=%E4%B8%80', '/ws?access_token=' + 'A' * 43 + '&access_token=' + 'A' * 43])
def test_browser_rejected_before_handshake_and_without_starting_analysis(service_factory, serve_api, origin, path):
    async def run():
        service = service_factory()
        service.config.ws_browser_token = 'A' * 43
        before = (service._full_handshakes, service._summary_handshakes, service.summary_publisher._revision)
        async with serve_api(service._ws_handler, '127.0.0.1', 0,
                                    process_request=service._ws_process_request) as server:
            port = server.sockets[0].getsockname()[1]
            with pytest.raises(InvalidStatus) as error:
                async with websockets.connect(f'ws://127.0.0.1:{port}{path}', origin=origin):
                    pytest.fail('An untrusted browser completed the handshake')
            assert error.value.response.status_code == 403
        assert not service.clients and not service._client_senders
        assert (service._full_handshakes, service._summary_handshakes, service.summary_publisher._revision) == before
        assert service.summary_publisher._worker is None and service.snapshot_publisher._worker is None
    asyncio.run(run())


@pytest.mark.parametrize('origin,query', [(None, ''), ('null', '&access_token=' + 'A' * 43),
                                       ('https://trusted.invalid', '&access_token=' + 'A' * 43)])
def test_native_and_explicitly_authorized_browser_receive_current_state(service_factory, serve_api, origin, query):
    async def run():
        service = service_factory(observer=ServiceObserver(on_analysis_summary=lambda message: None))
        service.config.ws_browser_token = 'A' * 43
        await service._publish_analysis_summary()
        for line in FIXTURE.splitlines(keepends=True):
            service._handle_trace_line(line)
        await service._publish_analysis_summary()
        expected = service.summary_publisher.current_message()
        assert expected['snapshot']['battle']['total_damage'] == 760
        async with serve_api(service._ws_handler, '127.0.0.1', 0,
                                    process_request=service._ws_process_request) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f'ws://127.0.0.1:{port}/ws?analysis=summary{query}', origin=origin) as socket:
                frames = [json.loads(await asyncio.wait_for(socket.recv(), 3)) for _ in range(2)]
                assert [f['type'] for f in frames] == ['hello', 'analysis_summary']
                assert frames[1] == expected
    asyncio.run(run())


def test_embedded_handler_also_closes_before_hello(service_factory, serve_api):
    async def run():
        service = service_factory()
        async with serve_api(service._ws_handler, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f'ws://127.0.0.1:{port}/ws', origin='https://outside.invalid') as socket:
                with pytest.raises(ConnectionClosedError) as error:
                    await asyncio.wait_for(socket.recv(), 2)
                assert error.value.rcvd.code == 1008
        assert not service.clients and service._full_handshakes == service._summary_handshakes == 0
    asyncio.run(run())


def test_duplicate_origin_is_rejected_even_with_valid_capability():
    request = SimpleNamespace(headers=Headers([('Origin', 'null'), ('Origin', 'https://outside.invalid')]),
                              path='/ws?access_token=' + 'A' * 43)
    assert not browser_request_allowed(request, 'A' * 43)


@pytest.mark.parametrize('client_request', [None, object(), SimpleNamespace(path='/ws'),
                                    SimpleNamespace(headers=None, path='/ws')])
def test_unknown_request_structure_is_rejected(client_request):
    assert not browser_request_allowed(client_request, 'A' * 43)


def test_legacy_header_check_uses_explicit_path_and_rejects_blank_duplicate():
    headers = Headers([('Origin', 'null')])
    token = 'A' * 43
    assert not browser_request_allowed(headers, token)
    assert browser_request_allowed(headers, token, path='/ws?access_token=' + token)
    assert not browser_request_allowed(headers, token, path='/ws?access_token=&access_token=' + token)


def test_handler_with_unknown_request_closes_before_sending_or_starting_analysis(service_factory):
    async def run():
        service = service_factory()
        closed = []
        async def close(**kwargs):
            closed.append(kwargs)
        await service._ws_handler(SimpleNamespace(close=close))
        assert closed == [{'code': 1008, 'reason': 'Browser access denied'}]
        assert not service.clients and service._full_handshakes == service._summary_handshakes == 0
    asyncio.run(run())
