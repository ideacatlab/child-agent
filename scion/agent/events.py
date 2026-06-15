"""Append-only event log (JSONL) — the trace and recovery substrate.

Every meaningful step (message, thinking, tool call, tool result, error) is an
immutable line. This is OpenHands' event-sourcing idea in miniature: the log is
the source of truth you can replay and audit.
"""

from __future__ import annotations

import json
import time
from typing import Any

from scion.config import get_settings


class EventLog:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.path = get_settings().events_dir / f"{session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, **data: Any) -> None:
        record = {"ts": round(time.time(), 3), "kind": kind, **data}
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass  # logging must never break the loop

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
