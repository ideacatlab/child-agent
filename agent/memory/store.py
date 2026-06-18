"""File-based memory: IDENTITY / USER / MEMORY + daily journals, plus blocks.

All plain Markdown so it's inspectable, hand-editable, and (optionally)
committable. Search is a dependency-free ranked keyword scan; when the RAG layer
is configured it can be indexed there too.

``IDENTITY.md`` is not a fixed persona — it's a starting charter the runtime may
rewrite about itself. The base template ships it nameless; a deployment fills in
``AGENT_NAME``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent.config import Settings, get_settings
from agent.memory.blocks import BlockStore

_DEFAULT_IDENTITY = """\
# IDENTITY

{whoami} I take full responsibility for performing the best I can for my users. I
work as an orchestrator: I do tasks directly when that is fastest, and I decompose
larger work across a fleet of worker agents I spawn and improve. Nothing about me is
fixed — I rewrite my own tools, skills, agents, and core whenever I find a flaw or a
better way.

## Principles
- When I have enough information to act, I act.
- I verify before I claim something is done.
- I keep secrets out of my output and never take destructive action without cause.
- I write down what I learn so my future self is sharper than my present self.
- I own every file in this repo, including this one. I improve it when I can.
"""

_DEFAULT_USER = """\
# USER

(Things I learn about my operator go here: who they are, what they want, their
preferences and constraints. I keep this current.)
"""

_DEFAULT_MEMORY = """\
# MEMORY

Durable facts and lessons. One line or short block each. I consult this before
starting work and add to it as I learn.
"""


class MemoryStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self.s.ensure_dirs()
        self.blocks = BlockStore(self.s.workspace / "blocks.json")
        self._seed()

    def _seed(self) -> None:
        if not self.s.identity_file.exists():
            whoami = (
                f"I am {self.s.agent_name}, a self-improving agent runtime."
                if self.s.agent_name
                else "I am a self-improving agent runtime (still unnamed)."
            )
            self.s.identity_file.write_text(
                _DEFAULT_IDENTITY.format(whoami=whoami), encoding="utf-8"
            )
        if not self.s.user_file.exists():
            self.s.user_file.write_text(_DEFAULT_USER, encoding="utf-8")
        if not self.s.memory_file.exists():
            self.s.memory_file.write_text(_DEFAULT_MEMORY, encoding="utf-8")

    # ---- reads ------------------------------------------------------------ #
    def identity(self) -> str:
        return _read(self.s.identity_file)

    def user(self) -> str:
        return _read(self.s.user_file)

    def memory(self) -> str:
        return _read(self.s.memory_file)

    # ---- writes ----------------------------------------------------------- #
    def remember(self, text: str) -> str:
        """Append a durable fact to MEMORY.md."""
        line = text.strip()
        if not line:
            return "nothing to remember"
        _append(self.s.memory_file, f"- {line}")
        return "remembered"

    def update_user(self, text: str) -> str:
        _append(self.s.user_file, text.strip())
        return "user profile updated"

    def journal(self, text: str) -> str:
        """Append to today's episodic journal."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts = datetime.now(timezone.utc).strftime("%H:%M")
        path = self.s.memory_dir / f"{day}.md"
        _append(path, f"- {ts} — {text.strip()}")
        return "journaled"

    # ---- search ----------------------------------------------------------- #
    def search(self, query: str, limit: int = 8) -> list[tuple[str, str]]:
        """Ranked keyword search across MEMORY + USER + journals.

        Returns ``[(source, line)]`` ordered by simple term-overlap score.
        """
        terms = [t for t in _tokenize(query) if t]
        if not terms:
            return []
        candidates: list[tuple[int, str, str]] = []
        files = [self.s.memory_file, self.s.user_file, self.s.identity_file]
        files += sorted(self.s.memory_dir.glob("*.md"), reverse=True)
        for f in files:
            if not f.exists():
                continue
            for raw in f.read_text(encoding="utf-8").splitlines():
                line = raw.strip("- ").strip()
                if not line:
                    continue
                low = line.lower()
                score = sum(1 for t in terms if t in low)
                if score:
                    candidates.append((score, f.name, line))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [(name, line) for _, name, line in candidates[:limit]]

    # ---- consolidation (dreaming) ---------------------------------------- #
    def recent_journal(self, days: int = 2) -> str:
        """Recent episodic notes — Claude Code reads these to consolidate into
        durable MEMORY itself (no LLM API call needed)."""
        out: list[str] = []
        for f in sorted(self.s.memory_dir.glob("*.md"), reverse=True)[:days]:
            out.append(f"## {f.stem}\n{_read(f)}")
        return "\n\n".join(out)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if (not path.exists() or path.read_text(encoding="utf-8").endswith("\n")) else "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(prefix + text.rstrip() + "\n")


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 1]


_MEMORY: MemoryStore | None = None


def get_memory() -> MemoryStore:
    global _MEMORY
    if _MEMORY is None:
        _MEMORY = MemoryStore()
    return _MEMORY
