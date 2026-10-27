"""Trace field decoding and numeric coercion."""
from __future__ import annotations

from datetime import (
    date,
    datetime,
    time,
    timedelta,
)
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from math import isfinite
from typing import Any
import re


_TIMESTAMP_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s+")


_KV_RE = re.compile(r'(\w+)=(".*?"|\S+)')


_SHORT_ID_RE = re.compile(r"^id_(\d+)$")


_DPD_RAW_RE = re.compile(
    r'DPD_RAW\s+#(?P<seq>\d+).*?\bcalc=(?P<calc>[-\d.eE+]+)\s+'
    r'atkScale=(?P<atk_scale>[-\d.eE+]+)\s+blocked=(?P<blocked>\d+)\s+'
    r'damageType=(?P<damage_type>0x[0-9A-Fa-f]+|\S+)\s+'
    r'decorateMask=(?P<decorate_mask>0x[0-9A-Fa-f]+|\S+)\s+'
    r'collider="(?P<collider>[^"]*)"\s+'
    r'atkZones=\[(?P<atk_zones>[^\]]*)\]\s+defZones=\[(?P<def_zones>[^\]]*)\]'
)


_BASELINE_RE = re.compile(r"\bBASELINE\s+#(?P<seq>\d+)\s+(?P<body>.*)")


_PKT_MOD_RE = re.compile(r"\bPKT_MOD\s+#(?P<seq>\d+)\s+atk=\[(?P<atk>[^\]]*)\]\s+def=\[(?P<def>[^\]]*)\]")


_PKT_ATTR_RE = re.compile(r"\bPKT_ATTR\s+#(?P<seq>\d+)\s+atk=\[(?P<atk>[^\]]*)\]\s+def=\[(?P<def>[^\]]*)\]")


_BASELINE_KV_RE = re.compile(r"(-?\d+)=([-\d.eE+]+)")


_LOADOUT_FIELD_RE_TEMPLATE = r"\b{key}=([^\s]+)"


