"""Offline input intentions, independent of raw capture and battle mathematics."""
from __future__ import annotations
from dataclasses import dataclass
import math


def default_bindings():
    rows = []
    for slot in range(4):
        key = f'K:{49+slot}'
        rows += [dict(action='skill',slot=slot,keys=[key],gesture='tap_hold'),
                 dict(action='ultimate',slot=slot,keys=['K:ALT',key],gesture='press'),
                 dict(action='switch',slot=slot,keys=[f'K:{112+slot}'],gesture='press'),
                 dict(action='skill',slot=slot,keys=['P:LB','P:'+('WEST','NORTH','EAST','SOUTH')[slot]],gesture='tap_hold')]
    rows += [dict(action='combo',slot=None,keys=['K:69'],gesture='press'),
             dict(action='combo',slot=None,keys=['P:RB'],gesture='press'),
             dict(action='switch',slot=None,keys=['K:81'],gesture='press')]
    # A d-pad direction is an explicit slot intention, not inferred main-control evidence.
    rows += [dict(action='switch',slot=i,keys=['P:'+key],gesture='press')
             for i,key in enumerate(('LEFT','UP','RIGHT','DOWN'))]
    return rows


def normalize_settings(value):
    value = value if isinstance(value,dict) else {}
    try:
        threshold = max(1,min(10000,int(value.get('hold_ms',280))))
    except (ValueError,TypeError,OverflowError):
        threshold = 280
    rows = value.get('bindings',default_bindings())
    if not isinstance(rows,list):
        rows = default_bindings()
    cleaned = []
    for row in rows[:128]:
        if not isinstance(row,dict) or row.get('action') not in {'skill','ultimate','combo','switch','other'}:
            continue
        keys = row.get('keys')
        if not isinstance(keys,list) or not 1 <= len(keys) <= 8 or not all(isinstance(k,str) and 1<=len(k)<=40 for k in keys):
            continue
        slot = row.get('slot')
        cleaned.append(dict(action=row['action'],slot=slot if type(slot) is int and 0<=slot<4 else None,
                            keys=list(dict.fromkeys(keys)),gesture='tap_hold' if row.get('gesture')=='tap_hold' else 'press'))
    return dict(hold_ms=threshold,bindings=cleaned,show_other=bool(value.get('show_other',False)),
                show_motion=bool(value.get('show_motion',False)),show_axes=bool(value.get('show_axes',False)))


@dataclass
class Pending:
    binding: dict
    device: str
    start: dict


class Interpreter:
    def __init__(self, settings=None):
        self.settings = normalize_settings(settings)
        self.held = {}
        self.pending = []
        self.actions = []
        self.last = None
        self.baseline_keys = set()

    def feed(self, event):
        kind = event.get('type')
        self.last = event
        if kind in {'interrupt','gap','end'}:
            self.interrupt(event,event.get('reason',kind),event.get('device'))
            return
        if kind == 'focus' and not event.get('active'):
            self.interrupt(event,'focus_lost')
            return
        if kind == 'baseline':
            device=event.get('device')
            self.interrupt(event,'baseline',device)
            states={device:set(values) for device,values in event.get('states',{}).items()}
            if device is None:
                self.held=states
                self.baseline_keys=set(event.get('keyboard_vks', []))
            else:
                self.held.update(states)
            return
        if kind != 'input' or event.get('phase') not in ('down','up','repeat'):
            return
        if event.get('mapped_device') and str(event.get('code','')).startswith('J:'):
            return
        device,code,phase = str(event.get('device','unknown')),str(event.get('code','')),event['phase']
        held = self.held.setdefault(device,set())
        if code in self.baseline_keys:
            if phase == 'up':
                self.baseline_keys.discard(code)
            return
        if phase == 'repeat':
            return
        if phase == 'up':
            held.discard(code)
            for pending in list(self.pending):
                if pending.device == device and code in pending.binding['keys']:
                    self.finish(pending,event)
            return
        if code in held:
            return
        held.add(code)
        matching = [b for b in self.settings['bindings'] if code in b['keys'] and set(b['keys'])<=held]
        # Only simultaneously established combinations qualify. Specific combinations replace subsets.
        matching.sort(key=lambda b:len(b['keys']),reverse=True)
        claimed = set()
        for binding in matching:
            keys = set(binding['keys'])
            if keys & claimed:
                continue
            if any(p.device==device and keys<set(p.binding['keys']) for p in self.pending):
                continue
            for pending in list(self.pending):
                if pending.device==device and set(pending.binding['keys'])<=keys:
                    self.pending.remove(pending)
            self.pending.append(Pending(binding,device,event))
            claimed |= keys

    def finish(self, pending, end, interrupted=False, reason=''):
        self.pending.remove(pending)
        start = pending.start
        end_wall = end.get('wall_ns',end.get('start_wall_ns',start['wall_ns']))
        start_mono,end_mono = start.get('mono_ns'),end.get('mono_ns',end.get('start_mono_ns'))
        duration = ((end_mono-start_mono) if start_mono is not None and end_mono is not None
                    else end_wall-start['wall_ns']) / 1_000_000
        duration = max(0,duration)
        binding = pending.binding
        action = binding['action']
        rule = '组合成立 / 按下'
        if binding['gesture'] == 'tap_hold':
            action = 'ultimate' if duration >= self.settings['hold_ms'] else 'skill'
            rule = f'长按 ≥ {self.settings["hold_ms"]}ms（参考值）' if action=='ultimate' else '短按松开'
        self.actions.append(dict(action=action,slot=binding['slot'],device=pending.device,
            keys=binding['keys'],start_wall_ns=start['wall_ns'],end_wall_ns=end_wall,
            duration_ms=duration,rule=rule,interrupted=interrupted,reason=reason))

    def interrupt(self,event,reason,device=None):
        for pending in list(self.pending):
            if device is None or pending.device==device:
                self.finish(pending,event,True,reason)
        if device is None:
            self.held.clear()
            self.baseline_keys.clear()
        else:
            self.held.pop(device,None)

    def close(self):
        if self.last:
            self.interrupt(self.last,'incomplete_file')
        return self.actions


def project(actions,start_wall_ms,duration_ms,slots=None,offset_ms=0):
    slots = slots or {}
    result = []
    for action in actions:
        start = action['start_wall_ns']/1e6-start_wall_ms+offset_ms
        end = action['end_wall_ns']/1e6-start_wall_ms+offset_ms
        if end < 0 or start > duration_ms:
            continue
        owner = slots.get(action['slot']) if action['slot'] is not None else None
        result.append(dict(action,start_ms=start,end_ms=end,character_key=owner,
                           slot_label=f'角色槽位{action["slot"]+1}' if action['slot'] is not None else '全局'))
    return result


def tooltip(action):
    name = {'skill':'战技输入','ultimate':'终结技输入','combo':'连携输入','switch':'切换输入'}.get(action['action'],'其他输入')
    return (f'{action.get("slot_label", "")} · {name}（输入意图，不代表成功释放）\n'
            f'{action["device"]} · {" + ".join(action["keys"])}\n'
            f'{action.get("start_ms",0)/1000:.3f}s → {action.get("end_ms",0)/1000:.3f}s'
            f' · {action["duration_ms"]:.1f}ms\n{action["rule"]}'
            + (f'\n中断：{action["reason"]}' if action['interrupted'] else ''))
