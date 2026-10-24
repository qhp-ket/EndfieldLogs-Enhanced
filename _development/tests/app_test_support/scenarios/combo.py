from endfield_pcap.analysis.combo import ComboCooldownPublisher

class Clock:
    wall = 1_000_000
    mono = 10_000
    def advance(self, ms):
        self.wall += ms
        self.mono += ms

def publisher():
    clock = Clock()
    return ComboCooldownPublisher(wall_ms=lambda: clock.wall, monotonic_ms=lambda: clock.mono), clock

def scene(session="s1"):
    return {"type": "SC_SELF_SCENE_INFO", "session_id": session, "timestamp_ms": 1_000_000,
            "char_list": [{"battle_inst_id": 9007199254740993 + i, "squad_index": i,
                           "display_name": name, "potential_level": 4 if i == 1 else 0}
                          for i, name in enumerate(["佩丽卡", "陈千语", "狼卫", "洛茜"])]}

def trigger(skill=107, slot=0, **extra):
    return {"type": "BattleOpTriggerAction", "session_id": "s1", "timestamp_ms": 1_000_000,
            "owner_id": 9007199254740993 + slot, "seq_id": 1, "client_tick_tms": 1000,
            "template_type": "Skill", "template_int_id": skill, "level": 1, **extra}
