
CHARACTERS = ["chr_0016_laevat", "chr_0033_camille", "chr_0032_lizhiyan", "chr_0035_liino"]

ACTORS = ["102140", "102171", "102201", "102231"]

GAME = "indie_hard013_s"

START = 1791811352908

def plan(identity="plan-1", *, position=0, enabled=True, dungeon=GAME):
    return {"id": identity, "name": "测试轴", "dungeonId": dungeon,
            "characterIds": CHARACTERS.copy(), "position": position, "enabled": enabled,
            "revision": 1, "updatedAt": "2026-10-14T00:00:00Z", "displayNotes": "装备只展示",
            "steps": [{"id": "step-1", "atMs": 2000, "characterId": CHARACTERS[3],
                       "skillId": "chr_0035_liino_normal_skill", "note": "战技", "phase": "开场"},
                      {"id": "step-2", "atMs": 4000, "characterId": CHARACTERS[3],
                       "skillId": "chr_0035_liino_normal_skill", "note": "再释放", "phase": ""}]}

def envelope(plans=None, account="user-1"):
    return {"schemaVersion": 1, "accountId": account, "revision": "a", "rotations": plans or [plan()]}

def feed(engine, *lines):
    for line in lines:
        engine.feed_line("[21:22:34.800] " + line)

def context(engine, *, dungeon=GAME, reverse=False):
    members = [f"{char}_{actor}" for char, actor in zip(CHARACTERS, ACTORS)]
    if reverse:
        members.reverse()
    feed(engine, f"DUNGEON_CONTEXT dungeonId={dungeon} source=SC_SELF_SCENE_INFO sceneId=scene-1",
         f"SQUAD size=4 members=[{' '.join(members)}]")

def start(engine, *, start_ts=START):
    feed(engine, f"OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId={GAME} challengeStartTs={start_ts}",
         "GAME_TIMER_START seq=29242 source=PacketBattleState startMs=25266 official=1")

def cast(*, seq=29246, tick=26744, inst="102232", owner=CHARACTERS[3], actor=ACTORS[3],
         skill="chr_0035_liino_normal_skill", source="unknown"):
    return (f"SKILL_CAST_START seq={seq} startMs={tick} inst={inst} owner={owner} "
            f"ownerId={actor} skill={skill} skillSource={source}")

def action_catalog():
    roots = ["chr_0035_liino_normal_skill", "chr_0035_liino_normal_skill_ult",
             "chr_0035_liino_attack1_ult", "chr_0035_liino_ultimate_skill"]
    return {"schemaVersion": 2, "maps": [], "characters": [{
        "id": CHARACTERS[3], "name": "梨诺", "skills": [{"id": root, "name": "官方技能"} for root in roots],
        "actions": [{"kind": "battle_skill", "name": "战技", "skillName": "闪耀焦点", "iconUrl": "/battle.png", "rootSkillIds": roots[:2]},
                    {"kind": "ultimate_skill", "name": "终结技", "skillName": "晨星的协奏曲", "iconUrl": "/ultimate.png", "rootSkillIds": roots[3:]}],
    }]}

def action_plan(kind="battle_skill"):
    value = plan()
    for step in value["steps"]:
        del step["skillId"]
        step["actionKind"] = kind
    return value
