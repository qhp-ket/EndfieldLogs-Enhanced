import json
from parser_core import battle_log_parser as core
from parser_core.ink_provenance import BUFF, EXPLOSION, OWNER, apply_ink_provenance

ATTACKER = 'chr_0004_pelica'

SUPPORT = 'chr_0035_liino'

class Trace:
    def __init__(self):
        self.lines = ['[10:00:00.000] CONTEXT']
        self.hits = []
        self.records = [dict(event_key=BUFF, uid='7001', source_character_key=OWNER, source_actor_id='4001',
            target_actor_id='3001', line_no=1, packet_creation_contexts=[dict(session_id='test', operation_seq=1)])]

    def line(self, body):
        self.lines.append('[10:00:00.000] ' + body)
        return len(self.lines)

    def source(self, seq, value, shares, *, tick=1000, session='test'):
        hit = dict(line_no=self.line('SOURCE'), seq=len(self.hits)+1, character_key=ATTACKER,
            packet_session_id=session, packet_seq_id=seq, client_tick_ms=tick, target_actor_id='3001',
            packet_final_value=value, rdps_contributions=shares)
        self.hits.append(hit)
        return hit

    def dynamic(self, seq, action, value, *, tick=1000, session='test'):
        identity = dict(schemaVersion=1, sessionId=session, operationSeq=seq, ownerType='1',
            ownerId='3001', environmentInstId='7001', templateType='Buff', actionId=action,
            clientTickMs=str(tick), triggerType=0, actionType=7,
            actionRuntimeCase='modify_dynamic_blackboard_action', operationPayloadCase='trigger_action_op_data')
        return self.line(f'BB_MODIFY_DYNAMIC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={BUFF} '
            f'actionId={action} value={value!r} identity=' + json.dumps(identity, separators=(',', ':')))

    def add(self, seq, previous, increment, *, tick=1000):
        self.line(f'BB_SIMPLE_CALC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={BUFF} '
            f'actionId=47 key=EntityBB_ink_damage valueA={previous} valueB={increment} final={previous+increment}')

    def release(self, seq=130, *, projectile='8001', legacy=False):
        if legacy:
            self.dynamic(seq-1, 13, 0)
            self.line(f'ACTOR_MAP id={projectile} template={OWNER} source=launch_projectile skill=None')
            self.line(f'SKILL_CAST_START seq={seq+1} startMs=1000 inst=8002 ownerId={projectile} skill={EXPLOSION}')
        else:
            self.line('INK_RELEASE ' + json.dumps(dict(schema_version=1, template_key=BUFF, action_id=14,
                session_id='test', operation_seq=seq, buff_uid='7001', owner_id='3001', source_actor_id='4001',
                projectile_id=projectile, client_tick_ms=1000)))
        self.dynamic(seq+2, 15, 0)

    def explosion(self, value, *, seq=140, effective=None, projectile='8001', session='test'):
        hit = dict(line_no=self.line('EXPLOSION'), seq=len(self.hits)+1, character_key=OWNER,
            target_actor_id='3001', source_actor_id='4001', packet_session_id=session, packet_seq_id=seq,
            event_owner_id=projectile, event_inst_id='8002', client_tick_ms=1000,
            skill_key=EXPLOSION, packet_final_value=value, hit_value=value if effective is None else effective,
            rdps_contributions={OWNER: value}, damage_calculation=dict(atkCalculation=dict(
                value=dict(blackboardKey='EntityBB_ink_damage', useBlackboardKey=True))))
        self.hits.append(hit)
        return hit

    def run(self, roots=None):
        return apply_ink_provenance('\n'.join(self.lines), self.hits, self.records,
            root_lookup=roots if roots is not None else core._load_current_buff_roots(), extract_fields=core._extract_fields)
