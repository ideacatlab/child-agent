"""Git-backed checkpoint / diff / revert for unrestricted self-rewrite.

These are conveniences, not guard rails. The agent edits its own code freely with its
native tools; this module only lets it bookmark a good state and get back to it.
``.env`` and other secrets are already ``.gitignore``d, so ``git add -A`` here never
stages them.
"""

from __future__ import annotations

import re
import subprocess

from agent.config import get_settings


def _author_args() -> list[str]:
    """Parse ``AGENT_GIT_AUTHOR`` ('Name <email>') into git -c overrides."""
    m = re.match(r"^(.*?)\s*<(.+?)>$", get_settings().git_author)
    if m:
        return ["-c", f"user.name={m.group(1)}", "-c", f"user.email={m.group(2)}"]
    return []


def _git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(get_settings().root),
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def current_ref() -> str:
    rc, out = _git("rev-parse", "--short", "HEAD")
    return out if rc == 0 else "(no commits yet)"


def checkpoint(label: str) -> str:
    """Commit the working tree as a recovery point. No-op if the tree is clean."""
    _git("add", "-A")
    rc, _ = _git("diff", "--cached", "--quiet")
    if rc == 0:  # exit 0 => nothing staged
        return f"nothing to checkpoint (working tree clean at {current_ref()})"
    msg = f"checkpoint: {label}"
    body = "Self-rewrite checkpoint — revert with `agent evolve revert`."
    rc, out = _git(*_author_args(), "commit", "-m", msg, "-m", body)
    if rc != 0:
        return f"checkpoint failed: {out}"
    return f"checkpoint {current_ref()}: {label}"


def diff(ref: str | None = None) -> str:
    """Show changes since *ref* (default: since the last commit/checkpoint)."""
    rc, out = _git("--no-pager", "diff", ref or "HEAD")
    return out or "(no changes since last checkpoint)"


def revert(ref: str | None = None) -> str:
    """Hard-reset the working tree back to *ref* (default HEAD). Discards uncommitted work."""
    target = ref or "HEAD"
    rc, out = _git("reset", "--hard", target)
    if rc != 0:
        return f"revert failed: {out}"
    return f"reverted to {current_ref()}"


def log(limit: int = 15) -> str:
    """Recent commit / checkpoint history, newest first."""
    rc, out = _git("--no-pager", "log", "--oneline", f"-{max(1, limit)}")
    return out or "(no history)"
