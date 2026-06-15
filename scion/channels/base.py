"""Channel protocol + a CLI implementation."""

from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    can_confirm: bool

    def send(self, text: str) -> None:
        """Deliver a complete message to the operator."""

    def confirm(self, prompt: str) -> bool:
        """Ask the operator to approve a risky action. Return True to proceed."""


class CLIChannel:
    """Terminal channel: prints messages, asks y/n at the prompt."""

    can_confirm = True

    def __init__(self, *, assume_yes: bool = False) -> None:
        self.assume_yes = assume_yes

    def send(self, text: str) -> None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    def confirm(self, prompt: str) -> bool:
        if self.assume_yes:
            return True
        sys.stdout.write("\n" + prompt + "\n[y/N] ")
        sys.stdout.flush()
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")

    def stream(self, delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()
