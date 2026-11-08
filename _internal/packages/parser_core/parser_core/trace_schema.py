"""Canonical trace field identities shared by native codecs and v1 adapters."""
INSTANCE_FIELDS = frozenset({'attacker_id', 'target_id', 'event_inst_id', 'event_owner_id',
                             'part_inst_id', 'buff_inst_id', 'entity_id', 'object_id',
                             'weapon_id', 'gem_id', 'gem_weapon_id', 'owner_id', 'skill_inst_id', 'source_actor_id', 'operation_owner_id', 'environment_inst_id', 'projectile_id',
                             'game_inst_id', 'game_unique_id', 'interactive_obj_id', 'npc_proxy_id', 'npc_obj_id', 'battle_inst_id'})

# Blackboard keys, debug payloads and anomaly originals are not schema fields.
# Preserve their scalar meaning even when a user/protocol key resembles an ID.
OPAQUE_FIELDS = frozenset({'bb', 'debug', 'debug_args', 'processor_debug_args',
                           'invalid_fields', 'normalization_errors'})
