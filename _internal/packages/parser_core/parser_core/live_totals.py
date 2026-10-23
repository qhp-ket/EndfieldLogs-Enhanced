"""Retractable integer damage/crit totals and canonical visual-hit maxima."""
from collections import Counter, defaultdict


class LiveDamageTotals:
    def __init__(self):
        self.rows = []
        self.totals = defaultdict(Counter)
        self.values = defaultdict(Counter)
        self.enemies = Counter()
        self.groups = defaultdict(dict)
        self.visual_maxima = {}
        self.updated_hits = self.reused_hits = 0

    @staticmethod
    def signature(hit):
        return (str(hit.get('character_key') or ''), hit.get('character_name'),
                str(hit.get('target_enemy_key') or ''), int(hit.get('hit_value') or 0),
                int(hit.get('crit_flag') or 0), str(hit.get('skill_key') or ''),
                int(hit.get('ts_ms') or 0))

    def _apply(self, index, row, sign, changed):
        character, _, enemy, value, crit, skill, stamp = row
        if not character:
            return
        totals = self.totals[character]
        totals['total_damage'] += sign*value
        totals['hit_count'] += sign
        totals['crit_hits'] += sign*bool(crit)
        values = self.values[character]
        values[value] += sign
        if values[value] == 0:
            del values[value]
        if enemy:
            self.enemies[enemy] += sign
            if self.enemies[enemy] == 0:
                del self.enemies[enemy]
        group = (character, enemy, skill)
        changed.add(group)
        if sign > 0:
            self.groups[group][index] = (stamp, value)
        else:
            del self.groups[group][index]

    def project(self, hits, buffs):
        from . import battle_log_parser as core
        rows = [self.signature(hit) for hit in hits]
        common = 0
        for old, new in zip(self.rows, rows):
            if old != new:
                break
            common += 1
        changed = set()
        for index in range(len(self.rows)-1, common-1, -1):
            self._apply(index, self.rows[index], -1, changed)
        for index in range(common, len(rows)):
            self._apply(index, rows[index], 1, changed)
        self.rows = rows
        self.updated_hits, self.reused_hits = len(rows)-common, common
        for group in changed:
            best = running = 0
            last = None
            # Canonical sorting is stable at equal timestamps; original input
            # index is the tie-breaker within this character/target/skill group.
            for _, (stamp, value) in sorted(self.groups[group].items(), key=lambda pair: (pair[1][0], pair[0])):
                running = value if last is None or stamp-last > core._VISUAL_HIT_GROUP_WINDOW_MS else running+value
                last = stamp
                best = max(best, running)
            self.visual_maxima[group] = best
            if not self.groups[group]:
                del self.groups[group]
                del self.visual_maxima[group]
        visual = defaultdict(int)
        for (character, _, _), maximum in self.visual_maxima.items():
            visual[character] = max(visual[character], maximum)
        participants = core._new_participant_totals()
        order, seen = [], set()
        names = {}
        for character, name, _, _, _, _, _ in rows:
            if not character:
                continue
            if character not in seen:
                seen.add(character)
                order.append(character)
            names[character] = name or core._resolve_character_name(character) or character
        for character in order:
            participant = participants[character]
            participant.update(self.totals[character])
            participant.update(character_key=character,
                character_name=names[character],
                max_hit=max(0, max(self.values[character], default=0), visual[character]))
        for record in buffs:
            for character in (record.get('source_character_key'), record.get('target_character_key')):
                if not character:
                    continue
                character = str(character)
                if character not in seen:
                    seen.add(character)
                    order.append(character)
                participants[character].update(character_key=character,
                    character_name=core._resolve_character_name(character) or character)
        # Enemy Counter tie order follows the current hit order, including after
        # a correction removes/reintroduces an enemy in the persistent cache.
        enemies = Counter()
        for character, _, enemy, _, _, _, _ in rows:
            if character and enemy and enemy not in enemies:
                enemies[enemy] = self.enemies[enemy]
        return participants, core._new_skill_totals(), order, seen, enemies
