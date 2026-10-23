"""Deterministic protocol scenarios constructed from constants, never recordings.

Identifiers, timestamps, HP, stats and blackboards below are invented test values.
Game template/action IDs describe the protocol cases being tested, not a capture.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / '_internal/packages/parser_core/tests/fixtures'
SESSION = 'synthetic-corrosion'
ENEMY = 'eny_0051_rodin'


def stamp(ms):
    return f'[00:00:{ms // 1000:02}.{ms % 1000:03}]'


def event(ms, tag, value):
    return f'{stamp(ms)} {tag} ' + json.dumps(value, separators=(',', ':'))


def stats(actor, template):
    return (f'{stamp(0)} ENTITY_STATS id={actor} template={template} '
            'kind=' + ('monster' if template.startswith('eny_') else 'character') +
            ' level=90 hp=10000 attrs=[1:10000/10000 2:100/100 87:100/100 '
            '95:0/0 96:0/0 97:0/0 98:0/0 99:0/0]')


def hit(ms, seq, damage, character, skill, *, packet, action=0, template=0, origin=0):
    return (f'{stamp(ms)} HP_V2 #{seq} hit={damage} cum={damage} raw={damage} '
            f'packetFinalValue={damage} pHP=100 eHP=10000 skill="{skill}" hits=1 '
            f'skillLv=1 templateIntId={template} templateType=Skill actionId={action} '
            f'origTemplateIntId={origin or template} damageUnitIndex=0 '
            f'src={character} tgt={ENEMY} atk={character} atkId=1001 tgtId=3001 '
            f'seg=0 critFlag=0 packetSeq={packet} clientTick={ms} packetSessionId="{SESSION}"')


def identity(uid, seq, ms, numeric, action, *, legacy=False):
    result = dict(schemaVersion=1, sessionId=SESSION, operationSeq=seq,
                  operationOwnerId='3001', ownerType='1', ownerId='3001',
                  environmentInstId=str(uid), generation=0, clientTickMs=str(ms),
                  templateType='Buff', templateIdCase='int_id', templateIntId=numeric,
                  templateStrId=None, actionId=action, triggerType=0,
                  actionType=7, actionRuntimeCase='modify_dynamic_blackboard_action',
                  operationPayloadCase='trigger_action_op_data')
    if legacy:
        for key in ('operationOwnerId', 'ownerId', 'environmentInstId', 'generation',
                    'templateType', 'templateIdCase', 'templateIntId', 'actionRuntimeCase', 'operationPayloadCase'):
            result[key] = None
        result['eventContext'] = dict(owner_id=3001, inst_id=uid, owner_type='1',
                                      template_type='Buff', template_int_id=numeric, seq_id=seq)
    return result


def create(ms, uid, buff, provider, numeric, creator, action, seq, values, *, owner=ENEMY, actor=3001):
    source_actor = actor if owner == provider else 2001
    lines = [f'{stamp(ms)} BUFF_START #{seq} id="{buff}" uid={uid} owner={owner} '
             f'src={provider} ownerId={actor} srcId={source_actor} dur=30',
             f'{stamp(ms)} BB[{uid}]: ' + ' '.join(f'{k}={v}' for k, v in values.items())]
    data = dict(schemaVersion=1, buffUid=str(uid), buffTemplate=buff,
                sourceActorId=str(source_actor), targetActorId=str(actor), sessionId=SESSION,
                operationSeq=seq, operationOwnerId=str(actor), operationGeneration=0,
                generationScope='operation_owner', sourceEvent='BattleOpTriggerAction',
                buffNumId=numeric, assignedItems=[dict(target_key=k, use_direct_value=True,
                    numeric_value=v, input_value_key='', string_value='') for k, v in values.items()],
                isNewInstance=True, priorUidObserved=False, observationKind='creation_or_refresh',
                actionId=action, triggerType=0, creationActionType='BattleActionCreateBuff',
                creationActionRuntimeCase='create_buff_action')
    lines.append(event(ms, 'BUFF_CREATE_OBSERVED', data))
    lines.append(event(ms, 'BUFF_ORIGIN', dict(schemaVersion=1, buffUid=str(uid), buffTemplate=buff,
                 sourceActorId=str(source_actor), targetActorId=str(actor), environmentType='Buff', ownerType='1',
                 environmentInstId=str(uid + 100), templateIntId=creator, actionId=action,
                 operationSeq=seq, triggerType=0)))
    return lines


def refresh(ms, uid, buff, numeric, seq, value, action, *, legacy=False):
    modify = identity(uid, seq, ms, numeric, action, legacy=legacy)
    update = (f'{stamp(ms)} BB_MODIFY_DYNAMIC seq={seq} tick={ms} inst={uid} ownerId=3001 '
              f'owner={ENEMY} skill={buff} actionId={action} value={value} identity=' +
              json.dumps(modify, separators=(',', ':')))
    changed = identity(uid, seq + 1, ms, numeric, action + 1, legacy=legacy)
    changed.update(actionType=31, actionRuntimeCase=None if legacy else 'refresh_buff_attr_modifier_value_action',
                   buffUid=None if legacy else str(uid))
    if legacy:
        changed['validationErrors'] = ['refresh_runtime_presence_unverified']
    return [update, event(ms, 'BUFF_ATTR_REFRESH_UNRESOLVED' if legacy else 'BUFF_ATTR_REFRESH', changed)]


def packet_details(ms, seq, packet, *, resistance=None, attacker_uid=None):
    lines = [event(ms, f'PKT_ATTR_INFO #{seq}', dict(reportPresent=True, packetSeq=packet, packetSessionId=SESSION))]
    lines.append(f'{stamp(ms)} PKT_ATTR #{seq} atk=[] def=[' + (f'98:{resistance}' if resistance is not None else '') + ']')
    if attacker_uid is not None:
        lines.append(event(ms, f'PKT_MOD_DETAIL #{seq}', dict(
            attacker=[dict(buff_inst_id=str(attacker_uid), index=0, processor_debug_args={})],
            defender=[], packetSessionId=SESSION, packetSeq=packet, damageUnitIndex=0)))
    return lines


def fire_corrosion():
    buff = 'buff_common_natural_fire_triggered'
    provider = 'chr_0032_lizhiyan'
    attacker = 'chr_0028_wulfa'
    lines = [stats(1001, attacker), stats(2001, provider), stats(3001, ENEMY)]
    for ms, uid, count, start, cap, refresh_values in [
        (100, 8001, 2, -8, -30, [(100, 101, -8), (500, 501, -20)]),
        (1100, 8002, 3, -30, -40, [(1100, 1101, -30), (1500, 1501, -40)]),
        (2100, 8003, 2, -40, -30, []),
    ]:
        if uid != 8001:
            lines.append(f'{stamp(ms)} BUFF_END #{ms} id="{buff}" uid={uid - 1}')
        values = dict(def_decrease=start, additional_def_decrease=0, start_def_decrease=-8,
                      max_def_decrease=cap, def_decrease_tick=-2, count=count, duration=30)
        lines.extend(create(ms, uid, buff, provider, 329, 330, 4, ms, values))
        for time, seq, value in refresh_values:
            lines.extend(refresh(time, uid, buff, 329, seq, value, 11))
        time = ms + 500
        seq = uid - 8000
        lines.append(hit(time, seq, 100 + seq * 20, attacker, 'chr_0028_wulfa_ultimate_skill',
                         packet=time, action=176, template=2397))
        lines.extend(packet_details(time, seq, time))
    return lines


def legacy_corrosion():
    attacker, provider = 'chr_0016_laevat', 'chr_0025_ardelia'
    buff = 'buff_common_natural_natural_corrupt_do'
    lines = [stats(1001, attacker), stats(2001, provider), stats(3001, ENEMY)]
    lines.extend(create(50, 9001, 'buff_chr_0016_laevat_ignore_fire_resist', attacker, 1575, 1034, 3, 1,
                        dict(ignore_fire_resist=-20, ignore_fire_resist_duration=20), owner=attacker, actor=1001))
    lines.extend(create(100, 9002, buff, provider, 1984, 331, 7, 10,
                        dict(def_decrease=-12, additional_def_decrease=0, max_def_decrease=-24,
                             start_def_decrease=-12, def_decrease_tick=-2, count=1, duration=30)))
    for ms, seq, value, damage in [(200, 12, -12.0, 132), (600, 22, -24.0, 144)]:
        lines.extend(refresh(ms, 9002, buff, 1984, seq, value, 13, legacy=True))
        n = 1 if seq == 12 else 2
        lines.append(hit(ms + 100, n, damage, attacker, 'chr_0016_laevat_ult_attack3',
                         packet=n * 20, action=13, template=1021))
        lines.extend(packet_details(ms + 100, n, n * 20, resistance=-20.0 + value, attacker_uid=9001))
    return lines


def combo(kind):
    character = 'chr_0006_wolfgd'
    cases = [('chr_0006_wolfgd_attack1_projhit01', 0, 1404, 170),
             ('chr_0006_wolfgd_normal_skill_projhit', 1, 187, 179),
             ('chr_0006_wolfgd_normal_skill_projhit', 1, 187, 179),
             ('chr_0006_wolfgd_normal_skill_projhit_FireSpellInfiction', 1, 1939, 179)] if kind == 'skill' else [
                 *[('chr_0006_wolfgd_ultimate_skill', a, 192, 192) for a in (19, 23, 27, 31, 35)],
                 *[('buff_common_burning_status', 0, 213, 192)] * 3]
    provider = 'chr_0019_karin'
    templates = ('buff_common_affixes_combo_trigger', 'buff_common_affixes_skillimbue',
                 'buff_common_affixes_skillimbue_atk')
    lines = [stats(1001, character), stats(2001, provider), stats(3001, ENEMY)]
    for position, buff in enumerate(templates):
        uid, ms = 10001 + position, 10 + position * 10
        action = 4 if position == 1 else 0
        lines += [f'{stamp(ms)} BUFF_START #{position + 1} id="{buff}" uid={uid} '
                  f'owner={character} src={provider} ownerId=1001 srcId=2001 dur=30',
                  f'{stamp(ms)} BB[{uid}]: imbue_scale=0.2']
        lines.append(event(ms, 'BUFF_CREATE_OBSERVED', dict(
            schemaVersion=1, buffUid=str(uid), buffTemplate=buff, sourceActorId='2001',
            targetActorId='1001', sessionId=SESSION, operationSeq=position + 1,
            buffId=buff, operationOwnerId='1001', operationGeneration=0, generationScope='operation_owner',
            sourceEvent='BattleOpTriggerAction', actionId=action, triggerType=0,
            creationActionType='BattleActionCreateBuff', creationActionRuntimeCase='create_buff_action',
            assignedItems=[dict(target_key='imbue_scale', use_direct_value=True,
                                numeric_value=0.2, input_value_key='', string_value='')])))
        if position:
            lines.append(event(ms, 'BUFF_ORIGIN', dict(
                schemaVersion=1, buffUid=str(uid), buffTemplate=buff,
                sourceActorId='2001', targetActorId='1001', environmentType='Buff', ownerType='1',
                environmentInstId=str(uid - 1), templateStrId=templates[position - 1],
                actionId=action, operationSeq=position + 1, triggerType=0)))
    for i, (skill, action, template, origin) in enumerate(cases, 1):
        ms = i * 100
        lines.append(hit(ms, i, 100, character, skill, packet=i * 100,
                         action=action, template=template, origin=origin))
        applicable = (kind == 'skill' and i >= 2) or (kind == 'ultimate' and i <= 5)
        lines.extend(packet_details(ms, i, i * 100, attacker_uid=10003 if applicable else None))
    return lines


def generate():
    return {
        'synthetic_fire_corrosion.log': fire_corrosion(),
        'synthetic_corrosion_packet.log': legacy_corrosion(),
        'synthetic_combo_skill.log': combo('skill'),
        'synthetic_combo_ultimate.log': combo('ultimate'),
    }


def main():
    for name, lines in generate().items():
        payload = ('# SYNTHETIC protocol scenario; generated from constants, not a battle capture.\n' +
                   '\n'.join(lines) + '\n').encode('utf8')
        path = DEST / name
        path.write_bytes(payload)
        manifest = dict(schema_version=1, kind='synthetic', generator='_development/tools/generate_test_fixtures.py',
                        fixtureSha256=hashlib.sha256(payload).hexdigest(), lines=len(lines),
                        evidence_scope='Parser regression only; does not prove real game behavior or upload eligibility.')
        path.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    print('Generated four synthetic fixtures without reading any recordings.')


if __name__ == '__main__':
    main()
