import asyncio
from copy import deepcopy
import json

from endfield_pcap.buff_display import BuffDisplayPublisher
from endfield_pcap.models import ServiceObserver
from test_live_snapshot_publisher import service_factory


def start(uid="9007199254740993", buff="fixture", stamp="10:00:00.000", duration="unknown"):
    return f'[{stamp}] BUFF_START #1 id="{buff}" uid={uid} owner=chr_fixture src=chr_source dur={duration}'


def test_arbitrary_instances_replacement_enable_end_expiry_and_reset(tmp_path):
    now = [0.0]
    publisher = BuffDisplayPublisher(clock=lambda: now[0], data_root=tmp_path)
    for i in range(37):
        publisher.feed_line(start(str(9007199254740993 + i), duration="10"))
    first = publisher.current_message()
    assert len(first["snapshot"]["buffs"]) == 37
    assert first["snapshot"]["buffs"][0]["uid"] == "9007199254740993"
    assert publisher.current_message() == first
    now[0] = 2
    assert publisher.current_message()["snapshot"]["buffs"][0]["remaining_ms"] == 8000
    publisher.feed_line(start(stamp="10:00:02.000", duration="10"))
    assert publisher.current_message()["snapshot"]["buffs"][0]["remaining_ms"] == 8000
    publisher.feed_line('[10:00:02.000] BUFF_ENABLE {"buffUid":"9007199254740993","enabled":false}')
    assert publisher.current_message()["snapshot"]["buffs"][0]["status"] == "disabled"
    publisher.feed_line('[10:00:02.000] BUFF_END #3 uid=9007199254740993')
    assert len(publisher.current_message()["snapshot"]["buffs"]) == 36
    now[0] = 20
    assert publisher.current_message()["snapshot"]["buffs"][0]["status"] == "expired_estimate"
    publisher.feed_line('[10:00:22.000] GAME_TIMER_RESET source=test')
    cleared = publisher.current_message()
    assert cleared["snapshot"]["buffs"] == [] and cleared["sequence"] > first["sequence"]
    publisher.feed_line(start())
    assert publisher.current_message()["snapshot"]["buffs"][0]["duration_source"] == "unknown"
    publisher.reset(new_stream=True)
    assert publisher.current_message()["stream_id"] != first["stream_id"]


def test_duration_uses_typed_lifetime_and_explicit_blackboard_only(tmp_path):
    for name, life, config in [
        ("constant", "Limited", dict(useBlackboardKey=False, value=15)),
        ("blackboard", "Limited", dict(useBlackboardKey=True, blackboardKey="duration")),
        ("infinite", "Infinity", dict(useBlackboardKey=False, value=9999))]:
        (tmp_path / f"{name}.json").write_text(json.dumps(dict(lifeType=life, duration=config)))
    publisher = BuffDisplayPublisher(clock=lambda: 0, data_root=tmp_path)
    for i, name in enumerate(["constant", "blackboard", "infinite", "unresolved"]):
        publisher.feed_line(start(str(i + 1), name))
        publisher.feed_line(f'[10:00:00.000] BB[{i + 1}]: duration=8')
    rows = publisher.current_message()["snapshot"]["buffs"]
    assert [row["duration_ms"] for row in rows] == [15000, 8000, None, None]
    assert [row["status"] for row in rows] == ["timed", "timed", "indefinite", "unknown"]
    publisher.feed_line(start("5", duration="nan"))
    assert publisher.current_message()["snapshot"]["buffs"][-1]["duration_ms"] is None


def test_midnight_and_copy_isolation(tmp_path):
    publisher = BuffDisplayPublisher(clock=lambda: 0, data_root=tmp_path)
    publisher.feed_line(start(stamp="23:59:59.000", duration="10"))
    publisher.feed_line('[00:00:01.000] harmless=1')
    message = publisher.current_message()
    assert message["snapshot"]["buffs"][0]["remaining_ms"] == 8000
    message["snapshot"]["buffs"].clear()
    assert publisher.current_message()["snapshot"]["buffs"]


def test_service_buff_sink_observer_and_full_handshake(service_factory):
    async def scenario():
        observed = []
        service = service_factory(observer=ServiceObserver(on_buff_snapshot=observed.append))
        service.buff_publisher = BuffDisplayPublisher(clock=lambda: 0)
        service._handle_trace_line(start())
        await service._publish_buff_snapshot()
        assert len(observed[-1]["snapshot"]["buffs"]) == 1
        original = deepcopy(observed[-1])
        observed[-1]["snapshot"]["buffs"].clear()
        class Socket:
            def __init__(self): self.frames = []
            async def send(self, text): self.frames.append(json.loads(text))
            async def wait_closed(self): pass
        socket = Socket()
        await service._ws_handler(socket)
        assert [frame["type"] for frame in socket.frames] == ["hello", "analysis_snapshot", "buff_snapshot"]
        assert socket.frames[-1] == original
        service._handle_trace_line('[10:00:01.000] GAME_TIMER_RESET source=test')
        await service._publish_buff_snapshot()
        assert observed[-1]["snapshot"]["buffs"] == []
    asyncio.run(scenario())
