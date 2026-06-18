"""Agent-role registry — declarative charters under ``agents/<role>/AGENT.md``.

A role is a Markdown file with simple frontmatter and a body. The body becomes the
spawned worker's appended system prompt; the frontmatter tunes how it is spawned:

    ---
    name: researcher
    description: Deep-dives a topic across the web and the knowledge base.
    model: claude-opus-4-8        # optional; omit to inherit
    tools: Read, Bash, WebSearch  # optional; maps to --allowedTools
    permission_mode: bypassPermissions   # optional; defaults from config
    ---

    You are a research worker. ...

This mirrors :mod:`agent.skills.loader` — roles are committed, travel with a fork,
and the agent writes new ones (``agent fleet new``) as it discovers missing roles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent.config import get_settings
from agent.skills.loader import _split_frontmatter

_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")

TEMPLATE = """\
---
name: {name}
description: {description}
# model: claude-opus-4-8          # optional — omit to inherit the CLI default
# tools: Read, Edit, Bash         # optional — restrict to these tools
# permission_mode: bypassPermissions
---

You are the **{name}** agent. {description}

## How you work
- Do exactly the task you are handed, fully, then stop.
- Use your native tools plus the `agent` CLI for durable infrastructure.
- Verify before you report. Your final message IS your result — make it tight.
- If you cannot finish, say precisely why so the orchestrator can re-plan.
"""


@dataclass
class AgentRole:
    name: str
    description: str
    path: Path
    model: str | None = None
    tools: list[str] | None = None
    permission_mode: str | None = None

    def body(self) -> str:
        """The role charter (everything after the frontmatter) — the system prompt."""
        _, body = _split_frontmatter(self.path.read_text(encoding="utf-8"))
        return body.strip()


def _parse_tools(raw: str) -> list[str] | None:
    parts = [t.strip() for t in raw.replace(";", ",").replace(" ", ",").split(",")]
    tools = [t for t in parts if t]
    return tools or None


class AgentRegistry:
    def __init__(self, dirs: list[Path] | None = None) -> None:
        self.dirs = dirs or [get_settings().agents_dir]
        self._roles: dict[str, AgentRole] = {}
        self.reload()

    def reload(self) -> None:
        self._roles.clear()
        for d in self.dirs:
            d = Path(d)
            if not d.exists():
                continue
            for md in sorted(d.glob("*/AGENT.md")):
                try:
                    meta, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
                except OSError:
                    continue
                name = meta.get("name") or md.parent.name
                self._roles[name] = AgentRole(
                    name=name,
                    description=meta.get("description", "").strip(),
                    path=md,
                    model=meta.get("model") or None,
                    tools=_parse_tools(meta.get("tools", "")),
                    permission_mode=meta.get("permission_mode") or None,
                )

    def all(self) -> list[AgentRole]:
        return list(self._roles.values())

    def get(self, name: str) -> AgentRole | None:
        return self._roles.get(name)

    def names(self) -> list[str]:
        return list(self._roles)

    def index(self) -> str:
        if not self._roles:
            return ""
        return "\n".join(f"- {r.name}: {r.description}" for r in self._roles.values())

    def scaffold(self, name: str, description: str = "") -> Path:
        """Write a new role charter (the 'write a new agent' path)."""
        if not _NAME.match(name):
            raise ValueError("role name must be kebab/snake_case, 2-49 chars")
        d = self.dirs[0] / name
        d.mkdir(parents=True, exist_ok=True)
        path = d / "AGENT.md"
        path.write_text(TEMPLATE.format(name=name, description=description or name), encoding="utf-8")
        self.reload()
        return path


_REGISTRY: AgentRegistry | None = None


def get_registry(*, fresh: bool = False) -> AgentRegistry:
    global _REGISTRY
    if _REGISTRY is None or fresh:
        _REGISTRY = AgentRegistry()
    return _REGISTRY
