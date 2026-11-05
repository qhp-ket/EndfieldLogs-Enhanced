"""Bounded observed context for independently readable recording starts.

Keep mappings and currently observed BUFF instances, never previous hits or
invented input/timer events. The live producer is not reset by a disk boundary.
"""
from copy import deepcopy


class RecordingContext:
    def __init__(self):
        self.rows = {}
        self.serial = 0

    def clear(self):
        self.rows.clear()

    def _put(self, key, event):
        self.serial += 1
        self.rows[key] = self.serial, deepcopy(event)

    def observe(self, event):
        kind = event.get('type')
        if kind in ('SC_SELF_SCENE_INFO', 'LOADOUT', 'DUNGEON_CONTEXT', 'CONTRACT_TAGS'):
            self._put((kind,), event)
        elif kind == 'SC_SELF_SCENE_INFO_SKILLS':
            self._put((kind, event.get('owner_inst_id'), event.get('owner_templateid')), event)
        elif kind == 'SC_OBJECT_ENTER_VIEW':
            for row in event.get('objects') or []:
                self._put((kind, row.get('battle_inst_id') or row.get('id')), {**event, 'objects': [row]})
        elif kind == 'SC_SYNC_ATTR':
            # Attribute updates are deltas, not whole entity snapshots.
            for row in event.get('attrs') or []:
                self._put((kind, event.get('battle_inst_id') or event.get('obj_id'), row.get('attr_type')), {**event, 'attrs': [row]})
        elif kind == 'BattleOpSkillAttach':
            self._put((kind, event.get('skill_inst_id')), event)
        elif kind == 'BattleOpSkillDetach':
            self.rows.pop(('BattleOpSkillAttach', event.get('skill_inst_id')), None)
        elif kind == 'BattleOpAddBuff':
            self._put(('buff', event.get('buff_inst_id'), 'add'), event)
        elif kind == 'BattleOpFinishBuff':
            self._remove_buff(event.get('buff_inst_id'))
        elif kind == 'BattleOpSetBuffEnableState':
            self._put(('buff', event.get('buff_inst_id'), 'enable'), event)
        elif kind == 'BattleOpTriggerAction':
            action = event.get('action') or {}
            for field, remove in (('create_buff_action', False), ('remove_buff_action', True)):
                for detail in (action.get(field) or {}).get('details') or []:
                    uid = detail.get('buff_inst_id')
                    if remove:
                        self._remove_buff(uid)
                    else:
                        self._put(('buff', uid, 'create'), {**event, 'action': {field: {'details': [detail]}}})

    def _remove_buff(self, uid):
        for key in tuple(self.rows):
            if len(key) > 1 and key[0] == 'buff' and key[1] == uid:
                self.rows.pop(key)

    def snapshot(self):
        return [deepcopy(row) for _, row in sorted(self.rows.values(), key=lambda pair: pair[0])]
