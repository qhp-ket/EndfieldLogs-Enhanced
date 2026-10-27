"""Public file-writing state used by application-level file operations."""
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class WritingKind(StrEnum):
    IDLE = 'idle'
    ACTIVE = 'active'
    UNCERTAIN = 'uncertain'


@dataclass(frozen=True, slots=True)
class CaptureWritingState:
    kind: WritingKind
    paths: tuple[Path, ...] = ()

    def permits_rename(self, path):
        return self.kind == WritingKind.IDLE or (self.kind == WritingKind.ACTIVE
            and Path(path).resolve() not in self.paths)
