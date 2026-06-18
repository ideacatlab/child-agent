"""Git-based self-publish with a secret-staging guard."""

from __future__ import annotations

import re
import subprocess

from agent.config import Settings, get_settings
from agent.logging import get_logger
from agent.security.secrets import looks_like_secret

log = get_logger("publish")

# Filenames that must never be committed (defence in depth beyond .gitignore).
_SECRET_FILE = re.compile(r"(^|/)\.env$|(^|/)secrets/|\.token$|cookies|github-token|\.key$", re.I)


class PublishError(Exception):
    pass


class GitPublisher:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    def _git(self, *args: str, check: bool = False) -> tuple[int, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.s.root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout + proc.stderr).strip()
        if check and proc.returncode != 0:
            raise PublishError(f"git {' '.join(args)} failed: {out}")
        return proc.returncode, out

    # ---- helpers ---------------------------------------------------------- #
    def is_repo(self) -> bool:
        rc, _ = self._git("rev-parse", "--is-inside-work-tree")
        return rc == 0

    def ensure_repo(self) -> None:
        if not self.is_repo():
            self._git("init", check=True)
            self._git("checkout", "-b", "main")

    def status(self) -> str:
        _, out = self._git("status", "--porcelain")
        return out

    def _staged_files(self) -> list[str]:
        _, out = self._git("diff", "--cached", "--name-only")
        return [line for line in out.splitlines() if line.strip()]

    def _guard_secrets(self) -> None:
        for name in self._staged_files():
            if _SECRET_FILE.search(name):
                self._git("reset", "-q")
                raise PublishError(f"ABORT: refusing to commit secret-like file: {name}")
        # content scan of the staged diff
        _, diff = self._git("diff", "--cached")
        for line in diff.splitlines():
            if line.startswith("+") and looks_like_secret(line):
                self._git("reset", "-q")
                raise PublishError("ABORT: staged diff appears to contain a secret value.")

    # ---- the operation ---------------------------------------------------- #
    def publish(self, message: str, *, paths: list[str] | None = None, push: bool = True) -> str:
        self.ensure_repo()
        if paths:
            for p in paths:
                self._git("add", "--", p)
        else:
            self._git("add", "-A")

        if not self._staged_files():
            return "nothing to publish (no staged changes)"

        self._guard_secrets()

        author = self.s.git_author
        trailer = "\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
        commit_msg = message.strip() + trailer
        env_author = []
        m = re.match(r"^(.*?)\s*<(.+?)>$", author)
        if m:
            env_author = ["-c", f"user.name={m.group(1)}", "-c", f"user.email={m.group(2)}"]
        rc, out = self._git(*env_author, "commit", "-m", commit_msg)
        if rc != 0:
            return f"commit failed (nothing to commit?): {out}"

        result = ["committed: " + message.strip()]
        if push:
            result.append(self._push())
        return "\n".join(result)

    def _push(self) -> str:
        # ensure an origin exists if a remote was configured
        rc, _ = self._git("remote", "get-url", "origin")
        if rc != 0 and self.s.git_remote:
            self._git("remote", "add", "origin", self.s.git_remote)
        rc, _ = self._git("remote", "get-url", "origin")
        if rc != 0:
            return "no git remote configured; commit kept locally (set AGENT_GIT_REMOTE to push)"
        rc, out = self._git("push", "origin", "HEAD")
        return "pushed" if rc == 0 else f"push failed: {out[-400:]}"


_PUBLISHER: GitPublisher | None = None


def get_publisher() -> GitPublisher:
    global _PUBLISHER
    if _PUBLISHER is None:
        _PUBLISHER = GitPublisher()
    return _PUBLISHER
