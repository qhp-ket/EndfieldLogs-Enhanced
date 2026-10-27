"""Deterministic skill-type lanes; expansion changes geometry, never events."""
from dataclasses import dataclass
from endfield_pcap.analysis.battle.lane_config import resolved_lanes, skill_key


CATEGORY_ORDER = ('重击', '战技', '连携', '大招', '其他')
CATEGORY_NAMES = {'大招': '终结'}


@dataclass
class SkillLane:
    character: str
    category: str
    placements: list
    rows: int
    name: str = ''
    categories: tuple = ()


def skill_lanes(blocks, characters, expanded, x_at, minimum_width, bounds=None, lane_configs=None):
    bounds = bounds or (lambda block: (block.start_ms, block.end_ms))
    groups = {}
    for block in blocks:
        if block.lane == 'skill':
            groups.setdefault(block.character_key, []).append(block)
    # Include evidenced actors omitted from the participant summary as well.
    owners = list(dict.fromkeys([*characters, *groups]))
    result = []
    for owner in owners:
        owner_blocks = groups.get(owner, [])
        for lane in resolved_lanes(owner_blocks, owner, (lane_configs or {}).get(owner)):
            category = lane['id']
            members = set(lane['skills'])
            group = [block for block in owner_blocks if skill_key(block) in members]
            if not group:
                continue
            edges, placements = [], []
            for block in sorted(group, key=lambda b: bounds(b)[0]):
                start_ms, end_ms = bounds(block)
                start = x_at(start_ms)
                end = max(x_at(end_ms), start + minimum_width)
                row = next((i for i, edge in enumerate(edges) if edge + 2 <= start), len(edges)) if (owner, category) in expanded else 0
                if row == len(edges):
                    edges.append(end)
                else:
                    edges[row] = max(edges[row], end)
                placements.append((block, row, start, end))
            result.append(SkillLane(owner, category, placements, max(1, len(edges)), lane['name'],
                                    tuple(dict.fromkeys(block.category for block in group))))
    return result
