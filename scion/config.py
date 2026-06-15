"""Configuration & paths.

Loads ``.env`` into the process environment (``setdefault`` semantics: real env
vars always win), exposes a typed :class:`Settings` snapshot, and knows where
every piece of state lives on disk. Pure stdlib.

Inherited shape from ali-fleet-recovery's ``aliconf.py``: a single shared loader
with ``set_env_var`` write-back (used for Telegram chat-id auto-capture).
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
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def set_env_var(key: str, value: str, root: Path | None = None) -> None:
    """Create-or-update a single line in ``.env`` and the live environment.

    Used to persist auto-discovered values (e.g. ``TELEGRAM_CHAT_ID``) so the
    next run already knows them — exactly the ali-fleet-recovery trick.
    """
    root = root or find_root()
    env_path = root / ".env"
    lines: list[str] = []
    found = False
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
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
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _list_int(name: str) -> list[int]:
    raw = os.environ.get(name, "").strip()
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


# --------------------------------------------------------------------------- #
# settings snapshot
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    # identity
    agent_name: str = "Scion"

    # llm
    model: str = "claude-opus-4-8"
    effort: str = "high"
    max_tokens: int = 16000
    thinking: str = "adaptive"  # "adaptive" | "off"

    # autonomy & safety
    autonomous: bool = False
    require_confirmation: bool = True
    allow_self_tooling: bool = True
    tool_autoapply: bool = False
    max_tool_iterations: int = 40  # circuit breaker for the agent loop

    # telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_allowed_user_ids: list[int] = field(default_factory=list)

    # embeddings / rag
    embedding_backend: str = "hashing"
    embedding_model: str | None = None
    embedding_dim: int = 512

    # git self-publish
    git_remote: str | None = None
    git_author: str = "scion <agent@localhost>"

    # paths
    root: Path = field(default_factory=find_root)
    workspace: Path = field(default_factory=lambda: find_root() / "workspace")

    # ---- derived paths ---------------------------------------------------- #
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
    def memory_dir(self) -> Path:
        return self.workspace / "memory"

    @property
    def soul_file(self) -> Path:
        return self.workspace / "SOUL.md"

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
    def sessions_dir(self) -> Path:
        return self.workspace / "sessions"

    @property
    def events_dir(self) -> Path:
        return self.workspace / "events"

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
        ws_override = os.environ.get("SCION_WORKSPACE", "").strip()
        workspace = Path(ws_override).expanduser().resolve() if ws_override else root / "workspace"
        thinking = os.environ.get("SCION_THINKING", "adaptive").strip().lower()
        return cls(
            agent_name=os.environ.get("SCION_AGENT_NAME", "Scion"),
            model=os.environ.get("SCION_MODEL", "claude-opus-4-8").strip(),
            effort=os.environ.get("SCION_EFFORT", "high").strip(),
            max_tokens=_int("SCION_MAX_TOKENS", 16000),
            thinking="off" if thinking in ("off", "0", "false", "disabled") else "adaptive",
            autonomous=_bool("SCION_AUTONOMOUS", False),
            require_confirmation=_bool("SCION_REQUIRE_CONFIRMATION", True),
            allow_self_tooling=_bool("SCION_ALLOW_SELF_TOOLING", True),
            tool_autoapply=_bool("SCION_TOOL_AUTOAPPLY", False),
            max_tool_iterations=_int("SCION_MAX_TOOL_ITERATIONS", 40),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            telegram_allowed_user_ids=_list_int("TELEGRAM_ALLOWED_USER_IDS"),
            embedding_backend=os.environ.get("SCION_EMBEDDING_BACKEND", "hashing").strip(),
            embedding_model=os.environ.get("SCION_EMBEDDING_MODEL") or None,
            embedding_dim=_int("SCION_EMBEDDING_DIM", 512),
            git_remote=os.environ.get("SCION_GIT_REMOTE") or None,
            git_author=os.environ.get("SCION_GIT_AUTHOR", "scion <agent@localhost>"),
            root=root,
            workspace=workspace,
        )

    def ensure_dirs(self) -> None:
        """Create every runtime directory. Safe to call repeatedly."""
        for d in (
            self.workspace,
            self.memory_dir,
            self.sessions_dir,
            self.events_dir,
            self.logs_dir,
            self.drafts_dir,
            self.authored_tools_dir,
            self.knowledge_dir,
            self.root / "skills",
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings.load()
    s.ensure_dirs()
    return s


def reload_settings() -> Settings:
    """Drop the cached settings (after editing .env at runtime)."""
    get_settings.cache_clear()
    return get_settings()
