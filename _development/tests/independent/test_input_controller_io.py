"""Real subprocess pipes must keep draining while JSON status stays open."""
import time
import subprocess
from types import SimpleNamespace
import pytest
from endfield_pcap.inputlog import controller


@pytest.mark.parametrize('exit_code', [0, 7])
def test_stderr_flood_cannot_block_status_or_graceful_stop(tmp_path, monkeypatch, exit_code):
    code = f'''import json,sys
sys.stderr.write('diagnostic-start' + 'x'*2_000_000 + 'diagnostic-end')
sys.stderr.flush()
print(json.dumps(dict(status='waiting_game',count=0,lost=0)),flush=True)
for line in sys.stdin:
    if json.loads(line).get('command')=='stop': break
sys.exit({exit_code})
'''
    monkeypatch.setattr(controller, 'worker_bootstrap', lambda: code)
    inputs = controller.InputController()
    try:
        inputs.start(tmp_path/'missing.exe', tmp_path)
        deadline = time.monotonic()+8
        while inputs.snapshot()['status']=='starting' and time.monotonic()<deadline:
            time.sleep(.01)
        assert inputs.snapshot()['status']=='waiting_game'
        inputs.stop(wait=True)
        deadline = time.monotonic()+3
        while inputs.snapshot()['status']=='waiting_game' and time.monotonic()<deadline:
            time.sleep(.01)
        state = inputs.snapshot()
        assert state['status']==('error' if exit_code else 'stopped')
        if exit_code:
            assert len(state['error'])<=1500 and state['error'].endswith('diagnostic-end')
            assert 'diagnostic-start' not in state['error']
        assert not inputs.running
    finally:
        inputs.stop(wait=True)


@pytest.mark.parametrize('failure', ['timeout', 'terminate', 'kill', 'wait'])
def test_stop_cleanup_failures_are_bounded_and_reported_without_raising(failure, caplog):
    calls = []
    def signal(name):
        calls.append(name)
        if failure == name:
            raise PermissionError('synthetic access denied')
    def wait(timeout):
        calls.append(timeout)
        if failure == 'wait':
            raise OSError('synthetic wait failure')
        raise subprocess.TimeoutExpired('input-worker', timeout)
    inputs = controller.InputController()
    inputs.process = SimpleNamespace(pid=123, poll=lambda: None, wait=wait,
        terminate=lambda: signal('terminate'), kill=lambda: signal('kill'))
    commands = []
    inputs.command = lambda **payload: commands.append(payload)
    inputs.stop(wait=True)
    assert commands == [dict(command='stop')]
    assert calls == [8, 'terminate', *([] if failure == 'terminate' else [3]),
                     'kill', *([] if failure == 'kill' else [1])]
    assert inputs.snapshot()['status'] == 'error'
    assert '123' in caplog.text and '退出失败' in caplog.text


def test_stop_escalates_once_then_reaps_process():
    calls = []
    def wait(timeout):
        calls.append(timeout)
        if timeout == 8:
            raise subprocess.TimeoutExpired('input-worker', timeout)
    inputs = controller.InputController()
    inputs.command = lambda **payload: calls.append(payload['command'])
    inputs.process = SimpleNamespace(poll=lambda: None, wait=wait,
        terminate=lambda: calls.append('terminate'),
        kill=lambda: pytest.fail('already reaped'))
    inputs.stop(wait=True)
    assert calls == ['stop', 8, 'terminate', 3]
