"""One damage observation shared by text import and structured ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from parser_core.ingestion.fields import (
    _coerce_int, _coerce_optional_float, _coerce_optional_int, _extract_fields,
)

HIT_SEQUENCE_RE = re.compile(r"\bHP_V2\s+#(\d+)\b")


@dataclass(frozen=True, slots=True)
class DamageObservation:
    sequence: int | None = None
    source: str | None = None
    attacker: str | None = None
    target: str | None = None
    source_actor: str | None = None
    target_actor: str | None = None
    skill: str | None = None
    template_type: str | None = None
    hit: int = 0
    hit_observed: bool = False
    unresolved_hit_text: str | None = None
    enemy_hp: int = 0
    enemy_hp_observed: bool = False
    raw: float | None = None
    final: float | None = None
    critical: int = 0
    critical_observed: bool = False
    skill_level: int | None = None
    template_integer: int | None = None
    event_instance: str | None = None
    event_owner: str | None = None
    client_tick: int | None = None
    action: int | None = None
    unit_index: int | None = None
    original_template: int | None = None
    part_instance: int | None = None
    hit_index: int = 1
    packet_owner: str | None = None
    packet_generation: int | None = None
    packet_sequence: int | None = None
    packet_session: str | None = None
    dynamic_signature: str | None = None
    dynamic_values: dict[int, float] = field(default_factory=dict)
    calculation_signature: str | None = None
    calculation_values: dict[int, dict[str, float | str]] = field(default_factory=dict)

    @classmethod
    def from_legacy(cls, line: str) -> DamageObservation:
        fields = _extract_fields(line)

        def actor(key: str) -> str | None:
            value = fields.get(key, "")
            return value if re.fullmatch(r"[1-9]\d*", value) else None

        def index(key: str) -> int | None:
            value = fields.get(key, "")
            return int(value) if re.fullmatch(r"\d+", value) else None

        dynamic: dict[int, float] = {}
        for token in re.split(r"[,;]", fields.get("dynBB") or ""):
            key, separator, value = token.partition(":")
            number = _coerce_optional_float(value) if separator else None
            identity = _coerce_optional_int(key)
            if identity is not None and number is not None:
                dynamic[identity] = number
        calculation: dict[int, dict[str, float | str]] = {}
        for token in re.split(r"[,;]", fields.get("calcBB") or ""):
            group, separator, assignment = token.partition(":")
            key, assignment_separator, value = assignment.partition("=")
            identity = _coerce_optional_int(group)
            if identity is None or not separator or not assignment_separator or not key:
                continue
            number = _coerce_optional_float(value)
            calculation.setdefault(identity, {})[key] = number if number is not None else value
        sequence = HIT_SEQUENCE_RE.search(line)
        owner = actor("packetOwnerId")
        if owner is not None and int(owner) >= 2**64:
            owner = None
        return cls(
            sequence=int(sequence.group(1)) if sequence else None,
            source=fields.get("src"), attacker=fields.get("atk"), target=fields.get("tgt"),
            source_actor=actor("atkId"), target_actor=actor("tgtId"), skill=fields.get("skill"),
            template_type=fields.get("templateType"), hit=_coerce_int(fields.get("hit")), hit_observed="hit" in fields,
            unresolved_hit_text=fields.get("hit"), enemy_hp=_coerce_int(fields.get("eHP")), enemy_hp_observed="eHP" in fields,
            raw=_coerce_optional_float(fields.get("raw")), final=_coerce_optional_float(fields.get("packetFinalValue")),
            critical=_coerce_int(fields.get("critFlag")), critical_observed=fields.get("critFlag") in {"0", "1"},
            skill_level=_coerce_int(fields.get("skillLv"), default=0) or None,
            template_integer=_coerce_int(fields.get("templateIntId"), default=0) or None,
            event_instance=actor("eventInstId"), event_owner=actor("eventOwnerId"), client_tick=index("clientTick"),
            action=index("actionId"), unit_index=index("damageUnitIndex"),
            original_template=_coerce_int(fields.get("origTemplateIntId"), default=0) or None,
            part_instance=_coerce_optional_int(fields.get("partInstId")), hit_index=_coerce_int(fields.get("hits"), default=1),
            packet_owner=owner, packet_generation=index("packetGeneration"), packet_sequence=index("packetSeq"),
            packet_session=fields.get("packetSessionId") or None,
            dynamic_signature=fields.get("dynBB"), dynamic_values=dynamic,
            calculation_signature=fields.get("calcBB"), calculation_values=calculation,
        )
