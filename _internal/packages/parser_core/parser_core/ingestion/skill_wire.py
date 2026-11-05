"""Original skill/resource fields and their established analysis precision."""
from math import isfinite


FIELDS = {
    "skill_cast": (("skill_inst_id", "skill_inst_id"), ("owner_id", "owner_id")),
    "atb": (("owner_id", "owner_id"), ("reason", "reason"), ("atb_value", "value"),
            ("atb_recovery_speed", "recovery_speed"), ("delta_value", "delta")),
    "poise": (("attacker_inst_id", "attacker_id"), ("modify_type", "modify_type"), ("value", "value"),
              ("cur_poise_value", "current_value"), ("owner_type", "owner_type"), ("template_type", "source_type"),
              ("template_int_id", "source_int"), ("orig_template_type", "original_source_type"),
              ("orig_template_int_id", "original_source_int"), ("action_id", "action_id")),
}


def skill_data(kind, event):
    fields = FIELDS[kind] + (("seq_id", "operation_seq"), ("client_tick_tms", "client_tick_ms"))
    return {target: event[source] for source, target in fields if source in event}


def integer(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return None


def number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError, OverflowError):
        return None


def projected_number(value):
    result = number(value)
    return float(format(result, ".6g")) if result is not None and isfinite(result) else None


def label(data, key, fallback="unknown"):
    return str(data.get(key) or fallback)


def identity_token(value):
    result = integer(value)
    return str(result) if result is not None else "unknown"
