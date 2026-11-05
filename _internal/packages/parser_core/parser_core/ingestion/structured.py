"""Object dispatcher shared by live and JSONL history callers."""
from parser_core.ingestion.structured_damage import consume_structured_damage
from parser_core.ingestion.structured_entity import consume_structured_entity, ENTITY_TYPES
from parser_core.ingestion.structured_identity import consume_structured_identity
from parser_core.ingestion.structured_character_skills import consume_structured_character_skills
from parser_core.ingestion.structured_loadout import consume_structured_loadout
from parser_core.ingestion.structured_skill import consume_structured_skill
from parser_core.ingestion.structured_buff import consume_structured_buff
from parser_core.ingestion.structured_buff_packet import consume_structured_buff_packet
from parser_core.ingestion.structured_dynamic import consume_structured_dynamic
from parser_core.ingestion.blackboard_wire import TYPES as BLACKBOARD_TYPES, consume_structured_blackboard
from parser_core.ingestion.structured_clock import CLOCK_TYPES, consume_structured_clock
from parser_core.ingestion.structured_timer import TIMER_TYPES, consume_structured_timer
from parser_core.ingestion.structured_stage import STAGE_TYPES, consume_structured_stage
from parser_core.ingestion.structured_context import CONTEXT_TYPES, consume_structured_context
from parser_core.ingestion.historical_wire import TYPES as HISTORICAL_TYPES, consume_historical


def consume_trace_event(ingestion, event, evidence_index):
    if event.type == 'damage':
        consume_structured_damage(ingestion, event, evidence_index)
    elif event.type in HISTORICAL_TYPES:
        consume_historical(ingestion, event, evidence_index)
    elif event.type in ENTITY_TYPES:
        consume_structured_entity(ingestion, event, evidence_index)
    elif event.type in ('squad', 'actor_mapping', 'identity_inference'):
        consume_structured_identity(ingestion, event, evidence_index)
        if event.type == 'identity_inference':
            ingestion.trace_identity_inference_seen = True
            ingestion.pending_buff_record = None
    elif event.type == 'character_skills':
        consume_structured_character_skills(ingestion, event, evidence_index)
    elif event.type in ('loadout_group', 'loadout_slot', 'loadout_stats'):
        consume_structured_loadout(ingestion, event, evidence_index)
    elif event.type in ('skill_cast', 'atb', 'poise'):
        consume_structured_skill(ingestion, event, evidence_index)
    elif event.type in ('buff_start', 'buff_end', 'buff_blackboard'):
        consume_structured_buff(ingestion, event, evidence_index)
    elif event.type in ('buff_creation', 'buff_origin', 'buff_enable', 'buff_keyword', 'buff_unresolved'):
        consume_structured_buff_packet(ingestion, event, evidence_index)
    elif event.type in ('blackboard_dynamic', 'buff_attribute_refresh', 'blackboard_skill_setting'):
        consume_structured_dynamic(ingestion, event, evidence_index)
    elif event.type in BLACKBOARD_TYPES:
        consume_structured_blackboard(ingestion, event, evidence_index)
    elif event.type in CLOCK_TYPES:
        consume_structured_clock(ingestion, event, evidence_index)
    elif event.type in TIMER_TYPES:
        consume_structured_timer(ingestion, event, evidence_index)
    elif event.type in STAGE_TYPES:
        consume_structured_stage(ingestion, event, evidence_index)
    elif event.type in CONTEXT_TYPES:
        consume_structured_context(ingestion, event, evidence_index)
    else:
        raise NotImplementedError('Structured ingestion is not connected for ' + event.type)
    ingestion.official_timer_collector.observe_event(evidence_index, event)
    ingestion.evidence_count = max(ingestion.evidence_count, evidence_index)


def consume_trace_events(ingestion, batch):
    for evidence_index, event in batch:
        consume_trace_event(ingestion, event, evidence_index)
