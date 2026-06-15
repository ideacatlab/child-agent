"""Letta-style core-memory blocks.

A block is a small, labelled, length-bounded piece of always-in-context memory
the agent manages with tools. The store persists to JSON and renders the blocks
into the system prompt with a live character budget so the model can see the
pressure and self-manage.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class MemoryBlock:
    label: str
    value: str = ""
    description: str = ""
    limit: int = 2000
    read_only: bool = False

    def render(self) -> str:
        used = len(self.value)
        head = f'<block label="{self.label}" chars="{used}/{self.limit}">'
        body = self.value.strip() or "(empty)"
        return f"{head}\n{body}\n</block>"


class BlockStore:
    """Persisted set of core-memory blocks."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._blocks: dict[str, MemoryBlock] = {}
        self._load()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        defaults = [
            MemoryBlock(
                "current_task",
                description="What the agent is working on right now and the plan.",
                limit=2000,
            ),
            MemoryBlock(
                "open_loops",
                description="Promises, follow-ups, and unfinished threads to revisit.",
                limit=1500,
            ),
        ]
        changed = False
        for b in defaults:
            if b.label not in self._blocks:
                self._blocks[b.label] = b
                changed = True
        if changed:
            self._save()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for d in data.get("blocks", []):
                    b = MemoryBlock(**d)
                    self._blocks[b.label] = b
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"blocks": [asdict(b) for b in self._blocks.values()]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ---- ops -------------------------------------------------------------- #
    def get(self, label: str) -> MemoryBlock | None:
        return self._blocks.get(label)

    def upsert(self, label: str, value: str, description: str = "", limit: int = 2000) -> MemoryBlock:
        b = self._blocks.get(label)
        if b is None:
            b = MemoryBlock(label=label, value=value, description=description, limit=limit)
            self._blocks[label] = b
        else:
            b.value = value
            if description:
                b.description = description
        self._save()
        return b

    def append(self, label: str, text: str) -> MemoryBlock:
        b = self._blocks.get(label) or MemoryBlock(label=label)
        sep = "\n" if b.value and not b.value.endswith("\n") else ""
        b.value = (b.value + sep + text).strip()
        if len(b.value) > b.limit:
            b.value = b.value[-b.limit :]
        self._blocks[label] = b
        self._save()
        return b

    def replace(self, label: str, old: str, new: str) -> MemoryBlock:
        b = self._blocks.get(label)
        if b is None:
            raise KeyError(label)
        if b.read_only:
            raise PermissionError(f"block {label!r} is read-only")
        b.value = b.value.replace(old, new)
        self._save()
        return b

    def all(self) -> list[MemoryBlock]:
        return list(self._blocks.values())

    def render(self, budget: int = 6000) -> str:
        """Render all blocks into a single string, respecting a char budget."""
        chunks: list[str] = []
        used = 0
        for b in self._blocks.values():
            piece = b.render()
            if used + len(piece) > budget:
                continue
            chunks.append(piece)
            used += len(piece)
        return "\n".join(chunks)
