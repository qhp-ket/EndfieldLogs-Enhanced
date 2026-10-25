"""Real subprocess pipes must keep draining while JSON status stays open."""
import time
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
