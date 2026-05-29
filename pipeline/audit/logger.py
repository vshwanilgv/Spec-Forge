from __future__ import annotations

import threading

from pipeline.models import AuditEntry


class AuditLogger:
    def __init__(self, log_path: str) -> None:
        self._log_path = log_path
        self._lock = threading.Lock()

    def log(self, entry: AuditEntry) -> None:
        line = entry.model_dump_json() + "\n"
        with self._lock:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(line)
