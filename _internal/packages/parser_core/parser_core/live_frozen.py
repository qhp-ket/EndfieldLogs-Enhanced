"""Detached immutable hit evidence, shared only between private projections."""
from copy import deepcopy


class FrozenMutation(RuntimeError):
    pass


def _reject(*args, **kwargs):
    raise FrozenMutation('attempt to mutate detached hit evidence')


class FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _reject

    def __deepcopy__(self, memo):
        return self  # immutable, detached from ingestion


class FrozenList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = sort = reverse = __iadd__ = __imul__ = _reject

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if type(value) is dict:
        return FrozenDict({key:freeze(item) for key,item in value.items()})
    if type(value) is list:
        return FrozenList(freeze(item) for item in value)
    if type(value) is tuple:
        return tuple(freeze(item) for item in value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    # Evidence fields are JSON-shaped. New mutable types require review, then
    # use the independent native-copy recovery path instead of unsafe sharing.
    raise FrozenMutation('unsupported mutable hit evidence type')


class FrozenHitEvidence:
    ROWS = 'hits'
    FIELDS = {'packet_attr_details', 'packet_modifier_uids', 'damage_calculation',
              'critical_observation', 'dpd_raw', 'attacker_stats_attrs',
              'attacker_stats_basic_attrs', 'target_resistance_points', 'target_resistance_scalars'}

    def __init__(self):
        self.records = {}

    def prepare(self, state):
        slim_hits, evidence, current = [], [], {}
        for index, hit in enumerate(state[self.ROWS]):
            fields = {}
            for field in self.FIELDS.intersection(hit):
                key = (index, hit.get('line_no'), field)
                old = self.records.get(key)
                value = old if old == hit[field] else freeze(hit[field])
                fields[field] = current[key] = value
            slim_hits.append({key:value for key,value in hit.items() if key not in fields})
            evidence.append(fields)
        self.records = current
        return {**state, self.ROWS:slim_hits}, evidence


class FrozenBuffEvidence(FrozenHitEvidence):
    ROWS = 'buff_starts'
    # Creation/origin proofs are only read by report finalization. Ingestion
    # may extend them; exact content comparison then replaces the detached copy.
    FIELDS = {'creation_observations', 'origin_observations'}
