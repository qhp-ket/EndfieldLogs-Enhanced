from collections import Counter, defaultdict
from parser_core.live_copy import isolated_copy, changed_records, copy_ingestion_state
from parser_core.incremental import AllocationFrontier


def test_isolation_preserves_aliases_cycles_defaults_and_counter_values():
    child={'nested': []}
    source={'a': child,'b':child,'counts':Counter({'x':3}), 'defaults':defaultdict(lambda: [], {'x':[1]})}
    source['cycle']=source
    result=isolated_copy(source)
    assert result['a'] is result['b'] and result['a'] is not child
    assert result['cycle'] is result
    assert result['counts']==Counter(x=3)
    assert result['defaults']['missing']==[]
    result['a']['nested'].append(1)
    assert child['nested']==[] and 'missing' not in source['defaults']


def test_native_state_copy_preserves_isolation_aliases_and_local_factories():
    child={'x':[]}
    state={'first':child,'second':child,'defaults':defaultdict(lambda: [], {'a': child}), 'counts':Counter(x=3)}
    result=copy_ingestion_state(state)
    assert result['first'] is result['second'] is result['defaults']['a']
    assert result['first'] is not child
    assert result['counts']==Counter(x=3)
    result['defaults']['new'].append(1)
    assert 'new' not in state['defaults']


def test_dependency_copy_reuses_only_detached_unchanged_rows():
    source=[{'id':1,'state':[]},{'id':2,'state':[]}]
    before=changed_records([],source)
    source[1]['state'].append(2)
    after=changed_records(before,source)
    assert after[0] is before[0] and after[1] is not before[1]
    assert before[1]['state']==[]
    source[1]['state'].append(3)
    assert after[1]['state']==[2]


def test_corrected_contributions_retract_totals_and_maxima_in_canonical_order():
    cache=AllocationFrontier()
    hits=[{'rdps_contributions': {'a':10., 'b':2.}}, {'rdps_contributions': {'a':30., 'b':5.}}]
    assert cache.contribution_totals(hits)=={'a':40.,'b':7.}
    assert cache.maxima_prefix[-1]=={'a':30.,'b':5.}
    hits[1]['rdps_contributions']={'a':3.,'b':32.}
    assert cache.contribution_totals(hits)=={'a':13.,'b':34.}
    assert cache.maxima_prefix[-1]=={'a':10.,'b':32.}
    assert cache.contribution_totals(hits[:1])=={'a':10.,'b':2.}
    assert cache.maxima_prefix[-1]=={'a':10.,'b':2.}
