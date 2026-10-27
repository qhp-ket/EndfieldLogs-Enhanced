"""Input display owns bindings and rejects superseded/closed background results."""
from copy import deepcopy
from types import SimpleNamespace
import threading

import pytest

from endfield_pcap.application.input_evidence import InputEvidenceController
from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.history.index import record_key
from endfield_pcap.settings import load_app_config


class GatedEvidence:
    """Real workers finish in an explicitly chosen order, without timed sleeps."""
    def __init__(self):
        self.entered = {name: threading.Event() for name in ('a', 'b')}
        self.release = {name: threading.Event() for name in ('a', 'b')}
        self.threads = {}
        self.arguments = {}

    def __call__(self, paths, trace, battle, settings, **alignment):
        name = paths[0].stem
        self.threads[name] = threading.current_thread()
        self.arguments[name] = (trace, battle, settings, alignment)
        self.entered[name].set()
        assert self.release[name].wait(5), 'test did not release the evidence worker'
        return dict(actions=[dict(action='skill', start_ms=10 if name == 'a' else 20)],
                    raw=[], warnings=[], paths=[str(paths[0])])

    def finish(self, name):
        assert self.entered[name].wait(2), f'{name} worker did not enter'
        self.release[name].set()
        self.threads[name].join(2)
        assert not self.threads[name].is_alive()

    def cleanup(self):
        for event in self.release.values():
            event.set()
        for thread in self.threads.values():
            thread.join(2)


def setup_controller(tmp_path, loader):
    path = tmp_path/'settings.json'
    store = SettingsStore(load_app_config(path), path)
    record = SimpleNamespace(file_path=tmp_path/'battle.log', record_index=2, started_at_ms=100)
    snapshot = dict(battle=dict(duration_ms=1000), participants=[dict(character_key='actor')])
    controller = InputEvidenceController(snapshot['battle'], store, loader=loader)
    controller.set_record(record)
    return controller, store, record, snapshot


def test_new_binding_wins_even_when_previous_worker_finishes_later(tmp_path):
    loader = GatedEvidence()
    controller, store, record, snapshot = setup_controller(tmp_path, loader)
    before = deepcopy(snapshot)
    try:
        controller.bind(tmp_path/'a.jsonl')
        assert loader.entered['a'].wait(2)
        controller.bind(tmp_path/'b.jsonl')
        loader.finish('b')
        # A completed worker has not changed state before the owner drains it.
        assert controller.state.pending and not controller.state.evidence['actions']
        assert controller.drain()
        evidence = controller.state.evidence
        assert evidence['actions'] == [dict(action='skill', start_ms=20)]
        loader.finish('a')
        assert not controller.drain()
        assert controller.state.evidence is evidence
        assert controller.state.paths == (tmp_path/'b.jsonl',)
        assert load_app_config(store.path).input_log_bindings[record_key(record)]['path'] == 'b.jsonl'
        assert snapshot == before
    finally:
        controller.close()
        loader.cleanup()


@pytest.mark.parametrize('invalidate', ['unbind', 'record', 'close'])
@pytest.mark.parametrize('already_completed', [False, True])
def test_late_input_result_does_not_restore_invalidated_evidence(tmp_path, invalidate, already_completed):
    loader = GatedEvidence()
    controller, _, _, _ = setup_controller(tmp_path, loader)
    try:
        controller.bind(tmp_path/'a.jsonl')
        assert loader.entered['a'].wait(2)
        if already_completed:
            loader.finish('a')
        if invalidate == 'unbind':
            controller.unbind()
        elif invalidate == 'record':
            controller.set_record(SimpleNamespace(file_path=tmp_path/'next.log', record_index=1, started_at_ms=200))
        else:
            controller.close()
        loader.finish('a')
        assert not controller.drain()
        assert not controller.state.pending and not controller.state.evidence['actions']
        if invalidate != 'close':
            assert not controller.state.paths
    finally:
        controller.close()
        loader.cleanup()


def test_alignment_and_filter_are_display_inputs_and_failure_is_diagnostic(tmp_path):
    calls = []
    workers = []
    entered = threading.Condition()

    def fail(paths, trace, battle, settings, **alignment):
        with entered:
            workers.append(threading.current_thread())
            entered.notify()
        calls.append((deepcopy(battle), deepcopy(settings), deepcopy(alignment)))
        battle['duration_ms'] = 999
        raise ValueError('fixture input unavailable')

    controller, store, record, snapshot = setup_controller(tmp_path, fail)
    before = deepcopy(snapshot)
    controller.bind(tmp_path/'a.jsonl')
    # Wait for actual task completion before committing results.
    with entered:
        assert entered.wait_for(lambda: len(workers) >= 1, timeout=2)
    workers[0].join(2)
    controller.drain()
    assert controller.state.error == 'fixture input unavailable'
    assert not controller.state.pending
    controller.set_alignment(offset_ms=25., start_override=123., manual_slots={1: 'actor'})
    with entered:
        assert entered.wait_for(lambda: len(workers) >= 2, timeout=2)
    workers[1].join(2)
    controller.drain()
    assert calls[1][0] == before['battle']
    assert calls[1][2] == dict(offset_ms=25., start_override=123., manual_slots={1: 'actor'}, verify=False)
    controller.set_settings({'show_other': True})
    with entered:
        assert entered.wait_for(lambda: len(workers) >= 3, timeout=2)
    workers[2].join(2)
    controller.drain()
    assert calls[2][1]['show_other'] is True
    assert load_app_config(store.path).input_settings['show_other'] is True
    controller.set_visible(True)
    assert store.current.input_log_bindings[record_key(record)]['visible'] is True
    assert snapshot == before
    controller.close()
