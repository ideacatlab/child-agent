"""Configuration & paths.

Loads ``.env`` into the environment (``setdefault``: real env vars win), exposes a
typed :class:`Settings` snapshot, and knows where every piece of state lives. Pure
stdlib. There is no LLM/API key here — the brain (and every spawned worker) is a
``claude`` process on your subscription, not an API.

The base template is **name-agnostic**: ``AGENT_NAME`` is empty until a deployment
gives this agent an identity. All knobs are ``AGENT_*`` env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


# --------------------------------------------------------------------------- #
# project root + .env loading
# --------------------------------------------------------------------------- #
def find_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (or cwd) to the dir holding pyproject.toml/.git."""
    cur = (start or Path.cwd()).resolve()
    for cand in [cur, *cur.parents]:
        if (cand / "pyproject.toml").exists() or (cand / ".git").exists():
            return cand
    return cur


def load_env(root: Path | None = None) -> None:
    """Read ``.env`` at *root* into ``os.environ`` with setdefault (env wins)."""
    root = root or find_root()
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def set_env_var(key: str, value: str, root: Path | None = None) -> None:
    """Create-or-update a single line in ``.env`` and the live environment."""
    root = root or find_root()
    env_path = root / ".env"
    lines: list[str] = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _list_int(name: str) -> list[int]:
    out: list[int] = []
    for part in os.environ.get(name, "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


# --------------------------------------------------------------------------- #
# settings snapshot
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    # identity — empty in the base template; a deployment sets AGENT_NAME
    agent_name: str = ""

    # behavioral guidance the master prompt reads (Claude Code enforces it)
    confirm_dangerous: bool = True   # ask the operator before destructive/outward actions
    allow_publish: bool = True       # may the agent push to git unattended

    # telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_allowed_user_ids: list[int] = field(default_factory=list)

    # embeddings / rag (default backend needs nothing and costs nothing)
    embedding_backend: str = "hashing"
    embedding_model: str | None = None
    embedding_dim: int = 512

    # git self-publish
    git_remote: str | None = None
    git_author: str = "agent <agent@localhost>"

    # ---- the fleet: how worker / supervisor agents are spawned ------------ #
    claude_bin: str = "claude"            # the `claude` CLI the runner shells out to
    worker_model: str | None = None       # model for spawned workers (None = inherit)
    fleet_max_concurrency: int = 3        # max simultaneous worker processes
    fleet_timeout: int = 1800             # per-worker hard timeout (seconds)
    fleet_permission_mode: str = "bypassPermissions"  # workers run fully autonomous
    fleet_worktree: bool = False          # isolate file-mutating workers in git worktrees
    supervise_every: str | None = None    # e.g. "30m" — always-on supervision cadence

    # paths
    root: Path = field(default_factory=find_root)
    workspace: Path = field(default_factory=lambda: find_root() / "workspace")

    # ---- derived paths (committed: the agent's durable growth) ------------ #
    @property
    def authored_tools_dir(self) -> Path:
        return self.root / "authored_tools"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def skills_dirs(self) -> list[Path]:
        return [self.root / "skills", self.workspace / "skills"]

    @property
    def agents_dir(self) -> Path:
        """Committed agent-role definitions (agents/<role>/AGENT.md)."""
        return self.root / "agents"

    # ---- derived paths (private runtime state, gitignored) ---------------- #
    @property
    def memory_dir(self) -> Path:
        return self.workspace / "memory"

    @property
    def identity_file(self) -> Path:
        return self.workspace / "IDENTITY.md"

    @property
    def user_file(self) -> Path:
        return self.workspace / "USER.md"

    @property
    def memory_file(self) -> Path:
        return self.workspace / "MEMORY.md"

    @property
    def queue_db(self) -> Path:
        return self.workspace / "queue.db"

    @property
    def vectors_db(self) -> Path:
        return self.workspace / "vectors.db"

    @property
    def scheduler_db(self) -> Path:
        return self.workspace / "scheduler.db"

    @property
    def fleet_db(self) -> Path:
        return self.workspace / "fleet.db"

    @property
    def runs_dir(self) -> Path:
        """Captured stdout/stderr of spawned worker runs."""
        return self.workspace / "runs"

    @property
    def logs_dir(self) -> Path:
        return self.workspace / "logs"

    @property
    def drafts_dir(self) -> Path:
        return self.workspace / "tool_drafts"

    # ---- construction ----------------------------------------------------- #
    @classmethod
    def load(cls) -> "Settings":
        root = find_root()
        load_env(root)
        ws = os.environ.get("AGENT_WORKSPACE", "").strip()
        workspace = Path(ws).expanduser().resolve() if ws else root / "workspace"
        return cls(
            agent_name=os.environ.get("AGENT_NAME", ""),
            confirm_dangerous=_bool("AGENT_CONFIRM_DANGEROUS", True),
            allow_publish=_bool("AGENT_ALLOW_PUBLISH", True),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            telegram_allowed_user_ids=_list_int("TELEGRAM_ALLOWED_USER_IDS"),
            embedding_backend=os.environ.get("AGENT_EMBEDDING_BACKEND", "hashing").strip(),
            embedding_model=os.environ.get("AGENT_EMBEDDING_MODEL") or None,
            embedding_dim=_int("AGENT_EMBEDDING_DIM", 512),
            git_remote=os.environ.get("AGENT_GIT_REMOTE") or None,
            git_author=os.environ.get("AGENT_GIT_AUTHOR", "agent <agent@localhost>"),
            claude_bin=os.environ.get("AGENT_CLAUDE_BIN", "claude").strip() or "claude",
            worker_model=os.environ.get("AGENT_WORKER_MODEL") or None,
            fleet_max_concurrency=_int("AGENT_FLEET_MAX_CONCURRENCY", 3),
            fleet_timeout=_int("AGENT_FLEET_TIMEOUT", 1800),
            fleet_permission_mode=os.environ.get(
                "AGENT_FLEET_PERMISSION_MODE", "bypassPermissions").strip() or "bypassPermissions",
            fleet_worktree=_bool("AGENT_FLEET_WORKTREE", False),
            supervise_every=os.environ.get("AGENT_SUPERVISE_EVERY") or None,
            root=root,
            workspace=workspace,
        )

    def ensure_dirs(self) -> None:
        for d in (
            self.workspace, self.memory_dir, self.logs_dir, self.drafts_dir, self.runs_dir,
            self.authored_tools_dir, self.knowledge_dir, self.root / "skills", self.agents_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings.load()
    s.ensure_dirs()
    return s


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