def _positive_int(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    rounded = round(number)
    if abs(number - rounded) > 0.0001:
        return None
    return int(rounded)


def _token_field(line: str, key: str) -> str | None:
    match = re.search(_LOADOUT_FIELD_RE_TEMPLATE.format(key=re.escape(key)), line)
    return match.group(1) if match else None


def _braced_field(line: str, key: str) -> str | None:
    marker = f"{key}="
    start = line.find(marker)
    if start < 0:
        return None
    brace_start = line.find("{", start + len(marker))
    if brace_start < 0:
        return None
    depth = 0
    for index in range(brace_start, len(line)):
        char = line[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return line[brace_start + 1:index]
    return None


def _split_top_level(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == sep and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _parse_bb_assignments(blob: str | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in _split_top_level(str(blob or ""), ","):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        value = raw_value.strip()
        # Blackboard values can be signed (for example resistance reductions
        # use -20). Preserve the numeric value here; individual effect
        # semantics decide whether a positive rate is required.
        rate = _coerce_optional_float(value)
        values[key.strip()] = rate if rate is not None else value
    return values


def _ms_time_text(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    value = int(timestamp_ms) % (24 * 60 * 60 * 1000)
    hours, rem = divmod(value, 60 * 60 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _parse_loadout_suits(raw: str) -> set[str]:
    return {
        suit_id
        for suit_id, count in re.findall(r"\[([^\]]+)\]=(\d+)", raw or "")
        if int(count) >= 3
    }


def _parse_skill_int_ids(raw_line: str) -> list[str]:
    match = re.search(r"skillIntIds=\[([^\]]*)\]", raw_line)
    if not match:
        return []
    return re.findall(r"\d+", match.group(1))


def _parse_equip_levels(raw: str | None) -> list[dict[str, int]]:
    levels: list[dict[str, int]] = []
    for index, level in re.findall(r"(\d+):(\d+)", str(raw or "")):
        levels.append({"index": int(index), "level": int(level)})
    return levels


def _parse_inline_equip_stats(raw: str | None) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for item in str(raw or "").split(";"):
        if ":" not in item or "=" not in item:
            continue
        slot, rest = item.split(":", 1)
        name, raw_value = rest.split("=", 1)
        level = None
        value_text = raw_value
        if "@" in raw_value:
            value_text, raw_level = raw_value.rsplit("@", 1)
            try:
                level = int(raw_level)
            except ValueError:
                level = None
        number = _safe_positive_rate(value_text)
        stats.append(
            {
                "slot": slot,
                "name": name,
                "value": number if number is not None else value_text,
                "level": level,
            }
        )
    return stats


def _parse_prefixed_timestamp_ms(line: str) -> int | None:
    match = _TIMESTAMP_RE.match(line)
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _parse_hint_timestamp_ms(text: str | None) -> int | None:
    if not text:
        return None
    parts = text.split("-")
    if len(parts) != 4:
        return None
    hours, minutes, seconds, millis = (int(part) for part in parts)
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _extract_fields(line: str) -> dict[str, str]:
    return {
        key: value[1:-1] if value.startswith('"') and value.endswith('"') else value
        for key, value in _KV_RE.findall(line)
    }


def _parse_contract_tag_ids(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(item) for item in re.findall(r"\d+", value)]


def _short_actor_number(value: str | None) -> str | None:
    if not value:
        return None
    match = _SHORT_ID_RE.match(value)
    return match.group(1) if match else None


@lru_cache(maxsize=1)


def _parse_loadout_skill_ids(raw: str) -> set[str]:
    match = re.search(r"skillIntIds=\[([^\]]*)\]", raw)
    if not match:
        return set()
    return set(re.findall(r"\d+", match.group(1)))


def _coerce_int(value: str | None, default: int = 0) -> int:
    parsed = _coerce_optional_int(value)
    return default if parsed is None else parsed


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if isfinite(value) and value.is_integer() and abs(value) <= 2**53 else None
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        exact = Decimal(value)
        return int(exact) if exact.is_finite() and exact == exact.to_integral_value() else None
    except (ValueError, InvalidOperation, OverflowError):
        return None


def _coerce_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _coerce_optional_float(value: str | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_zone_values(blob: str | None) -> list[float | None]:
    if blob is None or not blob.strip():
        return []
    # Array position is the client-side zone identity. Preserve a missing
    # value in place; dropping it would relabel every subsequent zone.
    return [_coerce_optional_float(part.strip()) for part in blob.split(',')]


def _parse_dpd_raw_line(line: str) -> dict[str, Any] | None:
    match = _DPD_RAW_RE.search(line)
    if not match:
        return None
    return {
        "seq": int(match.group("seq")),
        "calc": _coerce_optional_float(match.group("calc")),
        "atk_scale": _coerce_optional_float(match.group("atk_scale")),
        "blocked": _coerce_optional_int(match.group("blocked")),
        "damage_type_raw": match.group("damage_type"),
        "decorate_mask_raw": match.group("decorate_mask"),
        "collider": match.group("collider"),
        "atk_zones": _parse_zone_values(match.group("atk_zones")),
        "def_zones": _parse_zone_values(match.group("def_zones")),
    }


def _damage_element_from_dpd_raw(dpd_raw: dict[str, Any] | None) -> str | None:
    return None


def _parse_baseline_line(line: str) -> tuple[int, dict[int, float]] | None:
    match = _BASELINE_RE.search(line)
    if not match:
        return None
    return (
        int(match.group("seq")),
        {
            int(key): _coerce_float(value)
            for key, value in _BASELINE_KV_RE.findall(match.group("body"))
        },
    )


def _parse_packet_modifier_line(line: str) -> tuple[int, list[str], list[str]] | None:
    match = _PKT_MOD_RE.search(line)
    if not match:
        return None
    attacker = [item for item in match.group("atk").split() if item]
    defender = [item for item in match.group("def").split() if item]
    return int(match.group("seq")), attacker, defender


def _parse_packet_attr_line(line: str) -> tuple[int, list[str], list[str]] | None:
    match = _PKT_ATTR_RE.search(line)
    if not match:
        return None
    attacker = [item for item in match.group("atk").split() if item]
    defender = [item for item in match.group("def").split() if item]
    return int(match.group("seq")), attacker, defender


def _duration_ms_from_seconds(value: str | None) -> int | None:
    seconds = _coerce_float(value, default=-1.0)
    if seconds < 0:
        return None
    if seconds > 1_000_000:
        return None
    return int(round(seconds * 1000))


def _build_iso_datetime(reference_date: date, timestamp_ms: int, rollover_days: int = 0) -> str:
    midnight = datetime.combine(reference_date, time.min)
    result = midnight + timedelta(days=rollover_days, milliseconds=timestamp_ms)
    return result.astimezone().isoformat(timespec="milliseconds")


def _safe_positive_rate(value: Any) -> float | None:
    rate = _coerce_optional_float(value)
    return rate if rate is not None and rate > 0 else None
