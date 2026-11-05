"""Structural mapping of existing packet proofs; no log text or JSON roundtrip."""
FIELDS = dict(zip(
    ('schemaVersion', 'buffUid', 'buffTemplate', 'sourceActorId', 'targetActorId', 'sessionId',
     'operationSeq', 'operationOwnerId', 'operationGeneration', 'generationScope', 'sourceEvent',
     'buffNumId', 'buffId', 'buffTemplateId', 'assignedItems', 'isNewInstance', 'priorUidObserved',
     'observationKind', 'enhanceMultiplier', 'actionId', 'triggerType', 'creationActionType',
     'creationActionRuntimeCase', 'environmentType', 'ownerType', 'environmentInstId',
     'templateStrId', 'templateIntId', 'enabled', 'ownerId', 'clientTickMs', 'generation',
     'addedBuffNumId', 'modify', 'operationPayloadCase', 'validationErrors'),
    ('schema_version', 'buff_inst_id', 'template', 'source_actor_id', 'target_id', 'session_id',
     'operation_seq', 'operation_owner_id', 'operation_generation', 'generation_scope', 'source_event',
     'buff_num_id', 'buff_id', 'buff_template_id', 'assigned_items', 'is_new_instance', 'prior_uid_observed',
     'observation_kind', 'enhance_multiplier', 'action_id', 'trigger_type', 'creation_action_type',
     'creation_action_runtime_case', 'environment_type', 'owner_type', 'environment_inst_id',
     'template_str_id', 'template_int_id', 'enabled', 'owner_id', 'client_tick_ms', 'generation',
     'added_buff_num_id', 'modify', 'operation_payload_case', 'validation_errors'), strict=True))
FIELDS.update(templateType='template_type', templateIdCase='template_id_case', actionType='action_type',
              actionRuntimeCase='action_runtime_case', eventContext='event_context', runtime='runtime',
              actionSerialization='action_serialization')


def packet_data(observation):
    mapped = {FIELDS[key]: value for key, value in observation.items()}
    if isinstance(mapped.get('modify'), list):
        mapped['modify'] = [{{'configIndex': 'config_index', 'rateAfter': 'rate_after'}[key]: value
                            for key, value in row.items()} if isinstance(row, dict) else row for row in mapped['modify']]
    data = {'observation': mapped}
    if mapped.get('template') == 'unknown_buff':
        mapped['template'] = None
        data['template_status'] = 'unresolved'
    return data


def packet_observation(data):
    inverse = {value: key for key, value in FIELDS.items()}
    observation = {inverse[key]: value for key, value in data['observation'].items()}
    if isinstance(observation.get('modify'), list):
        observation['modify'] = [{{'config_index': 'configIndex', 'rate_after': 'rateAfter'}[key]: value
                                 for key, value in row.items()} if isinstance(row, dict) else row for row in observation['modify']]
    if data.get('template_status') == 'unresolved' and observation.get('buffTemplate') is None:
        observation['buffTemplate'] = 'unknown_buff'
    return observation


def observation_pairs(value):
    """The existing proof validators retain nested object-pairs semantics."""
    if isinstance(value, dict):
        return [(key, observation_pairs(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [observation_pairs(item) for item in value]
    return value
