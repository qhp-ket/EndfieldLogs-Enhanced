"""Small immutable record identity passed to an analysis window."""
from dataclasses import dataclass
from pathlib import Path

from endfield_pcap.history.index import record_key


@dataclass(frozen=True, slots=True)
class BattleRecordInfo:
    key: str
    file_path: Path
    label: str
    source_signature: tuple[int, int] | None

    @classmethod
    def from_record(cls, record, label):
        try:
            stat = record.file_path.stat()
            value = stat.st_mtime_ns, stat.st_size
        except OSError:
            value = None
        return cls(record_key(record), record.file_path, label, value)
