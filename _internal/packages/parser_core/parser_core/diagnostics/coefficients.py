"""Read optional workbook skill coefficients for diagnostic presentation."""
from __future__ import annotations
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from parser_core.catalog.diagnostics import (
    _REPO_ROOT,
)


_XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _damage_doc_workbook_path() -> Path:
    return _REPO_ROOT.parent / "endfield_docs" / "干员属性.xlsx"


@lru_cache(maxsize=1)
def _load_damage_doc_sheet_rows() -> dict[str, list[list[str | None]]]:
    path = _damage_doc_workbook_path()
    if not path.exists():
        return {}
    sheets: dict[str, list[list[str | None]]] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("a:si", _XLSX_NS):
                    texts = [node.text or "" for node in si.iterfind(".//a:t", _XLSX_NS)]
                    shared_strings.append("".join(texts))

            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rel_map: dict[str, str] = {}
            for rel in rels:
                rid = rel.attrib.get("Id")
                target = rel.attrib.get("Target")
                if rid and target:
                    rel_map[rid] = target

            def cell_value(cell: ET.Element) -> str | None:
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    texts = [node.text or "" for node in cell.iterfind(".//a:t", _XLSX_NS)]
                    return "".join(texts)
                value = cell.find("a:v", _XLSX_NS)
                if value is None:
                    return None
                raw = value.text
                if cell_type == "s":
                    try:
                        return shared_strings[int(raw)]
                    except Exception:
                        return raw
                return raw

            sheet_root = workbook.find("a:sheets", _XLSX_NS)
            if sheet_root is None:
                return {}
            for sheet in sheet_root:
                name = sheet.attrib.get("name")
                rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target = rel_map.get(rid or "")
                if not name or not target:
                    continue
                sheet_path = "xl/" + target if not target.startswith("xl/") else target
                if sheet_path not in zf.namelist():
                    continue
                xml_root = ET.fromstring(zf.read(sheet_path))
                rows: list[list[str | None]] = []
                for row in xml_root.findall(".//a:sheetData/a:row", _XLSX_NS):
                    values = [cell_value(cell) for cell in row.findall("a:c", _XLSX_NS)]
                    rows.append(values)
                sheets[name] = rows
    except Exception:
        return {}
    return sheets


def _parse_doc_scalar(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
        try:
            return float(text) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _load_damage_doc_skill_scalar_catalog() -> dict[str, dict[str, dict[int, float]]]:
    rows = _load_damage_doc_sheet_rows().get("干员技能属性") or []
    catalog: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    if not rows:
        return {}
    for row in rows[1:]:
        if len(row) < 5:
            continue
        skill_id = str(row[2] or "").strip()
        key = str(row[3] or "").strip()
        if not skill_id or not key:
            continue
        for index, raw_value in enumerate(row[4:16], start=1):
            scalar = _parse_doc_scalar(raw_value)
            if scalar is None:
                continue
            catalog[skill_id][key][index] = scalar
    return {
        skill_id: {key: dict(levels) for key, levels in values.items()}
        for skill_id, values in catalog.items()
    }


def _skill_doc_scalar(skill_key: str | None, skill_level: int | None) -> float | None:
    if not skill_key or not skill_level or skill_level <= 0:
        return None
    catalog = _load_damage_doc_skill_scalar_catalog()
    candidate_keys = [str(skill_key)]
    text = str(skill_key)
    for candidate in (
        text.removesuffix("_blocked"),
        text.removesuffix("_projhit"),
        text.removesuffix("_projhit_blocked"),
    ):
        if candidate and candidate not in candidate_keys:
            candidate_keys.append(candidate)
    if text.endswith("_projhit"):
        base = text.removesuffix("_projhit")
        if base and base not in candidate_keys:
            candidate_keys.append(base)
    for candidate_key in candidate_keys:
        rows = catalog.get(candidate_key, {})
        if not rows:
            continue
        for key_name in ("atk_scale", "display_atk_scale"):
            values = rows.get(key_name)
            if isinstance(values, dict) and skill_level in values:
                return values[skill_level]
    return None
