from __future__ import annotations
import re
from collections import Counter
from typing import Any
from google.protobuf.json_format import MessageToDict
from endfield_pcap.data.loadout import equip_piece_catalog, normalize_gem_payload


class InventoryEvents:
    @staticmethod
    def _int_map(message_map: Any) -> dict[int, int]:
        result: dict[int, int] = {}
        try:
            items = dict(message_map).items()
        except Exception:
            return result
        for key, value in items:
            try:
                result[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _str_int_map(message_map: Any) -> dict[str, int]:
        result: dict[str, int] = {}
        try:
            items = dict(message_map).items()
        except Exception:
            return result
        for key, value in items:
            try:
                result[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return result

    @staticmethod
    def _equip_template(equip: dict[str, object] | None, equip_id: int | None = None) -> str:
        if not equip:
            return str(equip_id or "")
        return str(equip.get("template_string") or equip.get("templateid") or equip_id or "")

    @staticmethod
    def _equip_suit_id(template: str) -> str:
        meta = equip_piece_catalog().get(str(template or ""), {})
        suit_id = str(meta.get("suit_id") or "")
        if suit_id:
            return suit_id
        match = re.search(r"item_equip_t\d+_(suit_[a-z0-9]+)_", str(template or ""), re.IGNORECASE)
        return match.group(1) if match else ""

    @classmethod
    def _equip_suit_counts(cls, equip_col: dict[int, int], equip_by_inst_id: dict[int, dict[str, object]]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for equip_id in set(int(value or 0) for value in equip_col.values()):
            if not equip_id:
                continue
            suit_id = cls._equip_suit_id(cls._equip_template(equip_by_inst_id.get(equip_id), equip_id))
            if suit_id:
                counts[suit_id] += 1
        return counts

    @classmethod
    def _equip_payload(cls, equip: Any, template_string: str | None = None) -> dict[str, object]:
        equip_id = int(getattr(equip, "equipid", 0) or 0)
        return {
            "equipid": equip_id,
            "templateid": int(getattr(equip, "templateid", 0) or 0),
            "template_string": template_string or "",
            "equip_char_id": int(getattr(equip, "equip_char_id", 0) or 0),
            "enhance": cls._int_map(getattr(equip, "enhance", {})),
            "legacy_enhance": cls._int_map(getattr(equip, "legacy_enhance", {})),
        }

    @staticmethod
    def _weapon_payload(weapon: Any, template_string: str | None = None) -> dict[str, object]:
        inst_id = int(getattr(weapon, "inst_id", 0) or 0)
        return {
            "inst_id": inst_id,
            "template_id": int(getattr(weapon, "template_id", 0) or 0),
            "template_string": template_string or "",
            "exp": int(getattr(weapon, "exp", 0) or 0),
            "weapon_lv": int(getattr(weapon, "weapon_lv", 0) or 0),
            "refine_lv": int(getattr(weapon, "refine_lv", 0) or 0),
            "breakthrough_lv": int(getattr(weapon, "breakthrough_lv", 0) or 0),
            "equip_char_id": int(getattr(weapon, "equip_char_id", 0) or 0),
            "attach_gem_id": int(getattr(weapon, "attach_gem_id", 0) or 0),
        }

    @staticmethod
    def _gem_payload(gem: Any, inst_id: int, template_string: str | None = None) -> dict[str, object]:
        payload = normalize_gem_payload(gem, inst_id, template_string or "")
        payload["payload"] = MessageToDict(gem, preserving_proto_field_name=True, use_integers_for_enums=False)
        return payload

    def _index_gem_payload(self, payload: dict[str, object]) -> None:
        inst_id = int(payload.get("inst_id") or 0)
        gem_id = int(payload.get("gem_id") or 0)
        weapon_id = int(payload.get("weapon_id") or 0)
        previous = self.gem_by_inst_id.get(gem_id or inst_id)
        if previous and (previous.get("terms") != payload.get("terms")
                         or int(previous.get("weapon_id") or 0) != weapon_id):
            affected = {weapon_id, int(previous.get("weapon_id") or 0)} - {0}
            for char_info in self.char_bag_by_objid.values():
                if int(char_info.get("weapon_id") or 0) in affected:
                    self._replace_weapon_source_skills(char_info, [])
        if inst_id:
            self.gem_by_inst_id[inst_id] = payload
        if gem_id:
            self.gem_by_inst_id[gem_id] = payload
        if weapon_id:
            self.gem_by_weapon_id[weapon_id] = payload
            weapon = self.weapon_by_inst_id.setdefault(weapon_id, {"inst_id": weapon_id})
            if not int(weapon.get("attach_gem_id") or 0):
                weapon["attach_gem_id"] = gem_id or inst_id

    def _index_item_grid(self, grid: Any) -> None:
        template_string = str(getattr(grid, "id", "") or "")
        inst = getattr(grid, "inst", None)
        if inst is None:
            return
        inst_id = int(getattr(inst, "inst_id", 0) or 0)
        try:
            kind = inst.WhichOneof("inst_impl")
        except Exception:
            kind = None
        if kind == "equip":
            equip = getattr(inst, "equip", None)
            if equip is not None:
                payload = self._equip_payload(equip, template_string)
                equip_id = int(payload.get("equipid") or inst_id or 0)
                if equip_id:
                    payload["equipid"] = equip_id
                    self.equip_by_inst_id[equip_id] = payload
            return
        if kind == "weapon":
            weapon = getattr(inst, "weapon", None)
            if weapon is not None:
                payload = self._weapon_payload(weapon, template_string)
                weapon_id = int(payload.get("inst_id") or inst_id or 0)
                if weapon_id:
                    payload["inst_id"] = weapon_id
                    payload["sync_source"] = "WEAPON_DATA"
                    self.weapon_by_inst_id[weapon_id] = payload
            return
        if kind == "gem" and inst_id:
            gem = getattr(inst, "gem", None)
            if gem is not None:
                self._index_gem_payload(self._gem_payload(gem, inst_id, template_string))
            return
        if inst_id and template_string.startswith("wpn_"):
            weapon = self.weapon_by_inst_id.setdefault(inst_id, {"inst_id": inst_id})
            weapon.setdefault("template_id", 0)
            weapon["template_string"] = template_string
            weapon.setdefault("sync_source", "template_only")
            weapon.setdefault("exp", 0)
            weapon.setdefault("weapon_lv", 0)
            weapon.setdefault("refine_lv", 0)
            weapon.setdefault("breakthrough_lv", 0)
            weapon.setdefault("equip_char_id", 0)
            weapon.setdefault("attach_gem_id", 0)

    def _index_item_bag(self, bag: Any) -> None:
        if bag is None:
            return
        for grid in getattr(bag, "grids", []):
            self._index_item_grid(grid)

    def _index_item_depot(self, depot: Any) -> None:
        if depot is None:
            return
        for grid in getattr(depot, "inst_list", []):
            self._index_item_grid(grid)

    def _update_item_bag_scope_sync(self, message: Any, timestamp_ms: int) -> None:
        self._index_item_bag(getattr(message, "bag", None))
        for depot in dict(getattr(message, "depot", {})).values():
            self._index_item_depot(depot)
        for depot in dict(getattr(message, "factory_depot", {})).values():
            self._index_item_depot(depot)
        self._emit_loadout_event("SC_ITEM_BAG_SCOPE_SYNC", timestamp_ms)

    def _update_item_bag_scope_modify(self, message: Any, timestamp_ms: int) -> None:
        self._index_item_bag(getattr(message, "bag", None))
        for depot in dict(getattr(message, "depot", {})).values():
            self._index_item_depot(depot)
        for depot in dict(getattr(message, "factory_depot", {})).values():
            self._index_item_depot(depot)
        self._emit_loadout_event("SC_ITEM_BAG_SCOPE_MODIFY", timestamp_ms)
