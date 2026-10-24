from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import secrets


@dataclass(slots=True)
class ServiceConfig:
    ws_port: int
    log_dir: Path
    log_level: str
    game_exe: str
    npcap_device: str
    dll_dir: Path
    debug_enabled: bool
    debug_dir: Path
    rsa_key_txt: Path
    name_index_path: Path
    trace_file: Path | None = None
    status_file: Path | None = None
    trace_enabled: bool = True
    merge_multi_phase_enemy_battles: bool = False
    ws_browser_token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
