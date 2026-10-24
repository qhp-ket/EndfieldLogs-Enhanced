from __future__ import annotations
import json
from datetime import datetime
from typing import Any
from endfield_pcap.trace.formatting import _intish, _template_id, _blackboard_pairs


class BuffEvents:
    def _handle_add_buff_op(self, event: dict[str, Any], ts_ms: int) -> None:
        buff_uid = _intish(event.get("buff_inst_id"))
        if not buff_uid:
            return
        buff_id, owner, src, src_id, target_id = self._resolve_add_buff_event(event, ts_ms)
        existing = self.buff_id_by_uid.get(buff_uid, "")
        if existing and existing != "unknown_buff" and not existing.isdigit():
            self._write_buff_start(ts_ms, existing, buff_uid, owner, src, event.get("assigned_items"), target_id=target_id, src_id=src_id, creation_event=event)
            return
        self._remember_actor_alias_for_buff(src_id, target_id, _intish(event.get("int_id")), buff_id)
        self._write_buff_start(ts_ms, buff_id, buff_uid, owner, src, event.get("assigned_items"), target_id=target_id, src_id=src_id, creation_event=event)

    def _resolve_add_buff_event(self, event: dict[str, Any], ts_ms: int) -> tuple[str, str, str, int | None, int | None]:
        src_id = _intish(event.get("src_inst_id"))
        target_id = _intish(event.get("target_inst_id"))
        if src_id and target_id and src_id == target_id:
            self._maybe_map_next_loadout_actor(src_id, ts_ms, source="bootstrap_buff")
        owner = self._name_for_event_id(target_id)
        src = self._name_for_event_id(src_id)
        buff_id = self._resolve_buff_template(
            event.get("str_id"),
            event.get("int_id"),
            owner=owner,
            src=src,
            assigned_items=event.get("assigned_items"),
        )
        if not buff_id or buff_id == "unknown_buff" or buff_id.isdigit():
            learned = self._resolve_learned_buff_mapping(
                _intish(event.get("int_id")),
                owner,
                src,
                event.get("assigned_items"),
                target_id=target_id,
                src_id=src_id,
            )
            if learned:
                buff_id = learned
        if (
            (not buff_id or buff_id == "unknown_buff" or buff_id.isdigit())
            and (src_id or target_id)
        ):
            alias_owner = self._actor_alias_by_id(target_id)
            alias_src = self._actor_alias_by_id(src_id)
            if alias_owner != owner or alias_src != src:
                retry = self._resolve_buff_template(
                    event.get("str_id"),
                    event.get("int_id"),
                    owner=alias_owner,
                    src=alias_src,
                    assigned_items=event.get("assigned_items"),
                )
                if (
                    retry
                    and retry != buff_id
                    and retry != "unknown_buff"
                    and (not retry.isdigit() or buff_id.isdigit())
                ):
                    buff_id = retry
                    owner = alias_owner
                    src = alias_src
        self._remember_learned_buff_mapping(
            _intish(event.get("int_id")),
            owner,
            src,
            event.get("assigned_items"),
            buff_id,
            target_id=target_id,
            src_id=src_id,
        )
        return buff_id, owner, src, src_id, target_id

    def _flush_pending_add_buffs(self) -> None:
        if not self._pending_add_buff_events:
            self._pending_add_buff_ts_ms = None
            return
        ts_ms = self._pending_add_buff_ts_ms
        if ts_ms is None:
            ts_ms = self._last_ts_ms
        if ts_ms is None:
            ts_ms = int(datetime.now().timestamp() * 1000)
        resolved_rows: list[dict[str, Any]] = []
        for event in self._pending_add_buff_events:
            buff_uid = _intish(event.get("buff_inst_id"))
            if not buff_uid:
                continue
            buff_id, owner, src, src_id, target_id = self._resolve_add_buff_event(event, ts_ms)
            resolved_rows.append(
                {
                    "event": event,
                    "buff_uid": buff_uid,
                    "src_id": src_id,
                    "target_id": target_id,
                    "owner": owner,
                    "src": src,
                    "buff_id": buff_id,
                }
            )

        self._apply_group_companion_inference(resolved_rows)

        for row in resolved_rows:
            event = row["event"]
            buff_id = str(row["buff_id"])
            owner = str(row["owner"])
            src = str(row["src"])
            self._remember_learned_buff_mapping(
                _intish(event.get("int_id")),
                owner,
                src,
                event.get("assigned_items"),
                buff_id,
                target_id=row.get("target_id"),
                src_id=row.get("src_id"),
            )
            self._remember_actor_alias_for_buff(
                row.get("src_id"),
                row.get("target_id"),
                _intish(event.get("int_id")),
                buff_id,
            )
            self._write_buff_start(ts_ms, buff_id, int(row["buff_uid"]), owner, src, event.get("assigned_items"), target_id=row.get("target_id"), src_id=row.get("src_id"), creation_event=event)

        self._pending_add_buff_events.clear()
        self._pending_add_buff_ts_ms = None

    def _flush_pending_create_buff_triggers(self) -> None:
        if self._pending_create_buff_events:
            ts_ms = self._pending_create_buff_ts_ms
            if ts_ms is None:
                ts_ms = self._last_ts_ms
            if ts_ms is None:
                raise ValueError("pending buff actions have no timestamp")
            self._handle_grouped_create_buff_events(self._pending_create_buff_events, ts_ms)
        self._pending_create_buff_events.clear()
        self._pending_create_buff_ts_ms = None

    def _handle_grouped_create_buff_events(self, events: list[dict[str, Any]], ts_ms: int) -> None:
        # Preserve each operation's phase and order, including Execute/End
        # pairs for the same instance in one timestamp group.
        for event in events:
            action = event.get("action")
            if isinstance(action, dict):
                self._write_create_buffs(ts_ms, event, action.get("create_buff_action"))

    def _apply_group_companion_inference(self, rows: list[dict[str, Any]]) -> None:
        return

    def _handle_finish_buff_op(self, event: dict[str, Any], ts_ms: int) -> None:
        buff_uid = _intish(event.get("buff_inst_id"))
        if not buff_uid:
            return
        buff_id = self.buff_id_by_uid.get(buff_uid, "")
        self.buff_seq += 1
        self._line(ts_ms, f'BUFF_END #{self.buff_seq} id="{buff_id}" uid={buff_uid}')
        self.buff_id_by_uid.pop(buff_uid, None)
        self.buff_actor_ids_by_uid.pop(buff_uid, None)
        self.buff_values_by_uid.pop(buff_uid, None)
        self.buff_keys_by_uid.pop(buff_uid, None)

    def _write_create_buffs(self, ts_ms: int, event: dict[str, Any], create_buff_action: Any) -> None:
        if not isinstance(create_buff_action, dict):
            return
        details = create_buff_action.get("details") or []
        if not isinstance(details, list):
            return
        trigger_type = event.get('trigger_type')
        if type(trigger_type) is int and trigger_type == 2:
            # Current native CreateBuffAction.OnEnd emits these same detail
            # rows as an explicit finish list (BATTLE_TRIGGER_TYPE.End).
            self._write_finish_buffs(ts_ms, {'finish_buffs': details})
            return
        if type(trigger_type) is not int or trigger_type != 0:
            for detail in details:
                if not isinstance(detail, dict) or not _intish(detail.get('buff_inst_id')):
                    continue
                self._line(ts_ms, 'BUFF_ACTION_UNRESOLVED '
                           f'uid={_intish(detail.get("buff_inst_id"))} '
                           f'seq={event.get("seq_id", "unknown")} '
                           f'triggerType={trigger_type if type(trigger_type) is int else "unknown"} '
                           f'actionId={_intish((event.get("action") or {}).get("action_id"))} '
                           f'ownerId={_intish(detail.get("target_id"))} '
                           f'srcId={_intish(detail.get("source_id"))}')
            return
        inferred_parent_id, inferred_children = self._infer_unresolved_parent_graph(event, details)
        if inferred_parent_id:
            parent_uid = _intish(event.get("inst_id"))
            if parent_uid:
                self.buff_id_by_uid[parent_uid] = inferred_parent_id
                owner = self._name_for_id((details[0].get("target_id") if details and isinstance(details[0], dict) else None) or event.get("owner_id"))
                src = self._name_for_id((details[0].get("source_id") if details and isinstance(details[0], dict) else None) or event.get("owner_id"))
                self._write_buff_start(ts_ms, inferred_parent_id, parent_uid, owner, src, {})
        for detail in details:
            if not isinstance(detail, dict):
                continue
            buff_uid = _intish(detail.get("buff_inst_id"))
            if not buff_uid:
                continue
            owner = self._name_for_id(detail.get("target_id"))
            src = self._name_for_id(detail.get("source_id"))
            has_explicit_template = bool(_template_id(detail.get("buff_id"))) or _intish(detail.get("buff_num_id")) is not None
            buff_id = (
                self._resolve_created_buff_template(event, detail, buff_uid, owner=owner, src=src)
                if has_explicit_template
                else inferred_children.get(buff_uid)
                or self._resolve_created_buff_template(event, detail, buff_uid, owner=owner, src=src)
            )
            assigned = {"blackboard": self._assigned_list_to_blackboard(detail.get("assigned_items"))}
            self._write_buff_start(ts_ms, buff_id, buff_uid, owner, src, assigned, target_id=_intish(detail.get("target_id")), src_id=_intish(detail.get("source_id")), creation_event=event, creation_detail=detail)
            # Preserve the create row's explicit environment/action relation.
            # No inferred parent graph or neighboring event supplies fields.
            origin = {
                'schemaVersion': 1, 'buffUid': str(buff_uid), 'buffTemplate': buff_id,
                'sourceActorId': str(detail.get('source_id')) if detail.get('source_id') is not None else None,
                'targetActorId': str(detail.get('target_id')) if detail.get('target_id') is not None else None,
                'environmentType': event.get('template_type'), 'ownerType': event.get('owner_type'),
                'environmentInstId': str(event.get('inst_id')) if event.get('inst_id') is not None else None,
                'templateStrId': event.get('template_str_id'), 'templateIntId': event.get('template_int_id'),
                'actionId': (event.get('action') or {}).get('action_id'),
                'operationSeq': event.get('seq_id'), 'triggerType': trigger_type,
            }
            self._line(ts_ms, 'BUFF_ORIGIN ' + json.dumps(origin, ensure_ascii=False, separators=(',', ':')))

    def _infer_unresolved_parent_graph(self, event: dict[str, Any], details: list[Any]) -> tuple[str | None, dict[int, str]]:
        return None, {}

    def _write_finish_buffs(self, ts_ms: int, finish_buff_action: Any) -> None:
        if not isinstance(finish_buff_action, dict):
            return
        details = finish_buff_action.get("finish_buffs") or []
        if not isinstance(details, list):
            return
        for detail in details:
            if not isinstance(detail, dict):
                continue
            buff_uid = _intish(detail.get("buff_inst_id"))
            if not buff_uid:
                continue
            buff_id = self.buff_id_by_uid.get(buff_uid, "")
            self.buff_seq += 1
            self._line(ts_ms, f'BUFF_END #{self.buff_seq} id="{buff_id}" uid={buff_uid}')
            self.buff_id_by_uid.pop(buff_uid, None)
            self.buff_actor_ids_by_uid.pop(buff_uid, None)
            self.buff_values_by_uid.pop(buff_uid, None)
            self.buff_keys_by_uid.pop(buff_uid, None)

    def _prefer_buff_start(self, previous_id: str, new_id: str) -> bool:
        if previous_id == new_id:
            return False
        if previous_id.isdigit():
            static_previous = self.resolver.static_buff_by_numeric.get(previous_id)
            if static_previous and new_id != static_previous:
                return False
        prev_canonical = previous_id and previous_id != "unknown_buff" and not previous_id.isdigit()
        new_canonical = new_id and new_id != "unknown_buff" and not new_id.isdigit()
        if new_canonical and not prev_canonical:
            return True
        if prev_canonical and not new_canonical:
            return False
        if new_id == "unknown_buff" and previous_id != "unknown_buff":
            return False
        if previous_id == "unknown_buff" and new_id != "unknown_buff":
            return True
        return new_id != previous_id

    def _flush_pending_buff_starts(self) -> None:
        if not self._pending_buff_start_rows:
            self._pending_buff_start_ts_ms = None
            return
        if self._pending_buff_start_ts_ms is None:
            raise ValueError("missing buff start timestamp")
        ts_ms = self._pending_buff_start_ts_ms
        for buff_uid in self._pending_buff_start_order:
            row = self._pending_buff_start_rows.get(buff_uid)
            if row is None:
                continue
            buff_id, owner, src, assigned_items = row
            owner_id, source_id = self.buff_actor_ids_by_uid.get(buff_uid, (None, None))
            self.buff_seq += 1
            self._append_line(
                ts_ms,
                (
                    f'BUFF_START #{self.buff_seq} id="{buff_id}" uid={buff_uid} '
                    f"owner={owner} src={src} ownerId={owner_id if owner_id is not None else 'unknown'} "
                    f"srcId={source_id if source_id is not None else 'unknown'} "
                    f"dur=unknown lifeT=unknown passed=unknown enh=unknown"
                ),
            )
            pairs = _blackboard_pairs(assigned_items)
            if pairs:
                body = " ".join(f"{key}={value:.6g}" for key, value in pairs)
                self._append_line(ts_ms, f"BB[{buff_uid}]: {body}")
        self._pending_buff_start_rows.clear()
        self._pending_buff_start_order.clear()
        self._pending_buff_start_ts_ms = None
