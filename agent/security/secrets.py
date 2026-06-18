"""Secret registry + masking.

Collects secret *values* from the environment and replaces them with opaque
placeholders anywhere they would otherwise be exposed (tool output, logs, the
transcript). This is the OpenHands ``SecretRegistry`` idea: secrets are known to
the harness, never handed to the model verbatim.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

# Env var names whose *values* are secret. Anything matching these substrings is
# treated as sensitive; the heuristic catches custom keys too.
_SENSITIVE_HINTS = ("token", "secret", "api_key", "apikey", "password", "passwd", "_key")
# Keys to never treat as secret even if they match a hint (avoid masking noise).
_ALLOW = {"AGENT_EMBEDDING_MODEL", "AGENT_GIT_AUTHOR"}


def _is_sensitive(key: str) -> bool:
    if key in _ALLOW:
        return False
    low = key.lower()
    return any(h in low for h in _SENSITIVE_HINTS)


class SecretRegistry:
    """Holds secret values and masks them out of arbitrary text."""

    def __init__(self) -> None:
        # value -> placeholder label
        self._secrets: dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        self._secrets.clear()
        for key, val in os.environ.items():
            if val and len(val) >= 6 and _is_sensitive(key):
                self._secrets[val] = f"<secret:{key}>"

    def register(self, value: str, label: str = "secret") -> None:
        if value and len(value) >= 6:
            self._secrets[value] = f"<secret:{label}>"

    def mask(self, text: str) -> str:
        """Replace every known secret value with its placeholder."""
        if not text:
            return text
        # Replace longest secrets first so substrings don't pre-empt them.
        for value in sorted(self._secrets, key=len, reverse=True):
            if value in text:
                text = text.replace(value, self._secrets[value])
        return text

    def scan(self, text: str) -> list[str]:
        """Return labels of any secrets found in *text* (for leak auditing)."""
        return [self._secrets[v] for v in self._secrets if v in (text or "")]


# A coarse high-entropy / known-prefix detector for *unknown* secrets, used by
# the self-publish guard as a second line of defence.
_LEAK_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def looks_like_secret(text: str) -> bool:
    return any(p.search(text or "") for p in _LEAK_PATTERNS)


@lru_cache(maxsize=1)
def get_secret_registry() -> SecretRegistry:
    return SecretRegistry()
