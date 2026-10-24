from __future__ import annotations
import json
from typing import Any
from endfield_pcap.capture.resolver import PacketResolveContext
from endfield_pcap.trace.formatting import _intish, _floatish, _template_id


class BuffMapping:
    @staticmethod
    def _assigned_list_to_blackboard(items: Any) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("target_key") or item.get("input_value_key") or "")
            value = _floatish(item.get("numeric_value"))
            if key and value is not None:
                out[key] = {"float_value": value}
        return out

    @staticmethod
    def _assigned_list_to_values(items: Any) -> dict[str, float]:
        out: dict[str, float] = {}
        if isinstance(items, dict):
            blackboard = items.get("blackboard")
            if isinstance(blackboard, dict):
                for key, raw in blackboard.items():
                    if not isinstance(raw, dict):
                        continue
                    value = _floatish(raw.get("float_value"))
                    if value is None:
                        value = _floatish(raw.get("numeric_value"))
                    if value is None:
                        value = _floatish(raw.get("value"))
                    if key and value is not None:
                        out[str(key)] = value
            return out
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("target_key") or item.get("input_value_key") or item.get("targetKey") or item.get("inputValueKey") or "")
            value = _floatish(item.get("numeric_value"))
            if key and value is not None:
                out[key] = value
        return out

    def _assigned_items_to_values(self, items: Any) -> dict[str, float]:
        return self._assigned_list_to_values(items)

    @staticmethod
    def _assigned_items_to_keys(items: Any) -> set[str]:
        keys: set[str] = set()
        if isinstance(items, dict):
            blackboard = items.get("blackboard")
            if isinstance(blackboard, dict):
                keys.update(str(key) for key in blackboard.keys() if str(key))
            return keys
        if not isinstance(items, list):
            return keys
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("target_key") or item.get("input_value_key") or item.get("targetKey") or item.get("inputValueKey") or "")
            if key:
                keys.add(key)
        return keys

    @staticmethod
    def _buff_context_signature(
        owner: str,
        src: str,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> str:
        if target_id and src_id and target_id == src_id:
            return "self"
        if owner.startswith("eny_") and src.startswith("chr_"):
            return "player_to_enemy"
        if owner.startswith("chr_") and src.startswith("chr_"):
            return "ally" if owner != src else "self"
        if owner.startswith("eny_") and src.startswith("eny_"):
            return "enemy_self"
        return "other"

    def _learned_buff_signature(
        self,
        numeric_id: int,
        owner: str,
        src: str,
        assigned_items: Any,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> tuple[int, str, tuple[str, ...]]:
        keys = tuple(sorted(self._assigned_items_to_keys(assigned_items)))
        return (
            int(numeric_id),
            self._buff_context_signature(owner, src, target_id=target_id, src_id=src_id),
            keys,
        )

    def _learned_buff_signature_from_keys(
        self,
        numeric_id: int,
        owner: str,
        src: str,
        keys: set[str] | None,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> tuple[int, str, tuple[str, ...]]:
        return (
            int(numeric_id),
            self._buff_context_signature(owner, src, target_id=target_id, src_id=src_id),
            tuple(sorted(str(key) for key in (keys or set()) if str(key))),
        )

    def _remember_learned_buff_mapping(
        self,
        numeric_id: int | None,
        owner: str,
        src: str,
        assigned_items: Any,
        canonical_id: str,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> None:
        return

    def _remember_learned_buff_mapping_from_keys(
        self,
        numeric_id: int | None,
        owner: str,
        src: str,
        keys: set[str] | None,
        canonical_id: str,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> None:
        return

    def _resolve_learned_buff_mapping(
        self,
        numeric_id: int | None,
        owner: str,
        src: str,
        assigned_items: Any,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
    ) -> str | None:
        return None

    def _assigned_direct_buff_id(self, items: Any) -> str | None:
        if not isinstance(items, list):
            return None
        candidates: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("target_key") or item.get("targetKey") or "").lower()
            if "buff_id" not in key and "child_buff_id" not in key:
                continue
            value = str(item.get("string_value") or item.get("stringValue") or "")
            if value.startswith("buff_") and self.resolver.has_buff(value):
                candidates.append(value)
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _write_buff_start(
        self,
        ts_ms: int,
        buff_id: str,
        buff_uid: int,
        owner: str,
        src: str,
        assigned_items: Any,
        *,
        target_id: int | None = None,
        src_id: int | None = None,
        creation_event: dict[str, Any] | None = None,
        creation_detail: dict[str, Any] | None = None,
    ) -> None:
        if target_id is not None or src_id is not None:
            self.buff_actor_ids_by_uid[buff_uid] = (target_id, src_id)
        previous_id = self.buff_id_by_uid.get(buff_uid, "")
        previous_values = self.buff_values_by_uid.get(buff_uid, {})
        previous_keys = self.buff_keys_by_uid.get(buff_uid, set())
        if previous_id and previous_id != buff_id and not self._prefer_buff_start(previous_id, buff_id):
            buff_id = previous_id
        new_values = self._assigned_items_to_values(assigned_items)
        new_keys = self._assigned_items_to_keys(assigned_items)
        identity_unchanged = bool(previous_id and previous_id == buff_id)
        values_add_information = any(previous_values.get(key) != value for key, value in new_values.items())
        if identity_unchanged:
            merged_values = dict(previous_values)
            merged_values.update(new_values)
            merged_keys = set(previous_keys) | set(new_keys)
        else:
            merged_values = new_values
            merged_keys = new_keys
        self.buff_id_by_uid[buff_uid] = buff_id
        self.buff_values_by_uid[buff_uid] = merged_values
        self.buff_keys_by_uid[buff_uid] = merged_keys
        if previous_id and previous_id != buff_id and previous_id.isdigit() and buff_id and buff_id != "unknown_buff" and not buff_id.isdigit():
            self._remember_learned_buff_mapping_from_keys(
                _intish(previous_id),
                owner,
                src,
                previous_keys or self._assigned_items_to_keys(assigned_items),
                buff_id,
            )
            self._remember_learned_buff_mapping(
                _intish(previous_id),
                owner,
                src,
                {"blackboard": {key: {"float_value": value} for key, value in previous_values.items()}},
                buff_id,
            )
        if not identity_unchanged or values_add_information:
            # Repeated create callbacks need not be a newly allocated Buff.
            # Preserve the observation without inventing another start row.
            if self._pending_buff_start_ts_ms is not None and self._pending_buff_start_ts_ms != ts_ms:
                self._flush_pending_buff_starts()
            self._pending_buff_start_ts_ms = ts_ms
            existing = self._pending_buff_start_rows.get(buff_uid)
            if existing is None:
                self._pending_buff_start_order.append(buff_uid)
                self._pending_buff_start_rows[buff_uid] = (buff_id, owner, src, assigned_items)
            else:
                prev_buff_id, prev_owner, prev_src, prev_assigned_items = existing
                if self._prefer_buff_start(prev_buff_id, buff_id):
                    self._pending_buff_start_rows[buff_uid] = (buff_id, owner, src, assigned_items)
        if creation_event is not None:
            # generation belongs to the operation owner entity. Neither
            # client create schema contains a generation for the new Buff.
            observation = {
                'schemaVersion': 1, 'buffUid': str(buff_uid), 'buffTemplate': buff_id,
                'sourceActorId': str(src_id) if src_id is not None else None,
                'targetActorId': str(target_id) if target_id is not None else None,
                'sessionId': creation_event.get('session_id'),
                'operationSeq': creation_event.get('seq_id'),
                'operationOwnerId': creation_event.get('operation_owner_id'),
                'operationGeneration': creation_event.get('generation'),
                'generationScope': 'operation_owner', 'sourceEvent': creation_event.get('type'),
                'buffNumId': ((creation_detail or {}).get('buff_num_id')
                              if creation_detail is not None else creation_event.get('int_id')),
                'buffId': ((creation_detail or {}).get('buff_id')
                           if creation_detail is not None else creation_event.get('str_id')),
                'buffTemplateId': creation_event.get('buff_template_id'),
                'assignedItems': (creation_detail.get('assigned_items') if creation_detail is not None
                                  else assigned_items if isinstance(assigned_items, list) else None),
                'isNewInstance': None, 'priorUidObserved': bool(previous_id),
                'observationKind': 'creation_or_refresh', 'enhanceMultiplier': None,
            }
            if creation_detail is not None:
                observation['actionId'] = (creation_event.get('action') or {}).get('action_id')
                observation['triggerType'] = creation_event.get('trigger_type')
                observation['creationActionType'] = (creation_event.get('action') or {}).get('action_type')
                observation['creationActionRuntimeCase'] = creation_event.get('action_runtime_case')
            if type(observation['operationOwnerId']) in (int, str):
                observation['operationOwnerId'] = str(observation['operationOwnerId'])
            self._line(ts_ms, 'BUFF_CREATE_OBSERVED ' + json.dumps(
                observation, ensure_ascii=False, separators=(',', ':'), allow_nan=False))

    def _packet_buff_mapping_applies(self, mapping: dict[str, Any], owner: str, src: str) -> bool:
        return self.resolver._packet_buff_mapping_applies(
            mapping,
            owner,
            src,
            self.active_suits_by_char,
            self.active_weapons_by_char,
        )

    def _resolve_buff_template(
        self,
        str_id: Any = None,
        int_id: Any = None,
        *,
        owner: str = "",
        src: str = "",
        assigned_items: Any = None,
    ) -> str:
        return self.resolver.resolve_buff(
            str_id,
            _intish(int_id),
            context=PacketResolveContext(
                owner=owner,
                src=src,
                active_suits_by_char=self.active_suits_by_char,
                active_weapons_by_char=self.active_weapons_by_char,
                blackboard_values=self._assigned_list_to_values(assigned_items),
                blackboard_keys=self._assigned_items_to_keys(assigned_items),
            ),
        )

    def _resolve_skill_template(self, str_id: Any = None, int_id: Any = None, *, owner_hint: str = "") -> str | None:
        number = _intish(int_id)
        return self.resolver.resolve_skill(
            str_id,
            number,
            context=PacketResolveContext(
                owner_hint=owner_hint or (self.skill_owner_by_int.get(number) if number is not None else "") or "",
            ),
        )

    @staticmethod
    def _character_from_template(template: str | None) -> str | None:
        if not template:
            return None
        parts = template.split("_")
        if len(parts) >= 3 and parts[0] == "chr" and parts[1].isdigit():
            return "_".join(parts[:3])
        return None

    def _resolve_created_buff_template(self, event: dict[str, Any], detail: dict[str, Any], buff_uid: int, *, owner: str = "", src: str = "") -> str:
        raw_template = _template_id(detail.get("buff_id"))
        if raw_template:
            return raw_template
        buff_num_id = _intish(detail.get("buff_num_id"))
        if buff_num_id is not None:
            resolved_numeric = self._resolve_buff_template(
                None,
                buff_num_id,
                owner=owner,
                src=src,
                assigned_items=detail.get("assigned_items"),
            )
            # The create row's numeric template is more authoritative than a
            # cached UID or inferred parent graph, even without trial loadout.
            if resolved_numeric:
                return resolved_numeric
        existing = self.buff_id_by_uid.get(buff_uid)
        if existing and existing != "unknown_buff":
            return existing
        parent_type = str(event.get("template_type") or "").lower()
        if parent_type == "skill":
            parent_id = self._resolve_skill_template(
                event.get("template_str_id"),
                event.get("template_int_id"),
                owner_hint=self._character_from_template(src) or self._character_from_template(owner) or "",
            ) or ""
        else:
            parent_uid = _intish(event.get("inst_id"))
            existing_parent = self.buff_id_by_uid.get(parent_uid) if parent_uid else None
            if existing_parent and existing_parent != "unknown_buff" and not existing_parent.isdigit():
                parent_id = existing_parent
            else:
                parent_id = self._resolve_buff_template(
                    event.get("template_str_id"),
                    event.get("template_int_id"),
                    owner=owner,
                    src=src,
                )

        resolved_created = self.resolver.resolve_created_buff(
            parent_type=parent_type,
            parent_canonical_id=parent_id,
            assigned_items=detail.get("assigned_items"),
        )
        if resolved_created:
            return resolved_created

        return "unknown_buff"
