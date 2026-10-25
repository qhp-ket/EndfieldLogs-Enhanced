from __future__ import annotations
import json
from pathlib import Path
from endfield_pcap.runtime.paths import bundle_root


ROOT = bundle_root()

APP_ICON_PNG = ROOT / "icon.png"

APP_ICON_ICO = ROOT / "icon.ico"

ICON_DIR = ROOT / "icon" / "Texture2D"

ACTOR_IMAGE_TABLE = ROOT / "jsondata" / "ActorImageTable.json"

APP_USER_MODEL_ID = "EndfieldLogsEnhanced.Desktop"

def _app_icon_path() -> Path | None:
    if APP_ICON_ICO.exists():
        return APP_ICON_ICO
    if APP_ICON_PNG.exists():
        return APP_ICON_PNG
    return None

def _load_avatar_index() -> dict[str, Path]:
    if not ACTOR_IMAGE_TABLE.exists():
        return {}
    payload = json.loads(ACTOR_IMAGE_TABLE.read_text(encoding="utf-8"))
    result: dict[str, Path] = {}
    for templateid, item in payload.items():
        avatar = item.get("avatarPath")
        if avatar:
            result[str(templateid)] = ICON_DIR / f"{avatar}.png"
    return result
