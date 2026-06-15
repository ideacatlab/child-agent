"""Conversation session: the message list + JSON persistence.

Messages are plain JSON-safe dicts (assistant content is normalized by the LLM
layer), so a session round-trips to disk and resumes cleanly.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from scion.config import get_settings


@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---- construction ----------------------------------------------------- #
    @classmethod
    def new(cls, prefix: str = "s") -> "Session":
        sid = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        return cls(id=sid)

    @classmethod
    def load(cls, session_id: str) -> "Session | None":
        path = get_settings().sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(id=data["id"], messages=data.get("messages", []), metadata=data.get("metadata", {}))

    # ---- mutation --------------------------------------------------------- #
    def add_user(self, content: str | list) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: list[dict]) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict]) -> None:
        self.messages.append({"role": "user", "content": results})

    def trim(self, keep_last: int = 80) -> None:
        """Cheap safeguard against unbounded growth (real compaction is TODO)."""
        if len(self.messages) > keep_last:
            self.messages = self.messages[-keep_last:]

    # ---- persistence ------------------------------------------------------ #
    def save(self) -> None:
        s = get_settings()
        s.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = s.sessions_dir / f"{self.id}.json"
        payload = {"id": self.id, "messages": self.messages, "metadata": self.metadata}
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
