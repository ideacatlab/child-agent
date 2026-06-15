"""A committed, self-rendering knowledge registry.

The agent's durable, shareable self-knowledge (findings, gaps, playbook notes),
stored as JSON and re-rendered to Markdown on every change — exactly the
self-rendering registry pattern from ali-fleet-recovery's ``podgaps.py``. Lives
under ``knowledge/`` so ``publish`` version-controls it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from scion.config import get_settings
from scion.security.policy import MODERATE, SAFE
from scion.tools.base import tool


class KnowledgeRegistry:
    def __init__(self) -> None:
        s = get_settings()
        s.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = s.knowledge_dir / "registry.json"
        self.md_path = s.knowledge_dir / "REGISTRY.md"
        self._items: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.json_path.exists():
            try:
                self._items = json.loads(self.json_path.read_text(encoding="utf-8")).get("items", [])
            except json.JSONDecodeError:
                self._items = []

    def _save(self) -> None:
        self.json_path.write_text(json.dumps({"items": self._items}, indent=2), encoding="utf-8")
        self._render()

    def _render(self) -> None:
        groups: dict[str, list[dict]] = {}
        for it in self._items:
            groups.setdefault(it.get("status", "open"), []).append(it)
        out = ["# Knowledge Registry", "", f"_rendered {datetime.now(timezone.utc):%Y-%m-%d}_", ""]
        for status in ("open", "in-progress", "resolved", "note"):
            items = groups.get(status)
            if not items:
                continue
            out.append(f"## {status}")
            for it in items:
                out.append(f"- **{it['id']}** — {it['title']}: {it['detail']}")
            out.append("")
        self.md_path.write_text("\n".join(out), encoding="utf-8")

    def note(self, title: str, detail: str, status: str = "open") -> str:
        kid = f"K-{len(self._items) + 1:03d}"
        self._items.append(
            {"id": kid, "title": title, "detail": detail, "status": status, "ts": int(time.time())}
        )
        self._save()
        return kid

    def listing(self) -> str:
        if not self._items:
            return "(knowledge registry is empty)"
        return "\n".join(
            f"{it['id']} [{it['status']}] {it['title']}: {it['detail'][:100]}" for it in self._items
        )


_REGISTRY: KnowledgeRegistry | None = None


def _reg() -> KnowledgeRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = KnowledgeRegistry()
    return _REGISTRY


@tool(risk=MODERATE)
def note_knowledge(title: str, detail: str, status: str = "open") -> str:
    """Record a durable finding/gap/playbook note in the knowledge registry.

    Args:
        title: short title.
        detail: the finding or note.
        status: open | in-progress | resolved | note.
    """
    kid = _reg().note(title, detail, status)
    return f"recorded {kid}"


@tool(risk=SAFE, parallel_safe=True)
def list_knowledge() -> str:
    """List everything in the knowledge registry."""
    return _reg().listing()
